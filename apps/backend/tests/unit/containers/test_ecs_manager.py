"""Tests for EcsManager (ECS Fargate service lifecycle with per-user EFS isolation).

Uses mocked boto3 clients and container_repo -- no real AWS or
DynamoDB required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from core.containers.ecs_manager import EcsManager, EcsManagerError, GATEWAY_PORT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ecs_client():
    """Create a mock ECS boto3 client."""
    client = MagicMock()
    client.create_service.return_value = {"service": {"serviceName": "openclaw-user_test_123-f4ae64abb2db"}}
    client.update_service.return_value = {}
    client.delete_service.return_value = {}
    client.describe_task_definition.return_value = {
        "taskDefinition": {
            "family": "isol8-dev-openclaw",
            "taskRoleArn": "arn:aws:iam::123456789:role/task-role",
            "executionRoleArn": "arn:aws:iam::123456789:role/exec-role",
            "networkMode": "awsvpc",
            "containerDefinitions": [{"name": "openclaw", "image": "alpine/openclaw:latest"}],
            "volumes": [
                {
                    "name": "openclaw-workspace",
                    "efsVolumeConfiguration": {
                        "fileSystemId": "fs-test123",
                        "transitEncryption": "ENABLED",
                        "authorizationConfig": {
                            "accessPointId": "fsap-base",
                            "iam": "ENABLED",
                        },
                    },
                }
            ],
            "requiresCompatibilities": ["FARGATE"],
            "cpu": "256",
            "memory": "512",
            "runtimePlatform": None,
        }
    }
    client.register_task_definition.return_value = {
        "taskDefinition": {"taskDefinitionArn": "arn:aws:ecs:us-east-1:123456789:task-definition/isol8-dev-openclaw:42"}
    }
    client.describe_services.return_value = {
        "services": [
            {
                "serviceName": "openclaw-user_test_123-f4ae64abb2db",
                "deployments": [{"id": "ecs-svc/primary", "status": "PRIMARY", "rolloutState": "IN_PROGRESS"}],
            }
        ]
    }
    client.list_tasks.return_value = {"taskArns": []}
    client.describe_tasks.return_value = {"tasks": []}
    client.deregister_task_definition.return_value = {}
    return client


@pytest.fixture
def mock_efs_client():
    """Create a mock EFS boto3 client."""
    client = MagicMock()
    client.create_access_point.return_value = {"AccessPointId": "fsap-user123"}
    client.delete_access_point.return_value = {}
    # Create a mock exceptions attribute for AccessPointNotFound
    client.exceptions = MagicMock()
    client.exceptions.AccessPointNotFound = type("AccessPointNotFound", (Exception,), {})
    return client


@pytest.fixture
def mock_settings():
    """Mock settings with test ECS configuration."""
    with patch("core.containers.ecs_manager.settings") as s:
        s.AWS_REGION = "us-east-1"
        s.ENVIRONMENT = "dev"
        s.ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-1:123456789:cluster/test-cluster"
        s.ECS_TASK_DEFINITION = "arn:aws:ecs:us-east-1:123456789:task-definition/openclaw:1"
        s.ECS_SUBNETS = "subnet-aaa,subnet-bbb"
        s.ECS_SECURITY_GROUP_ID = "sg-12345"
        s.CLOUD_MAP_SERVICE_ARN = "arn:aws:servicediscovery:us-east-1:123456789:service/srv-test"
        s.EFS_FILE_SYSTEM_ID = "fs-test123"
        yield s


@pytest.fixture
def manager(mock_settings, mock_ecs_client, mock_efs_client):
    """Create an EcsManager with mocked boto3 clients."""
    with patch("core.containers.ecs_manager.boto3") as mock_boto3:
        # Return different clients for ecs vs efs
        def client_factory(service, **kwargs):
            if service == "ecs":
                return mock_ecs_client
            elif service == "efs":
                return mock_efs_client
            return MagicMock()

        mock_boto3.client.side_effect = client_factory
        mgr = EcsManager()
    return mgr


def _make_container_dict(
    user_id="user_test_123",
    service_name="openclaw-user_test_123-f4ae64abb2db",
    gateway_token="tok-abc",
    status="running",
    access_point_id=None,
    task_definition_arn=None,
    substatus=None,
):
    """Helper to create a container dict for mocking DynamoDB repo responses."""
    d = {
        "owner_id": user_id,
        "service_name": service_name,
        "gateway_token": gateway_token,
        "status": status,
    }
    if access_point_id is not None:
        d["access_point_id"] = access_point_id
    if task_definition_arn is not None:
        d["task_definition_arn"] = task_definition_arn
    if substatus is not None:
        d["substatus"] = substatus
    return d


# ---------------------------------------------------------------------------
# Service naming
# ---------------------------------------------------------------------------


class TestServiceNaming:
    """Test deterministic, collision-resistant service name generation."""

    def test_service_name_is_deterministic(self, manager):
        """Same user_id always produces the same service name."""
        name1 = manager._service_name("user_test_123")
        name2 = manager._service_name("user_test_123")
        assert name1 == name2

    def test_service_name_includes_user_id_and_hash(self, manager):
        """Service name includes sanitized user_id and hash suffix."""
        name = manager._service_name("user_test_123")
        assert name.startswith("openclaw-user_test_123-")
        # Hash suffix is 12 hex chars
        hash_part = name.split("-")[-1]
        assert len(hash_part) == 12
        assert all(c in "0123456789abcdef" for c in hash_part)

    def test_service_name_different_users(self, manager):
        """Different user IDs produce different service names."""
        name1 = manager._service_name("user_2abc123")
        name2 = manager._service_name("user_2xyz789")
        assert name1 != name2

    def test_service_name_similar_prefix_no_collision(self, manager):
        """Users sharing a prefix (e.g. 'user_') get unique names."""
        name1 = manager._service_name("user_2aaaaaa")
        name2 = manager._service_name("user_2aaaaaab")
        assert name1 != name2


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestEcsManagerInit:
    """Test EcsManager initialization."""

    def test_parses_subnets(self, manager):
        """Subnets are parsed from comma-separated string."""
        assert manager._subnets == ["subnet-aaa", "subnet-bbb"]

    def test_security_groups(self, manager):
        """Security group is wrapped in a list."""
        assert manager._security_groups == ["sg-12345"]

    def test_cluster_set(self, manager):
        """Cluster ARN is set from settings."""
        assert "test-cluster" in manager._cluster

    def test_efs_file_system_id_set(self, manager):
        """EFS file system ID is set from settings."""
        assert manager._efs_file_system_id == "fs-test123"

    def test_empty_subnets(self, mock_settings, mock_efs_client):
        """Empty subnet string produces empty list."""
        mock_settings.ECS_SUBNETS = ""
        with patch("core.containers.ecs_manager.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc, **kw: mock_efs_client if svc == "efs" else MagicMock()
            mgr = EcsManager()
        assert mgr._subnets == []

    def test_subnets_with_whitespace(self, mock_settings, mock_efs_client):
        """Subnets with extra whitespace are trimmed."""
        mock_settings.ECS_SUBNETS = " subnet-aaa , subnet-bbb , "
        with patch("core.containers.ecs_manager.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc, **kw: mock_efs_client if svc == "efs" else MagicMock()
            mgr = EcsManager()
        assert mgr._subnets == ["subnet-aaa", "subnet-bbb"]


# ---------------------------------------------------------------------------
# _create_access_point
# ---------------------------------------------------------------------------


class TestCreateAccessPoint:
    """Test per-user EFS access point creation."""

    def test_creates_access_point(self, manager, mock_efs_client):
        """_create_access_point calls EFS API with correct parameters."""
        ap_id = manager._create_access_point("user_test_123")

        assert ap_id == "fsap-user123"
        mock_efs_client.create_access_point.assert_called_once()
        call_kwargs = mock_efs_client.create_access_point.call_args.kwargs
        assert call_kwargs["FileSystemId"] == "fs-test123"
        assert call_kwargs["PosixUser"] == {"Uid": 1000, "Gid": 1000}
        assert call_kwargs["RootDirectory"]["Path"] == "/users/user_test_123"
        assert call_kwargs["RootDirectory"]["CreationInfo"]["OwnerUid"] == 1000
        assert call_kwargs["RootDirectory"]["CreationInfo"]["Permissions"] == "0755"

    def test_access_point_failure_raises(self, manager, mock_efs_client):
        """EFS API failure raises EcsManagerError."""
        mock_efs_client.create_access_point.side_effect = ClientError(
            {"Error": {"Code": "FileSystemNotFound", "Message": "not found"}},
            "CreateAccessPoint",
        )

        with pytest.raises(EcsManagerError, match="Failed to create EFS access point"):
            manager._create_access_point("user_test_123")


# ---------------------------------------------------------------------------
# _register_task_definition
# ---------------------------------------------------------------------------


class TestRegisterTaskDefinition:
    """Test per-user task definition registration."""

    def test_clones_task_def_with_access_point(self, manager, mock_ecs_client):
        """_register_task_definition clones base task def with per-user access point."""
        task_def_arn = manager._register_task_definition("fsap-user123")

        assert "task-definition" in task_def_arn

        # Verify describe was called to read base
        mock_ecs_client.describe_task_definition.assert_called_once_with(taskDefinition=manager._task_def)

        # Verify register was called with overridden access point
        mock_ecs_client.register_task_definition.assert_called_once()
        call_kwargs = mock_ecs_client.register_task_definition.call_args.kwargs
        assert call_kwargs["family"] == "isol8-dev-openclaw"
        volumes = call_kwargs["volumes"]
        assert len(volumes) == 1
        efs_config = volumes[0]["efsVolumeConfiguration"]
        assert efs_config["authorizationConfig"]["accessPointId"] == "fsap-user123"

    def test_register_failure_raises(self, manager, mock_ecs_client):
        """ECS API failure during register raises EcsManagerError."""
        mock_ecs_client.register_task_definition.side_effect = ClientError(
            {"Error": {"Code": "ClientException", "Message": "failed"}},
            "RegisterTaskDefinition",
        )

        with pytest.raises(EcsManagerError, match="Failed to register per-user task definition"):
            manager._register_task_definition("fsap-user123")


# ---------------------------------------------------------------------------
# create_user_service
# ---------------------------------------------------------------------------


class TestCreateUserService:
    """Test ECS service creation with per-user EFS isolation."""

    @pytest.mark.asyncio
    async def test_creates_service_and_repo_record(self, manager, mock_ecs_client, mock_efs_client):
        """create_user_service upserts repo record early, then creates access point, task def, service."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.upsert = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock(return_value=_make_container_dict())

            service_name = await manager.create_user_service("user_test_123", "token-abc")

            assert service_name == "openclaw-user_test_123-f4ae64abb2db"

            # Verify repo upsert called early
            mock_repo.upsert.assert_called_once_with(
                "user_test_123",
                {
                    "service_name": "openclaw-user_test_123-f4ae64abb2db",
                    "gateway_token": "token-abc",
                    "status": "provisioning",
                    "substatus": None,
                    "owner_type": "personal",
                },
            )

            # Verify EFS access point was created
            mock_efs_client.create_access_point.assert_called_once()

            # Verify task definition was cloned
            mock_ecs_client.describe_task_definition.assert_called_once()
            mock_ecs_client.register_task_definition.assert_called_once()

            # Verify ECS create_service called
            mock_ecs_client.create_service.assert_called_once()
            call_kwargs = mock_ecs_client.create_service.call_args.kwargs
            assert call_kwargs["cluster"] == manager._cluster
            assert call_kwargs["serviceName"] == "openclaw-user_test_123-f4ae64abb2db"
            assert call_kwargs["desiredCount"] == 0
            assert call_kwargs["launchType"] == "FARGATE"
            assert call_kwargs["enableExecuteCommand"] is True

            # Verify update_fields called for substatus progression (3 calls)
            assert mock_repo.update_fields.call_count == 3

    @pytest.mark.asyncio
    async def test_create_service_enables_deployment_circuit_breaker(self, manager, mock_ecs_client, mock_efs_client):
        """create_service MUST pass deploymentCircuitBreaker so ECS surfaces a
        rolloutState=FAILED signal when a per-user provision fails (bad image,
        crash loop). Without this, _await_running_transition has no way to
        distinguish a slow start from a permanent failure."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.upsert = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock(return_value=_make_container_dict())

            await manager.create_user_service("user_test_123", "token-abc")

            call_kwargs = mock_ecs_client.create_service.call_args.kwargs
            dc = call_kwargs.get("deploymentConfiguration") or {}
            cb = dc.get("deploymentCircuitBreaker") or {}
            assert cb.get("enable") is True, (
                "Deployment circuit breaker must be enabled so rolloutState=FAILED "
                "can be used as the failure signal by _await_running_transition."
            )
            # rollback=False: no previous deployment to roll back to on first deploy.
            assert cb.get("rollback") is False

    @pytest.mark.asyncio
    async def test_ecs_failure_raises_and_rolls_back(self, manager, mock_ecs_client, mock_efs_client):
        """ECS API failure raises EcsManagerError, sets error status, and rolls back AWS resources."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.upsert = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock(return_value=_make_container_dict())

            mock_ecs_client.create_service.side_effect = ClientError(
                {"Error": {"Code": "ClusterNotFoundException", "Message": "not found"}},
                "CreateService",
            )

            with pytest.raises(EcsManagerError, match="Failed to create ECS service"):
                await manager.create_user_service("user_test_123", "token")

            # Error status set via update_fields
            error_calls = [c for c in mock_repo.update_fields.call_args_list if c[0][1].get("status") == "error"]
            assert len(error_calls) >= 1

            # Rollback: task def deregistered and access point deleted
            mock_ecs_client.deregister_task_definition.assert_called_once()
            mock_efs_client.delete_access_point.assert_called_once_with(AccessPointId="fsap-user123")

    @pytest.mark.asyncio
    async def test_access_point_failure_raises(self, manager, mock_efs_client, mock_ecs_client):
        """EFS access point creation failure raises EcsManagerError and sets error status."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.upsert = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock(return_value=_make_container_dict())

            mock_efs_client.create_access_point.side_effect = ClientError(
                {"Error": {"Code": "FileSystemNotFound", "Message": "not found"}},
                "CreateAccessPoint",
            )

            with pytest.raises(EcsManagerError, match="Failed to create EFS access point"):
                await manager.create_user_service("user_test_123", "token")

            # Error status set
            error_calls = [c for c in mock_repo.update_fields.call_args_list if c[0][1].get("status") == "error"]
            assert len(error_calls) >= 1

            # No AWS rollback needed -- nothing was created yet
            mock_ecs_client.create_service.assert_not_called()
            mock_ecs_client.deregister_task_definition.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_def_failure_rolls_back_access_point(self, manager, mock_ecs_client, mock_efs_client):
        """Task definition failure rolls back the access point and sets error status."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.upsert = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock(return_value=_make_container_dict())

            mock_ecs_client.register_task_definition.side_effect = ClientError(
                {"Error": {"Code": "ClientException", "Message": "failed"}},
                "RegisterTaskDefinition",
            )

            with pytest.raises(EcsManagerError, match="Failed to register per-user task definition"):
                await manager.create_user_service("user_test_123", "token")

            # Error status set
            error_calls = [c for c in mock_repo.update_fields.call_args_list if c[0][1].get("status") == "error"]
            assert len(error_calls) >= 1

            # Access point should be cleaned up
            mock_efs_client.delete_access_point.assert_called_once_with(AccessPointId="fsap-user123")
            # No ECS service should have been created
            mock_ecs_client.create_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_substatus_progression(self, manager, mock_ecs_client, mock_efs_client):
        """create_user_service updates substatus at each step via container_repo."""
        update_calls = []

        async def track_update(user_id, fields):
            update_calls.append(fields)
            return _make_container_dict()

        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.upsert = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock(side_effect=track_update)

            await manager.create_user_service("user_test_123", "token-abc")

            # _update_container is called for each substatus progression
            assert len(update_calls) == 3
            assert update_calls[0]["substatus"] == "efs_created"
            assert "access_point_id" in update_calls[0]
            assert update_calls[1]["substatus"] == "task_registered"
            assert "task_definition_arn" in update_calls[1]
            assert update_calls[2]["substatus"] == "service_created"


