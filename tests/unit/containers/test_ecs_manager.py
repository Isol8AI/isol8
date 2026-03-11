"""Tests for EcsManager (ECS Fargate service lifecycle with per-user EFS isolation).

Uses mocked boto3 clients and async DB sessions -- no real AWS or
database required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from core.containers.ecs_manager import EcsManager, EcsManagerError, GATEWAY_PORT
from models.container import Container


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
            "containerDefinitions": [{"name": "openclaw", "image": "ghcr.io/openclaw:latest"}],
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


@pytest.fixture
def mock_db():
    """Create a mock async database session.

    db.add() is synchronous in SQLAlchemy (not awaited), so we use a
    plain MagicMock for it to avoid RuntimeWarning about un-awaited
    coroutines.
    """
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _make_container(
    user_id="user_test_123",
    service_name="openclaw-user_test_123-f4ae64abb2db",
    gateway_token="tok-abc",
    status="running",
    access_point_id=None,
    task_definition_arn=None,
):
    """Helper to create a Container model instance for mocking."""
    c = Container(
        user_id=user_id,
        service_name=service_name,
        gateway_token=gateway_token,
        status=status,
        access_point_id=access_point_id,
        task_definition_arn=task_definition_arn,
    )
    return c


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

    async def test_creates_service_and_db_record(self, manager, mock_ecs_client, mock_efs_client, mock_db):
        """create_user_service creates DB record early, then access point, task def, service."""
        # Mock DB: no existing container
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Mock _update_container to track substatus updates
        manager._update_container = AsyncMock()

        service_name = await manager.create_user_service("user_test_123", "token-abc", mock_db)

        assert service_name == "openclaw-user_test_123-f4ae64abb2db"

        # Verify EFS access point was created
        mock_efs_client.create_access_point.assert_called_once()

        # Verify task definition was cloned
        mock_ecs_client.describe_task_definition.assert_called_once()
        mock_ecs_client.register_task_definition.assert_called_once()

        # Verify ECS create_service called with per-user task definition
        mock_ecs_client.create_service.assert_called_once()
        call_kwargs = mock_ecs_client.create_service.call_args.kwargs
        assert call_kwargs["cluster"] == manager._cluster
        assert call_kwargs["serviceName"] == "openclaw-user_test_123-f4ae64abb2db"
        assert "task-definition" in call_kwargs["taskDefinition"]
        assert call_kwargs["desiredCount"] == 1
        assert call_kwargs["launchType"] == "FARGATE"
        assert call_kwargs["networkConfiguration"]["awsvpcConfiguration"]["subnets"] == ["subnet-aaa", "subnet-bbb"]
        assert call_kwargs["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "DISABLED"
        assert call_kwargs["enableExecuteCommand"] is True

        # Verify DB record was added early (before AWS steps)
        mock_db.add.assert_called_once()
        added_container = mock_db.add.call_args[0][0]
        assert added_container.user_id == "user_test_123"
        assert added_container.service_name == "openclaw-user_test_123-f4ae64abb2db"
        assert added_container.gateway_token == "token-abc"
        assert added_container.status == "provisioning"
        # Initial upsert commits via mock_db
        mock_db.commit.assert_awaited_once()
        # Substatus updates go through _update_container (3 calls: efs, task_def, service)
        assert manager._update_container.await_count == 3

    async def test_upserts_existing_db_record(self, manager, mock_ecs_client, mock_efs_client, mock_db):
        """create_user_service updates existing DB record instead of inserting."""
        existing = _make_container(status="stopped")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        manager._update_container = AsyncMock()

        service_name = await manager.create_user_service("user_test_123", "new-token", mock_db)

        assert service_name == "openclaw-user_test_123-f4ae64abb2db"
        # Should NOT call db.add — updates in place
        mock_db.add.assert_not_called()
        assert existing.gateway_token == "new-token"
        assert existing.status == "provisioning"
        # Initial upsert commits via mock_db
        mock_db.commit.assert_awaited_once()
        # Substatus updates go through _update_container (3 calls)
        assert manager._update_container.await_count == 3

    async def test_ecs_failure_raises_and_rolls_back(self, manager, mock_ecs_client, mock_efs_client, mock_db):
        """ECS API failure raises EcsManagerError, sets error status, and rolls back AWS resources."""
        existing = _make_container(status="stopped")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        manager._update_container = AsyncMock()

        mock_ecs_client.create_service.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "not found"}},
            "CreateService",
        )

        with pytest.raises(EcsManagerError, match="Failed to create ECS service"):
            await manager.create_user_service("user_test_123", "token", mock_db)

        # Error status set via _update_container
        manager._update_container.assert_any_await("user_test_123", status="error", substatus=None)

        # Rollback: task def deregistered and access point deleted
        mock_ecs_client.deregister_task_definition.assert_called_once()
        mock_efs_client.delete_access_point.assert_called_once_with(AccessPointId="fsap-user123")

    async def test_access_point_failure_raises(self, manager, mock_efs_client, mock_ecs_client, mock_db):
        """EFS access point creation failure raises EcsManagerError and sets error status."""
        existing = _make_container(status="stopped")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        manager._update_container = AsyncMock()

        mock_efs_client.create_access_point.side_effect = ClientError(
            {"Error": {"Code": "FileSystemNotFound", "Message": "not found"}},
            "CreateAccessPoint",
        )

        with pytest.raises(EcsManagerError, match="Failed to create EFS access point"):
            await manager.create_user_service("user_test_123", "token", mock_db)

        # Error status set via _update_container
        manager._update_container.assert_any_await("user_test_123", status="error", substatus=None)

        # No AWS rollback needed — nothing was created yet
        mock_ecs_client.create_service.assert_not_called()
        mock_ecs_client.deregister_task_definition.assert_not_called()

    async def test_task_def_failure_rolls_back_access_point(self, manager, mock_ecs_client, mock_efs_client, mock_db):
        """Task definition failure rolls back the access point and sets error status."""
        existing = _make_container(status="stopped")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        manager._update_container = AsyncMock()

        mock_ecs_client.register_task_definition.side_effect = ClientError(
            {"Error": {"Code": "ClientException", "Message": "failed"}},
            "RegisterTaskDefinition",
        )

        with pytest.raises(EcsManagerError, match="Failed to register per-user task definition"):
            await manager.create_user_service("user_test_123", "token", mock_db)

        # Error status set via _update_container
        manager._update_container.assert_any_await("user_test_123", status="error", substatus=None)

        # Access point should be cleaned up
        mock_efs_client.delete_access_point.assert_called_once_with(AccessPointId="fsap-user123")
        # No ECS service should have been created
        mock_ecs_client.create_service.assert_not_called()

    async def test_substatus_progression(self, manager, mock_ecs_client, mock_efs_client, mock_db):
        """create_user_service updates substatus at each step via _update_container."""
        existing = _make_container(status="stopped")
        update_calls = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        # Capture _update_container calls
        async def track_update(user_id, **fields):
            update_calls.append(fields)

        manager._update_container = AsyncMock(side_effect=track_update)

        await manager.create_user_service("user_test_123", "token-abc", mock_db)

        # Initial upsert sets substatus=None via mock_db.commit
        # Then _update_container is called for each substatus progression
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

    async def test_stop_scales_to_zero(self, manager, mock_ecs_client, mock_db):
        """stop_user_service calls update_service with desiredCount=0."""
        existing = _make_container(status="running")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        await manager.stop_user_service("user_test_123", mock_db)

        mock_ecs_client.update_service.assert_called_once_with(
            cluster=manager._cluster,
            service="openclaw-user_test_123-f4ae64abb2db",
            desiredCount=0,
        )
        assert existing.status == "stopped"
        mock_db.commit.assert_awaited_once()

    async def test_stop_no_db_record(self, manager, mock_ecs_client, mock_db):
        """stop_user_service with no DB record still calls ECS but skips DB update."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        await manager.stop_user_service("user_test_123", mock_db)

        mock_ecs_client.update_service.assert_called_once()
        # commit is NOT called when there's no container to update
        mock_db.commit.assert_not_awaited()

    async def test_stop_ecs_failure_raises(self, manager, mock_ecs_client, mock_db):
        """ECS API failure raises EcsManagerError."""
        mock_ecs_client.update_service.side_effect = ClientError(
            {"Error": {"Code": "ServiceNotFoundException", "Message": "not found"}},
            "UpdateService",
        )

        with pytest.raises(EcsManagerError, match="Failed to stop ECS service"):
            await manager.stop_user_service("user_test_123", mock_db)


