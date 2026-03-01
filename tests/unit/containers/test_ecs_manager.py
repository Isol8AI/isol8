"""Tests for EcsManager (ECS Fargate service lifecycle).

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
    client.create_service.return_value = {"service": {"serviceName": "openclaw-user_tes"}}
    client.update_service.return_value = {}
    client.delete_service.return_value = {}
    return client


@pytest.fixture
def mock_sd_client():
    """Create a mock ServiceDiscovery boto3 client."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_settings():
    """Mock settings with test ECS configuration."""
    with patch("core.containers.ecs_manager.settings") as s:
        s.AWS_REGION = "us-east-1"
        s.ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-1:123456789:cluster/test-cluster"
        s.ECS_TASK_DEFINITION = "arn:aws:ecs:us-east-1:123456789:task-definition/openclaw:1"
        s.ECS_SUBNETS = "subnet-aaa,subnet-bbb"
        s.ECS_SECURITY_GROUP_ID = "sg-12345"
        s.CLOUD_MAP_SERVICE_ARN = "arn:aws:servicediscovery:us-east-1:123456789:service/srv-test"
        s.CLOUD_MAP_NAMESPACE_ID = "ns-test"
        yield s


@pytest.fixture
def manager(mock_settings, mock_ecs_client, mock_sd_client):
    """Create an EcsManager with mocked boto3 clients."""
    with patch("core.containers.ecs_manager.boto3") as mock_boto3:
        mock_boto3.client.side_effect = lambda service, **kwargs: {
            "ecs": mock_ecs_client,
            "servicediscovery": mock_sd_client,
        }[service]
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
    user_id="user_test_123", service_name="openclaw-user_tes", gateway_token="tok-abc", status="running"
):
    """Helper to create a Container model instance for mocking."""
    c = Container(
        user_id=user_id,
        service_name=service_name,
        gateway_token=gateway_token,
        status=status,
    )
    return c


# ---------------------------------------------------------------------------
# Service naming
# ---------------------------------------------------------------------------


class TestServiceNaming:
    """Test deterministic service name generation."""

    def test_service_name_truncates(self, manager):
        """Service name uses first 8 chars of user_id."""
        name = manager._service_name("user_test_123_long_id")
        assert name == "openclaw-user_tes"

    def test_service_name_short_id(self, manager):
        """Short user_id is used as-is."""
        name = manager._service_name("abc")
        assert name == "openclaw-abc"

    def test_service_name_exact_8(self, manager):
        """Exactly 8-char user_id works."""
        name = manager._service_name("12345678")
        assert name == "openclaw-12345678"


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

    def test_empty_subnets(self, mock_settings):
        """Empty subnet string produces empty list."""
        mock_settings.ECS_SUBNETS = ""
        with patch("core.containers.ecs_manager.boto3") as mock_boto3:
            mock_boto3.client.return_value = MagicMock()
            mgr = EcsManager()
        assert mgr._subnets == []

    def test_subnets_with_whitespace(self, mock_settings):
        """Subnets with extra whitespace are trimmed."""
        mock_settings.ECS_SUBNETS = " subnet-aaa , subnet-bbb , "
        with patch("core.containers.ecs_manager.boto3") as mock_boto3:
            mock_boto3.client.return_value = MagicMock()
            mgr = EcsManager()
        assert mgr._subnets == ["subnet-aaa", "subnet-bbb"]


# ---------------------------------------------------------------------------
# create_user_service
# ---------------------------------------------------------------------------