# ---------------------------------------------------------------------------
# stop_user_service
# ---------------------------------------------------------------------------


class TestStopUserService:
    """Test scaling service to 0."""

    @pytest.mark.asyncio
    async def test_stop_scales_to_zero(self, manager, mock_ecs_client):
        """stop_user_service calls update_service with desiredCount=0."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="running"))
            mock_repo.update_status = AsyncMock(return_value=_make_container_dict(status="stopped"))

            await manager.stop_user_service("user_test_123")

            mock_ecs_client.update_service.assert_called_once_with(
                cluster=manager._cluster,
                service="openclaw-user_test_123-f4ae64abb2db",
                desiredCount=0,
            )
            mock_repo.update_status.assert_called_once_with("user_test_123", "stopped")

    @pytest.mark.asyncio
    async def test_stop_no_db_record(self, manager, mock_ecs_client):
        """stop_user_service with no repo record still calls ECS but skips status update."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=None)

            await manager.stop_user_service("user_test_123")

            mock_ecs_client.update_service.assert_called_once()
            mock_repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_ecs_failure_raises(self, manager, mock_ecs_client):
        """ECS API failure raises EcsManagerError."""
        mock_ecs_client.update_service.side_effect = ClientError(
            {"Error": {"Code": "ServiceNotFoundException", "Message": "not found"}},
            "UpdateService",
        )

        with pytest.raises(EcsManagerError, match="Failed to stop ECS service"):
            await manager.stop_user_service("user_test_123")