# ---------------------------------------------------------------------------
# start_user_service
# ---------------------------------------------------------------------------


class TestStartUserService:
    """Test scaling service to 1."""

    async def test_start_scales_to_one(self, manager, mock_ecs_client, mock_db):
        """start_user_service calls update_service with desiredCount=1 and force."""
        existing = _make_container(status="stopped")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        await manager.start_user_service("user_test_123", mock_db)

        mock_ecs_client.update_service.assert_called_once_with(
            cluster=manager._cluster,
            service="openclaw-user_test_123-f4ae64abb2db",
            desiredCount=1,
            forceNewDeployment=True,
        )
        assert existing.status == "provisioning"
        mock_db.commit.assert_awaited_once()

    async def test_start_no_db_record(self, manager, mock_ecs_client, mock_db):
        """start_user_service with no DB record still calls ECS."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        await manager.start_user_service("user_test_123", mock_db)

        mock_ecs_client.update_service.assert_called_once()
        mock_db.commit.assert_not_awaited()

    async def test_start_ecs_failure_raises(self, manager, mock_ecs_client, mock_db):
        """ECS API failure raises EcsManagerError."""
        mock_ecs_client.update_service.side_effect = ClientError(
            {"Error": {"Code": "ServiceNotFoundException", "Message": "not found"}},
            "UpdateService",
        )

        with pytest.raises(EcsManagerError, match="Failed to start ECS service"):
            await manager.start_user_service("user_test_123", mock_db)


# ---------------------------------------------------------------------------
# delete_user_service
# ---------------------------------------------------------------------------


class TestDeleteUserService:
    """Test service deletion with per-user resource cleanup."""

    async def test_delete_scales_then_deletes_with_cleanup(self, manager, mock_ecs_client, mock_efs_client, mock_db):
        """delete_user_service scales to 0, deletes service, and cleans up per-user resources."""
        existing = _make_container(
            status="running",
            access_point_id="fsap-user123",
            task_definition_arn="arn:aws:ecs:us-east-1:123456789:task-definition/openclaw:42",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        await manager.delete_user_service("user_test_123", mock_db)

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
        # Verify DB record deleted
        mock_db.delete.assert_awaited_once_with(existing)
        mock_db.commit.assert_awaited_once()

    async def test_delete_no_db_record(self, manager, mock_ecs_client, mock_efs_client, mock_db):
        """delete_user_service with no DB record still deletes ECS service."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        await manager.delete_user_service("user_test_123", mock_db)

        mock_ecs_client.update_service.assert_called_once()
        mock_ecs_client.delete_service.assert_called_once()
        # No per-user resources to clean up
        mock_ecs_client.deregister_task_definition.assert_not_called()
        mock_efs_client.delete_access_point.assert_not_called()
        mock_db.delete.assert_not_awaited()

    async def test_delete_without_per_user_resources(self, manager, mock_ecs_client, mock_efs_client, mock_db):
        """delete_user_service skips cleanup when container has no per-user resources."""
        existing = _make_container(
            status="running",
            access_point_id=None,
            task_definition_arn=None,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        await manager.delete_user_service("user_test_123", mock_db)

        # ECS service still deleted
        mock_ecs_client.delete_service.assert_called_once()
        # No per-user cleanup
        mock_ecs_client.deregister_task_definition.assert_not_called()
        mock_efs_client.delete_access_point.assert_not_called()
        # DB record still deleted
        mock_db.delete.assert_awaited_once_with(existing)

    async def test_delete_ecs_failure_raises(self, manager, mock_ecs_client, mock_db):
        """ECS API failure raises EcsManagerError."""
        mock_ecs_client.update_service.side_effect = ClientError(
            {"Error": {"Code": "ServiceNotFoundException", "Message": "not found"}},
            "UpdateService",
        )

        with pytest.raises(EcsManagerError, match="Failed to delete ECS service"):
            await manager.delete_user_service("user_test_123", mock_db)


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
    """Test gateway health checks."""

    def test_healthy_200(self, manager):
        """Healthy gateway returning 200 yields True."""
        with patch("core.containers.ecs_manager.urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            assert manager.is_healthy("10.0.1.42") is True

            # Verify correct URL and method
            call_args = mock_urlopen.call_args
            request_obj = call_args[0][0]
            assert request_obj.full_url == f"http://10.0.1.42:{GATEWAY_PORT}/v1/chat/completions"
            assert request_obj.method == "OPTIONS"

    def test_healthy_404(self, manager):
        """Gateway returning 404 is still healthy (gateway is running)."""
        with patch("core.containers.ecs_manager.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib_http_error(404)

            assert manager.is_healthy("10.0.1.42") is True

    def test_unhealthy_500(self, manager):
        """Gateway returning 500 is unhealthy."""
        with patch("core.containers.ecs_manager.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib_http_error(500)

            assert manager.is_healthy("10.0.1.42") is False

    def test_unhealthy_connection_refused(self, manager):
        """Connection refused means unhealthy."""
        with patch("core.containers.ecs_manager.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = ConnectionRefusedError("refused")

            assert manager.is_healthy("10.0.1.42") is False

    def test_unhealthy_timeout(self, manager):
        """Timeout means unhealthy."""
        import socket

        with patch("core.containers.ecs_manager.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = socket.timeout("timed out")

            assert manager.is_healthy("10.0.1.42") is False

    def test_unhealthy_url_error(self, manager):
        """URLError means unhealthy."""
        import urllib.error

        with patch("core.containers.ecs_manager.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("connection failed")

            assert manager.is_healthy("10.0.1.42") is False


# ---------------------------------------------------------------------------
# get_service_status
# ---------------------------------------------------------------------------


class TestGetServiceStatus:
    """Test DB status lookup."""

    async def test_returns_container(self, manager, mock_db):
        """get_service_status returns the Container record."""
        existing = _make_container(status="running")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        result = await manager.get_service_status("user_test_123", mock_db)
        assert result is existing
        assert result.status == "running"

    async def test_returns_none_when_not_found(self, manager, mock_db):
        """get_service_status returns None when no record exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await manager.get_service_status("user_nonexistent", mock_db)
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
# Helpers
# ---------------------------------------------------------------------------


def urllib_http_error(code: int):
    """Create a urllib.error.HTTPError with the given status code."""
    import urllib.error
    import io

    return urllib.error.HTTPError(
        url="http://test",
        code=code,
        msg=f"HTTP {code}",
        hdrs={},
        fp=io.BytesIO(b""),
    )