class TestCreateUserService:
    """Test ECS service creation."""

    async def test_creates_service_and_db_record(self, manager, mock_ecs_client, mock_db):
        """create_user_service calls ECS and inserts a DB record."""
        # Mock DB: no existing container
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        service_name = await manager.create_user_service("user_test_123", "token-abc", mock_db)

        assert service_name == "openclaw-user_tes"

        # Verify ECS create_service called with correct args
        mock_ecs_client.create_service.assert_called_once()
        call_kwargs = mock_ecs_client.create_service.call_args.kwargs
        assert call_kwargs["cluster"] == manager._cluster
        assert call_kwargs["serviceName"] == "openclaw-user_tes"
        assert call_kwargs["taskDefinition"] == manager._task_def
        assert call_kwargs["desiredCount"] == 1
        assert call_kwargs["launchType"] == "FARGATE"
        assert call_kwargs["networkConfiguration"]["awsvpcConfiguration"]["subnets"] == ["subnet-aaa", "subnet-bbb"]
        assert call_kwargs["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "DISABLED"
        assert call_kwargs["enableExecuteCommand"] is True

        # Verify DB record was added
        mock_db.add.assert_called_once()
        added_container = mock_db.add.call_args[0][0]
        assert added_container.user_id == "user_test_123"
        assert added_container.service_name == "openclaw-user_tes"
        assert added_container.gateway_token == "token-abc"
        assert added_container.status == "provisioning"
        mock_db.commit.assert_awaited_once()

    async def test_upserts_existing_db_record(self, manager, mock_ecs_client, mock_db):
        """create_user_service updates existing DB record instead of inserting."""
        existing = _make_container(status="stopped")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        service_name = await manager.create_user_service("user_test_123", "new-token", mock_db)

        assert service_name == "openclaw-user_tes"
        # Should NOT call db.add — updates in place
        mock_db.add.assert_not_called()
        assert existing.gateway_token == "new-token"
        assert existing.status == "provisioning"
        mock_db.commit.assert_awaited_once()

    async def test_ecs_failure_raises(self, manager, mock_ecs_client, mock_db):
        """ECS API failure raises EcsManagerError."""
        mock_ecs_client.create_service.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "not found"}},
            "CreateService",
        )

        with pytest.raises(EcsManagerError, match="Failed to create ECS service"):
            await manager.create_user_service("user_test_123", "token", mock_db)

        # DB should not be touched on ECS failure
        mock_db.commit.assert_not_awaited()


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
            service="openclaw-user_tes",
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
            service="openclaw-user_tes",
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
    """Test service deletion."""

    async def test_delete_scales_then_deletes(self, manager, mock_ecs_client, mock_db):
        """delete_user_service scales to 0 then deletes service."""
        existing = _make_container(status="running")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        await manager.delete_user_service("user_test_123", mock_db)

        # Verify update_service (scale to 0) called first
        mock_ecs_client.update_service.assert_called_once_with(
            cluster=manager._cluster,
            service="openclaw-user_tes",
            desiredCount=0,
        )
        # Verify delete_service called
        mock_ecs_client.delete_service.assert_called_once_with(
            cluster=manager._cluster,
            service="openclaw-user_tes",
            force=True,
        )
        # Verify DB record deleted
        mock_db.delete.assert_awaited_once_with(existing)
        mock_db.commit.assert_awaited_once()

    async def test_delete_no_db_record(self, manager, mock_ecs_client, mock_db):
        """delete_user_service with no DB record still deletes ECS service."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        await manager.delete_user_service("user_test_123", mock_db)

        mock_ecs_client.update_service.assert_called_once()
        mock_ecs_client.delete_service.assert_called_once()
        mock_db.delete.assert_not_awaited()

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
    """Test Cloud Map service discovery."""

    def test_returns_ip(self, manager, mock_sd_client):
        """discover_ip returns the IPv4 address from Cloud Map."""
        mock_sd_client.discover_instances.return_value = {
            "Instances": [
                {
                    "InstanceId": "task-abc",
                    "Attributes": {
                        "AWS_INSTANCE_IPV4": "10.0.1.42",
                        "AWS_INSTANCE_PORT": "18789",
                    },
                }
            ]
        }

        ip = manager.discover_ip("openclaw-user_tes")

        assert ip == "10.0.1.42"
        mock_sd_client.discover_instances.assert_called_once_with(
            NamespaceName=manager._namespace,
            ServiceName="openclaw-user_tes",
        )

    def test_returns_none_when_no_instances(self, manager, mock_sd_client):
        """discover_ip returns None when no instances found."""
        mock_sd_client.discover_instances.return_value = {"Instances": []}

        ip = manager.discover_ip("openclaw-user_tes")
        assert ip is None

    def test_returns_none_on_error(self, manager, mock_sd_client):
        """discover_ip returns None on SDK error."""
        mock_sd_client.discover_instances.side_effect = ClientError(
            {"Error": {"Code": "NamespaceNotFound", "Message": "not found"}},
            "DiscoverInstances",
        )

        ip = manager.discover_ip("openclaw-user_tes")
        assert ip is None

    def test_returns_none_when_no_ipv4_attr(self, manager, mock_sd_client):
        """discover_ip returns None when instance lacks IPv4 attribute."""
        mock_sd_client.discover_instances.return_value = {
            "Instances": [
                {
                    "InstanceId": "task-abc",
                    "Attributes": {},
                }
            ]
        }

        ip = manager.discover_ip("openclaw-user_tes")
        assert ip is None

    def test_returns_first_instance_ip(self, manager, mock_sd_client):
        """discover_ip returns IP from the first instance when multiple exist."""
        mock_sd_client.discover_instances.return_value = {
            "Instances": [
                {
                    "InstanceId": "task-1",
                    "Attributes": {"AWS_INSTANCE_IPV4": "10.0.1.1"},
                },
                {
                    "InstanceId": "task-2",
                    "Attributes": {"AWS_INSTANCE_IPV4": "10.0.1.2"},
                },
            ]
        }

        ip = manager.discover_ip("openclaw-user_tes")
        assert ip == "10.0.1.1"


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