# ---------------------------------------------------------------------------
# start_user_service
# ---------------------------------------------------------------------------


class TestStartUserService:
    """Test scaling service to 1."""

    @pytest.mark.asyncio
    async def test_start_scales_to_one(self, manager, mock_ecs_client):
        """start_user_service calls update_service with desiredCount=1 and force."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="stopped"))
            mock_repo.update_status = AsyncMock(return_value=_make_container_dict(status="provisioning"))

            await manager.start_user_service("user_test_123")

            mock_ecs_client.update_service.assert_called_once_with(
                cluster=manager._cluster,
                service="openclaw-user_test_123-f4ae64abb2db",
                desiredCount=1,
                forceNewDeployment=True,
                deploymentConfiguration={
                    "deploymentCircuitBreaker": {
                        "enable": True,
                        "rollback": False,
                    }
                },
            )
            mock_repo.update_status.assert_called_once_with("user_test_123", "provisioning")

    @pytest.mark.asyncio
    async def test_start_fires_running_transition_poller(self, manager, mock_ecs_client):
        """Cold-start restart MUST fire _await_running_transition, or the cold-
        started container will get stuck at status=provisioning forever when
        its ECS task takes >10s to become healthy and the user leaves before
        making another request."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock) as mock_await,
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="stopped"))
            mock_repo.update_status = AsyncMock(return_value=_make_container_dict(status="provisioning"))

            await manager.start_user_service("user_test_123")

            # Give the fire-and-forget task a chance to be scheduled.
            # asyncio.create_task schedules it immediately; a yield is enough.
            import asyncio as _asyncio

            await _asyncio.sleep(0)

            mock_await.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    async def test_start_no_db_record(self, manager, mock_ecs_client):
        """start_user_service with no repo record still calls ECS."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=None)

            await manager.start_user_service("user_test_123")

            mock_ecs_client.update_service.assert_called_once()
            mock_repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_ecs_failure_raises(self, manager, mock_ecs_client):
        """ECS API failure raises EcsManagerError."""
        mock_ecs_client.update_service.side_effect = ClientError(
            {"Error": {"Code": "ServiceNotFoundException", "Message": "not found"}},
            "UpdateService",
        )

        with patch.object(manager, "_await_running_transition", new_callable=AsyncMock):
            with pytest.raises(EcsManagerError, match="Failed to start ECS service"):
                await manager.start_user_service("user_test_123")

    @pytest.mark.asyncio
    async def test_start_service_enables_circuit_breaker_on_existing_services(self, manager, mock_ecs_client):
        """start_user_service's update_service call must include the circuit
        breaker so pre-existing services (created before Task 1) get upgraded
        the first time we touch them. Otherwise _await_running_transition
        can never receive rolloutState=FAILED and polls forever on a broken
        pre-existing service."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="stopped"))
            mock_repo.update_status = AsyncMock(return_value=_make_container_dict(status="provisioning"))

            await manager.start_user_service("user_test_123")

            call_kwargs = mock_ecs_client.update_service.call_args.kwargs
            dc = call_kwargs.get("deploymentConfiguration") or {}
            cb = dc.get("deploymentCircuitBreaker") or {}
            assert cb.get("enable") is True
            assert cb.get("rollback") is False


# ---------------------------------------------------------------------------
# delete_user_service
# ---------------------------------------------------------------------------


class TestDeleteUserService:
    """Test service deletion with per-user resource cleanup."""

    @pytest.mark.asyncio
    async def test_delete_scales_then_deletes_with_cleanup(self, manager, mock_ecs_client, mock_efs_client):
        """delete_user_service scales to 0, deletes service, and cleans up per-user resources."""
        container_dict = _make_container_dict(
            status="running",
            access_point_id="fsap-user123",
            task_definition_arn="arn:aws:ecs:us-east-1:123456789:task-definition/openclaw:42",
        )
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=container_dict)
            mock_repo.delete = AsyncMock()

            await manager.delete_user_service("user_test_123")

            # Verify update_service (scale to 0) called first
            mock_ecs_client.update_service.assert_called_once_with(
                cluster=manager._cluster,
                service="openclaw-user_test_123-f4ae64abb2db",
                desiredCount=0,
            )
            # Verify delete_service called
            mock_ecs_client.delete_service.assert_called_once_with(
                cluster=manager._cluster,
                service="openclaw-user_test_123-f4ae64abb2db",
                force=True,
            )
            # Verify per-user task definition deregistered
            mock_ecs_client.deregister_task_definition.assert_called_once_with(
                taskDefinition="arn:aws:ecs:us-east-1:123456789:task-definition/openclaw:42"
            )
            # Verify per-user access point deleted
            mock_efs_client.delete_access_point.assert_called_once_with(AccessPointId="fsap-user123")
            # Verify repo record deleted
            mock_repo.delete.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    async def test_delete_no_db_record(self, manager, mock_ecs_client, mock_efs_client):
        """delete_user_service with no repo record still deletes ECS service."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=None)
            mock_repo.delete = AsyncMock()

            await manager.delete_user_service("user_test_123")

            mock_ecs_client.update_service.assert_called_once()
            mock_ecs_client.delete_service.assert_called_once()
            # No per-user resources to clean up
            mock_ecs_client.deregister_task_definition.assert_not_called()
            mock_efs_client.delete_access_point.assert_not_called()
            mock_repo.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_without_per_user_resources(self, manager, mock_ecs_client, mock_efs_client):
        """delete_user_service skips cleanup when container has no per-user resources."""
        container_dict = _make_container_dict(status="running")
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=container_dict)
            mock_repo.delete = AsyncMock()

            await manager.delete_user_service("user_test_123")

            # ECS service still deleted
            mock_ecs_client.delete_service.assert_called_once()
            # No per-user cleanup
            mock_ecs_client.deregister_task_definition.assert_not_called()
            mock_efs_client.delete_access_point.assert_not_called()
            # Repo record still deleted
            mock_repo.delete.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    async def test_delete_ecs_failure_raises(self, manager, mock_ecs_client):
        """ECS API failure raises EcsManagerError."""
        mock_ecs_client.update_service.side_effect = ClientError(
            {"Error": {"Code": "ServiceNotFoundException", "Message": "not found"}},
            "UpdateService",
        )

        with pytest.raises(EcsManagerError, match="Failed to delete ECS service"):
            await manager.delete_user_service("user_test_123")


# ---------------------------------------------------------------------------
# discover_ip
# ---------------------------------------------------------------------------


class TestDiscoverIp:
    """Test ECS-based task IP discovery."""

    def test_returns_ip(self, manager, mock_ecs_client):
        """discover_ip returns the private IPv4 from ECS describe_tasks."""
        mock_ecs_client.list_tasks.return_value = {
            "taskArns": ["arn:aws:ecs:us-east-1:123456789:task/test-cluster/abc123"]
        }
        mock_ecs_client.describe_tasks.return_value = {
            "tasks": [
                {
                    "taskArn": "arn:aws:ecs:us-east-1:123456789:task/test-cluster/abc123",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [
                                {"name": "subnetId", "value": "subnet-aaa"},
                                {"name": "privateIPv4Address", "value": "10.0.1.42"},
                            ],
                        }
                    ],
                }
            ]
        }

        ip = manager.discover_ip("openclaw-abc123def4")

        assert ip == "10.0.1.42"
        mock_ecs_client.list_tasks.assert_called_once_with(
            cluster=manager._cluster,
            serviceName="openclaw-abc123def4",
            desiredStatus="RUNNING",
        )

    def test_returns_none_when_no_tasks(self, manager, mock_ecs_client):
        """discover_ip returns None when no running tasks found."""
        mock_ecs_client.list_tasks.return_value = {"taskArns": []}

        ip = manager.discover_ip("openclaw-abc123def4")
        assert ip is None

    def test_returns_none_on_error(self, manager, mock_ecs_client):
        """discover_ip returns None on SDK error."""
        mock_ecs_client.list_tasks.side_effect = ClientError(
            {"Error": {"Code": "ServiceNotFound", "Message": "not found"}},
            "ListTasks",
        )

        ip = manager.discover_ip("openclaw-abc123def4")
        assert ip is None

    def test_returns_none_when_no_eni(self, manager, mock_ecs_client):
        """discover_ip returns None when task has no ENI attachment."""
        mock_ecs_client.list_tasks.return_value = {
            "taskArns": ["arn:aws:ecs:us-east-1:123456789:task/test-cluster/abc123"]
        }
        mock_ecs_client.describe_tasks.return_value = {"tasks": [{"taskArn": "...", "attachments": []}]}

        ip = manager.discover_ip("openclaw-abc123def4")
        assert ip is None

    def test_returns_none_when_no_ip_in_eni(self, manager, mock_ecs_client):
        """discover_ip returns None when ENI lacks privateIPv4Address."""
        mock_ecs_client.list_tasks.return_value = {
            "taskArns": ["arn:aws:ecs:us-east-1:123456789:task/test-cluster/abc123"]
        }
        mock_ecs_client.describe_tasks.return_value = {
            "tasks": [
                {
                    "taskArn": "...",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [
                                {"name": "subnetId", "value": "subnet-aaa"},
                            ],
                        }
                    ],
                }
            ]
        }

        ip = manager.discover_ip("openclaw-abc123def4")
        assert ip is None


# ---------------------------------------------------------------------------
# is_healthy
# ---------------------------------------------------------------------------


class TestIsHealthy:
    """Test gateway health checks via TCP socket."""

    def test_healthy_connection_succeeds(self, manager):
        """Successful TCP connection means healthy."""
        with patch("core.containers.ecs_manager.socket.create_connection") as mock_conn:
            mock_socket = MagicMock()
            mock_conn.return_value.__enter__ = MagicMock(return_value=mock_socket)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            assert manager.is_healthy("10.0.1.42") is True
            mock_conn.assert_called_once_with(("10.0.1.42", GATEWAY_PORT), timeout=5)

    def test_unhealthy_connection_refused(self, manager):
        """Connection refused means unhealthy."""
        with patch("core.containers.ecs_manager.socket.create_connection") as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError("refused")

            assert manager.is_healthy("10.0.1.42") is False

    def test_unhealthy_timeout(self, manager):
        """Timeout means unhealthy."""
        import socket

        with patch("core.containers.ecs_manager.socket.create_connection") as mock_conn:
            mock_conn.side_effect = socket.timeout("timed out")

            assert manager.is_healthy("10.0.1.42") is False


# ---------------------------------------------------------------------------
# resolve_running_container
# ---------------------------------------------------------------------------


class TestResolveRunningContainer:
    """Test container resolution with auto-transition."""

    @pytest.mark.asyncio
    async def test_returns_container_and_ip(self, manager):
        """Returns container dict and IP for a running container."""
        container_dict = _make_container_dict(status="running", service_name="openclaw-user_test_123-f4ae64abb2db")
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=container_dict)
            manager.discover_ip = MagicMock(return_value="10.0.1.42")

            container, ip = await manager.resolve_running_container("user_test_123")

            assert container == container_dict
            assert ip == "10.0.1.42"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_container(self, manager):
        """Returns (None, None) when no container exists."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=None)

            container, ip = await manager.resolve_running_container("user_test_123")

            assert container is None
            assert ip is None

    @pytest.mark.asyncio
    async def test_returns_none_for_stopped_container(self, manager):
        """Returns (None, None) when container status is not provisioning/running."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="stopped"))

            container, ip = await manager.resolve_running_container("user_test_123")

            assert container is None
            assert ip is None

    @pytest.mark.asyncio
    async def test_auto_transitions_provisioning_to_running(self, manager):
        """Provisioning container transitions to running when healthy."""
        container_dict = _make_container_dict(status="provisioning", service_name="openclaw-user_test_123-f4ae64abb2db")
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=container_dict)
            mock_repo.update_fields = AsyncMock(return_value=container_dict)
            manager.discover_ip = MagicMock(return_value="10.0.1.42")
            manager.is_healthy = MagicMock(return_value=True)

            container, ip = await manager.resolve_running_container("user_test_123")

            assert container["status"] == "running"
            assert ip == "10.0.1.42"
            mock_repo.update_fields.assert_called_once()


# ---------------------------------------------------------------------------
# get_service_status
# ---------------------------------------------------------------------------


class TestGetServiceStatus:
    """Test repo status lookup."""

    @pytest.mark.asyncio
    async def test_returns_container(self, manager):
        """get_service_status returns the container dict."""
        container_dict = _make_container_dict(status="running")
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=container_dict)

            result = await manager.get_service_status("user_test_123")
            assert result == container_dict
            assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, manager):
        """get_service_status returns None when no record exists."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(return_value=None)

            result = await manager.get_service_status("user_nonexistent")
            assert result is None


# ---------------------------------------------------------------------------
# EcsManagerError
# ---------------------------------------------------------------------------


class TestEcsManagerError:
    """Test custom exception."""

    def test_error_with_user_id(self):
        """EcsManagerError stores user_id."""
        err = EcsManagerError("something failed", user_id="user_123")
        assert str(err) == "something failed"
        assert err.user_id == "user_123"

    def test_error_without_user_id(self):
        """EcsManagerError defaults user_id to empty string."""
        err = EcsManagerError("generic failure")
        assert err.user_id == ""


# ---------------------------------------------------------------------------
# _await_running_transition (durable provisioning -> running poller)
# ---------------------------------------------------------------------------


class TestAwaitRunningTransition:
    """The poller that drives provisioning -> running in the background.

    Must be durable (no fixed timeout) and have proper exit conditions so a
    container can never be left stuck at status=provisioning forever while
    actually running in ECS.
    """

    @pytest.mark.asyncio
    async def test_transitions_to_running_when_task_healthy(self, manager, mock_ecs_client):
        """Container becomes reachable -> write status=running and exit."""
        mock_ecs_client.list_tasks.return_value = {"taskArns": ["arn:aws:ecs:us-east-1:123:task/cluster/abc"]}
        mock_ecs_client.describe_tasks.return_value = {
            "tasks": [
                {
                    "lastStatus": "RUNNING",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [{"name": "privateIPv4Address", "value": "10.0.1.42"}],
                        }
                    ],
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "is_healthy", return_value=True),
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_called_once()
            fields = mock_repo.update_fields.call_args.args[1]
            assert fields["status"] == "running"
            assert fields["substatus"] == "gateway_healthy"
            assert fields["task_arn"] == "arn:aws:ecs:us-east-1:123:task/cluster/abc"

    @pytest.mark.asyncio
    async def test_transitions_to_error_when_circuit_breaker_trips(self, manager, mock_ecs_client):
        """ECS deployment rolloutState=FAILED -> write status=error and exit.

        This is the definitive failure signal: the circuit breaker only trips
        after N failed task placements, so we know the provision will never
        succeed on its own (bad image, crash loop, etc.)."""
        mock_ecs_client.list_tasks.return_value = {"taskArns": []}
        mock_ecs_client.describe_services.return_value = {
            "services": [{"deployments": [{"id": "ecs-svc/primary", "status": "PRIMARY", "rolloutState": "FAILED"}]}]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_called_once()
            fields = mock_repo.update_fields.call_args.args[1]
            assert fields["status"] == "error"

    @pytest.mark.asyncio
    async def test_exits_silently_when_ddb_status_changed_externally(self, manager, mock_ecs_client):
        """If another actor (admin, reaper, re-provision) changed the DDB status
        under us, exit without writing anything -- our job is done or obsolete."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="stopped"))
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_not_called()

    @pytest.mark.asyncio
    async def test_exits_silently_when_row_missing(self, manager, mock_ecs_client):
        """Container row deleted -> exit. No row to transition."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=None)
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_not_called()

    @pytest.mark.asyncio
    async def test_keeps_polling_when_task_not_yet_healthy(self, manager, mock_ecs_client):
        """On iteration N no running task, on iteration N+1 it's healthy -> transition.

        Regression for the 120s timeout bug: a container that takes >2 minutes
        to become reachable MUST still get transitioned when it eventually is."""
        # First poll: no tasks. Second poll: a healthy task.
        mock_ecs_client.list_tasks.side_effect = [
            {"taskArns": []},
            {"taskArns": ["arn:aws:ecs:us-east-1:123:task/cluster/abc"]},
        ]
        mock_ecs_client.describe_tasks.return_value = {
            "tasks": [
                {
                    "lastStatus": "RUNNING",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [{"name": "privateIPv4Address", "value": "10.0.1.42"}],
                        }
                    ],
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "is_healthy", return_value=True),
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_called_once()
            fields = mock_repo.update_fields.call_args.args[1]
            assert fields["status"] == "running"

    @pytest.mark.asyncio
    async def test_one_describe_services_per_iteration_on_happy_path(self, manager, mock_ecs_client):
        """describe_services consolidates two concerns (primary-deployment
        filter + rolloutState failure detection) so a happy-path transition
        costs one describe_services + one list_tasks + one describe_tasks."""
        mock_ecs_client.list_tasks.return_value = {"taskArns": ["arn:aws:ecs:us-east-1:123:task/cluster/abc"]}
        mock_ecs_client.describe_tasks.return_value = {
            "tasks": [
                {
                    "lastStatus": "RUNNING",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [{"name": "privateIPv4Address", "value": "10.0.1.42"}],
                        }
                    ],
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "is_healthy", return_value=True),
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            assert mock_ecs_client.describe_services.call_count == 1

    @pytest.mark.asyncio
    async def test_filters_running_tasks_by_primary_deployment(self, manager, mock_ecs_client):
        """During a forced redeploy, the OLD task is still RUNNING while the
        NEW deployment rolls out. _poll_running_task MUST only consider tasks
        from the current PRIMARY deployment -- picking the old task would
        flip status=running using the pre-deploy task_arn and mask a failing
        rollout.

        Filter mechanism: pass startedBy=<primary-deployment-id> to list_tasks.
        ECS tags service-launched tasks with startedBy=ecs-svc/<deployment-id>.
        """
        # describe_services returns one PRIMARY and one ACTIVE (draining) deployment.
        mock_ecs_client.describe_services.return_value = {
            "services": [
                {
                    "deployments": [
                        {
                            "id": "ecs-svc/new",
                            "status": "PRIMARY",
                            "rolloutState": "IN_PROGRESS",
                        },
                        {
                            "id": "ecs-svc/old",
                            "status": "ACTIVE",
                            "rolloutState": "COMPLETED",
                        },
                    ]
                }
            ]
        }

        # list_tasks should be called with startedBy pointing at the PRIMARY.
        mock_ecs_client.list_tasks.return_value = {"taskArns": ["arn:aws:ecs:us-east-1:123:task/cluster/new-task"]}
        mock_ecs_client.describe_tasks.return_value = {
            "tasks": [
                {
                    "lastStatus": "RUNNING",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [{"name": "privateIPv4Address", "value": "10.0.1.99"}],
                        }
                    ],
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "is_healthy", return_value=True),
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            # list_tasks must have been called with startedBy=<primary-id>.
            list_kwargs = mock_ecs_client.list_tasks.call_args.kwargs
            assert list_kwargs.get("startedBy") == "ecs-svc/new", (
                f"Expected startedBy='ecs-svc/new', got {list_kwargs.get('startedBy')!r}. "
                "Must filter to the PRIMARY deployment's tasks so an old "
                "drain-phase task doesn't trigger a premature status=running."
            )

            # With the filter correctly applied, the new task's ARN is recorded.
            fields = mock_repo.update_fields.call_args.args[1]
            assert fields["task_arn"] == "arn:aws:ecs:us-east-1:123:task/cluster/new-task"

    @pytest.mark.asyncio
    async def test_no_primary_deployment_keeps_polling(self, manager, mock_ecs_client):
        """If describe_services returns no PRIMARY deployment (transient ECS
        state during deployment churn), the poller should just sleep and
        retry next iteration -- not write status=running or status=error."""
        mock_ecs_client.describe_services.return_value = {"services": [{"deployments": []}]}
        mock_ecs_client.list_tasks.return_value = {"taskArns": []}

        # Cancel after one sleep so the loop exits.
        import asyncio as _asyncio

        sleep_calls = [0]

        async def count_and_cancel(*args, **kwargs):
            sleep_calls[0] += 1
            if sleep_calls[0] >= 1:
                raise _asyncio.CancelledError()

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", side_effect=count_and_cancel),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock()

            with pytest.raises(_asyncio.CancelledError):
                await manager._await_running_transition("user_test_123")

            # No status transition written either direction.
            mock_repo.update_fields.assert_not_called()

    @pytest.mark.asyncio
    async def test_detects_circuit_breaker_via_primary_deployment_rollout_state(self, manager, mock_ecs_client):
        """rolloutState='FAILED' must be read from the PRIMARY deployment
        specifically, not from deployments[0] blindly. During a rollout,
        the ACTIVE (old) deployment can coexist with the new PRIMARY and
        the list order is not guaranteed."""
        import asyncio as _asyncio

        mock_ecs_client.describe_services.return_value = {
            "services": [
                {
                    "deployments": [
                        # Draining old deployment listed first.
                        {
                            "id": "ecs-svc/old",
                            "status": "ACTIVE",
                            "rolloutState": "COMPLETED",
                        },
                        # New PRIMARY failed.
                        {
                            "id": "ecs-svc/new",
                            "status": "PRIMARY",
                            "rolloutState": "FAILED",
                        },
                    ]
                }
            ]
        }
        mock_ecs_client.list_tasks.return_value = {"taskArns": []}

        # If the implementation incorrectly reads deployments[0] and misses
        # the FAILED PRIMARY, the loop would spin forever -- cancel after a
        # few sleeps so the test fails loudly instead of hanging.
        sleep_count = [0]

        async def cancel_after_a_few(*args, **kwargs):
            sleep_count[0] += 1
            if sleep_count[0] > 3:
                raise _asyncio.CancelledError()

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", side_effect=cancel_after_a_few),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock()

            # Expected: implementation finds FAILED PRIMARY -> writes error -> returns
            # without ever reaching the cancellation guard.
            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_called_once()
            fields = mock_repo.update_fields.call_args.args[1]
            assert fields["status"] == "error"

    @pytest.mark.asyncio
    async def test_respects_cancellation(self, manager, mock_ecs_client):
        """Clean shutdown: if the event loop cancels the task (backend restart),
        the poller exits without raising into the caller and without writing
        a status transition."""
        import asyncio as _asyncio

        mock_ecs_client.list_tasks.return_value = {"taskArns": []}
        mock_ecs_client.describe_services.return_value = {
            "services": [
                {"deployments": [{"id": "ecs-svc/primary", "status": "PRIMARY", "rolloutState": "IN_PROGRESS"}]}
            ]
        }

        # asyncio.sleep raises CancelledError inside the poller loop.
        async def cancel_on_sleep(*args, **kwargs):
            raise _asyncio.CancelledError()

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", side_effect=cancel_on_sleep),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock()

            # Must not swallow CancelledError -- asyncio task cancellation
            # semantics require it to propagate out.
            with pytest.raises(_asyncio.CancelledError):
                await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_not_called()


# ---------------------------------------------------------------------------
# resize_user_container (per-user CPU/memory/image update path)
# ---------------------------------------------------------------------------


class TestResizeUserContainer:
    """Tests resize path fires the transition poller.

    resize writes status=provisioning via update_fields + ECS forceNewDeployment.
    Without firing the poller, the row stays stuck at provisioning until the
    next backend restart catches it via the startup reconciler."""

    @pytest.mark.asyncio
    async def test_resize_fires_running_transition_poller(self, manager, mock_ecs_client):
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock) as mock_await,
        ):
            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(
                    status="running",
                    task_definition_arn="arn:aws:ecs:us-east-1:123:task-definition/base:1",
                )
            )
            mock_repo.update_fields = AsyncMock(return_value=_make_container_dict(status="provisioning"))

            await manager.resize_user_container("user_test_123", new_cpu="1024", new_memory="2048")

            import asyncio as _asyncio

            await _asyncio.sleep(0)

            mock_await.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    async def test_resize_enables_circuit_breaker_on_update_service(self, manager, mock_ecs_client):
        """resize path's update_service must also carry the circuit breaker
        so pre-existing services get upgraded on resize."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock),
            patch("core.containers.ecs_manager.asyncio.to_thread") as mock_to_thread,
        ):
            # asyncio.to_thread runs the sync boto3 call in a thread;
            # intercept it so we can inspect kwargs.
            async def passthrough(fn, *args, **kwargs):
                return fn(*args, **kwargs)

            mock_to_thread.side_effect = passthrough

            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(
                    status="running",
                    task_definition_arn="arn:aws:ecs:us-east-1:123:task-definition/base:1",
                )
            )
            mock_repo.update_fields = AsyncMock(return_value=_make_container_dict(status="provisioning"))

            await manager.resize_user_container("user_test_123", new_cpu="1024", new_memory="2048")

            # resize issues two to_thread calls -- register_task_definition
            # and update_service. Find the update_service call.
            update_calls = [
                call
                for call in mock_to_thread.call_args_list
                if getattr(call.args[0], "__name__", "") == "update_service"
                or (call.args and call.args[0] == mock_ecs_client.update_service)
            ]
            assert update_calls, "Expected update_service to be called via asyncio.to_thread"
            call_kwargs = update_calls[0].kwargs
            dc = call_kwargs.get("deploymentConfiguration") or {}
            cb = dc.get("deploymentCircuitBreaker") or {}
            assert cb.get("enable") is True
            assert cb.get("rollback") is False


# ---------------------------------------------------------------------------
# provision_user_container (full provisioning flow + recovery branches)
# ---------------------------------------------------------------------------


class TestProvisionUserContainer:
    """Tests for the recovery branches of provision_user_container that set
    status=provisioning on an existing service row. Both branches must fire
    the transition poller so the row drains back to status=running without
    relying on the startup reconciler."""

    @pytest.mark.asyncio
    async def test_provision_redeploying_branch_fires_poller(self, manager, mock_ecs_client):
        """When provision is called and the ECS service is already running,
        the redeploying branch forces a new deployment and writes
        status=provisioning. It MUST fire the poller so the row transitions
        back to status=running once the new task is healthy."""
        # Service exists with desired=1, running=1 -> redeploying branch.
        mock_ecs_client.describe_services.return_value = {
            "services": [
                {
                    "serviceName": "openclaw-user_test_123-f4ae64abb2db",
                    "status": "ACTIVE",
                    "desiredCount": 1,
                    "runningCount": 1,
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock) as mock_await,
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="running"))
            mock_repo.update_fields = AsyncMock()

            await manager.provision_user_container("user_test_123")

            import asyncio as _asyncio

            await _asyncio.sleep(0)

            mock_await.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    async def test_provision_ecs_starting_branch_fires_poller(self, manager, mock_ecs_client):
        """When provision is called and ECS is mid-launch (desired=1, running=0),
        the 'ECS is starting' branch writes status=provisioning and returns
        without taking ECS action. It MUST fire the poller to drive the
        transition once the task becomes healthy."""
        mock_ecs_client.describe_services.return_value = {
            "services": [
                {
                    "serviceName": "openclaw-user_test_123-f4ae64abb2db",
                    "status": "ACTIVE",
                    "desiredCount": 1,
                    "runningCount": 0,
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock) as mock_await,
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="stopped"))
            mock_repo.update_fields = AsyncMock()

            await manager.provision_user_container("user_test_123")

            import asyncio as _asyncio

            await _asyncio.sleep(0)

            mock_await.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    async def test_provision_full_flow_fires_poller_exactly_once(self, manager, mock_ecs_client, mock_efs_client):
        """Full-provision path (no existing service) must fire
        _await_running_transition EXACTLY ONCE, not twice.

        start_user_service fires one poller (Task 3). Historically
        provision_user_container fired another at the very end. That's
        duplicate work -- two identical long-lived tasks doing the same
        list_tasks/describe_services polling and racing to write the DDB
        transition. Keep only one."""

        # Make _service_exists return None so we go through the full-provisioning path.
        mock_ecs_client.describe_services.return_value = {"services": []}

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock) as mock_await,
            patch.object(manager, "write_user_configs", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=None)
            mock_repo.upsert = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_status = AsyncMock(return_value=_make_container_dict(status="provisioning"))

            await manager.provision_user_container("user_test_123")

            # Let any fire-and-forget tasks be scheduled.
            import asyncio as _asyncio

            await _asyncio.sleep(0)

            # Exactly one poller, not two.
            assert mock_await.await_count == 1, (
                f"Expected exactly 1 poller, got {mock_await.await_count}. "
                "start_user_service fires the poller; the outer create_task "
                "at the end of provision_user_container is redundant."
            )
            mock_await.assert_called_with("user_test_123")

    @pytest.mark.asyncio
    async def test_redeploying_branch_enables_circuit_breaker(self, manager, mock_ecs_client):
        """The redeploying branch (desired=1, running>0) issues an
        update_service(forceNewDeployment=True). That call must carry the
        circuit breaker so pre-existing services get upgraded mid-flight."""
        mock_ecs_client.describe_services.return_value = {
            "services": [
                {
                    "serviceName": "openclaw-user_test_123-f4ae64abb2db",
                    "status": "ACTIVE",
                    "desiredCount": 1,
                    "runningCount": 1,
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="running"))
            mock_repo.update_fields = AsyncMock()

            await manager.provision_user_container("user_test_123")

            # update_service is called directly (not via asyncio.to_thread)
            # in the redeploying branch.
            call_kwargs = mock_ecs_client.update_service.call_args.kwargs
            dc = call_kwargs.get("deploymentConfiguration") or {}
            cb = dc.get("deploymentCircuitBreaker") or {}
            assert cb.get("enable") is True
            assert cb.get("rollback") is False

    @pytest.mark.asyncio
    async def test_provision_ecs_starting_no_poller_when_status_already_provisioning(self, manager, mock_ecs_client):
        """If the DDB status is already 'provisioning' when we hit the
        ECS-is-starting branch, we should NOT spawn another poller. An
        earlier one is already running (or the startup reconciler will
        pick up the row on next deploy). Spawning multiple pollers per
        owner wastes ECS API quota under a slow cold start with repeated
        /container/provision calls."""
        mock_ecs_client.describe_services.return_value = {
            "services": [
                {
                    "serviceName": "openclaw-user_test_123-f4ae64abb2db",
                    "status": "ACTIVE",
                    "desiredCount": 1,
                    "runningCount": 0,
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "_await_running_transition", new_callable=AsyncMock) as mock_await,
        ):
            # Row already at status=provisioning.
            mock_repo.get_by_owner_id = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock()

            await manager.provision_user_container("user_test_123")

            import asyncio as _asyncio

            await _asyncio.sleep(0)

            # No poller fired -- one's already running (or reconciler will catch it).
            mock_await.assert_not_called()
            # Also no DDB update (status already correct).
            mock_repo.update_fields.assert_not_called()
