"""Tests for ContainerManager (Docker orchestration).

Uses mocked Docker SDK — no real Docker daemon required.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.containers.manager import (
    ContainerManager,
    ContainerError,
    ContainerInfo,
    _INTERNAL_GATEWAY_PORT,
)


@pytest.fixture
def mock_docker_client():
    """Create a mock Docker client."""
    client = MagicMock()
    client.ping.return_value = True
    return client


@pytest.fixture
def manager(mock_docker_client):
    """Create a ContainerManager with mocked Docker client."""
    with patch("core.containers.manager.docker") as mock_docker_module:
        mock_docker_module.from_env.return_value = mock_docker_client
        mgr = ContainerManager(
            containers_root="/tmp/test-containers",
            openclaw_image="openclaw:test",
            port_range_start=19000,
            port_range_end=19010,
        )
    return mgr


class TestContainerManagerInit:
    """Test ContainerManager initialization."""

    def test_init_with_docker(self, manager):
        """Manager initializes when Docker is available."""
        assert manager.available is True

    def test_init_without_docker(self):
        """Manager handles Docker unavailable gracefully."""
        with patch("core.containers.manager.docker") as mock_docker:
            from docker.errors import DockerException

            mock_docker.from_env.side_effect = DockerException("no daemon")
            mgr = ContainerManager()
        assert mgr.available is False


class TestContainerNaming:
    """Test container and volume naming."""

    def test_container_name(self, manager):
        """Container name is derived from user_id."""
        name = manager._container_name("user_abc123")
        assert name == "isol8-user-user-abc123"
        assert " " not in name

    def test_volume_name(self, manager):
        """Volume name is derived from user_id."""
        name = manager._volume_name("user_abc123")
        assert name == "isol8-workspace-user-abc123"


class TestPortAllocation:
    """Test port allocation logic."""

    def test_allocate_first_port(self, manager):
        """First allocation returns port_range_start."""
        port = manager._allocate_port()
        assert port == 19000

    def test_allocate_skips_used(self, manager):
        """Allocation skips ports that are in use."""
        manager._cache["user_a"] = ContainerInfo("user_a", 19000, "c1", "running")
        port = manager._allocate_port()
        assert port == 19001

    def test_allocate_exhausted(self, manager):
        """Raises ContainerError when all ports are taken."""
        for i in range(11):  # 19000-19010 = 11 ports
            uid = f"user_{i}"
            manager._cache[uid] = ContainerInfo(uid, 19000 + i, f"c{i}", "running")

        with pytest.raises(ContainerError, match="No available ports"):
            manager._allocate_port()


class TestGetContainerPort:
    """Test container port lookup."""

    def test_port_for_running_container(self, manager):
        """Returns port for running container."""
        manager._cache["user_123"] = ContainerInfo("user_123", 19005, "c1", "running")
        assert manager.get_container_port("user_123") == 19005

    def test_port_for_stopped_container(self, manager):
        """Returns None for stopped container."""
        manager._cache["user_123"] = ContainerInfo("user_123", 19005, "c1", "stopped")
        assert manager.get_container_port("user_123") is None

    def test_port_for_unknown_user(self, manager):
        """Returns None for unknown user."""
        assert manager.get_container_port("nonexistent") is None


class TestProvisionContainer:
    """Test container provisioning."""

    def test_provision_creates_volume_and_container(self, manager, mock_docker_client):
        """Provisioning creates a Docker volume and starts a container."""
        from docker.errors import NotFound

        # Mock: no existing container
        mock_docker_client.containers.get.side_effect = NotFound("not found")

        # Mock: container.run returns a mock container
        mock_container = MagicMock()
        mock_container.id = "new_container_id"
        mock_container.short_id = "new_cont"
        mock_docker_client.containers.run.return_value = mock_container

        # Mock the config write helper container
        mock_docker_client.containers.run.side_effect = [
            None,  # _write_config_to_volume (alpine container)
            mock_container,  # actual OpenClaw container
        ]

        info = manager.provision_container("user_test_123")

        assert info.user_id == "user_test_123"
        assert info.port == 19000
        assert info.container_id == "new_container_id"
        assert info.status == "running"

        # Verify volume was created
        mock_docker_client.volumes.create.assert_called_once()

        # Verify cached
        assert manager.get_container_port("user_test_123") == 19000

    def test_provision_returns_existing_running(self, manager, mock_docker_client):
        """Provisioning returns existing container if already running."""
        manager._cache["user_123"] = ContainerInfo("user_123", 19000, "c1", "running")

        info = manager.provision_container("user_123")
        assert info.port == 19000
        # Docker SDK should NOT have been called for a new container
        mock_docker_client.containers.run.assert_not_called()

    def test_provision_without_docker(self):
        """Provisioning raises error when Docker unavailable."""
        with patch("core.containers.manager.docker") as mock_docker:
            from docker.errors import DockerException

            mock_docker.from_env.side_effect = DockerException("no daemon")
            mgr = ContainerManager()

        with pytest.raises(ContainerError, match="Docker not available"):
            mgr.provision_container("user_123")


class TestStopContainer:
    """Test container stopping."""

    def test_stop_running_container(self, manager, mock_docker_client):
        """Stopping a running container updates cache status."""
        manager._cache["user_123"] = ContainerInfo("user_123", 19000, "c1", "running")
        mock_container = MagicMock()
        mock_docker_client.containers.get.return_value = mock_container

        result = manager.stop_container("user_123")

        assert result is True
        mock_container.stop.assert_called_once_with(timeout=10)
        assert manager._cache["user_123"].status == "stopped"

    def test_stop_nonexistent_container(self, manager, mock_docker_client):
        """Stopping non-existent container returns False."""
        from docker.errors import NotFound

        mock_docker_client.containers.get.side_effect = NotFound("not found")

        result = manager.stop_container("user_123")
        assert result is False


class TestRemoveContainer:
    """Test container removal."""

    def test_remove_clears_cache(self, manager, mock_docker_client):
        """Removing container clears it from cache."""
        manager._cache["user_123"] = ContainerInfo("user_123", 19000, "c1", "running")
        mock_container = MagicMock()
        mock_docker_client.containers.get.return_value = mock_container

        result = manager.remove_container("user_123")
        assert result is True
        assert "user_123" not in manager._cache

    def test_remove_keeps_volume_by_default(self, manager, mock_docker_client):
        """Default removal preserves the workspace volume."""
        from docker.errors import NotFound

        mock_docker_client.containers.get.side_effect = NotFound("not found")

        manager.remove_container("user_123", keep_volume=True)
        mock_docker_client.volumes.get.assert_not_called()

    def test_remove_deletes_volume(self, manager, mock_docker_client):
        """Removal with keep_volume=False deletes the volume."""
        from docker.errors import NotFound

        mock_docker_client.containers.get.side_effect = NotFound("not found")

        mock_volume = MagicMock()
        mock_docker_client.volumes.get.return_value = mock_volume

        manager.remove_container("user_123", keep_volume=False)
        mock_volume.remove.assert_called_once_with(force=True)


class TestEnsureRunning:
    """Test ensure_running logic."""

    def test_already_running(self, manager, mock_docker_client):
        """Returns port if container is already running."""
        manager._cache["user_123"] = ContainerInfo("user_123", 19000, "c1", "running")
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_docker_client.containers.get.return_value = mock_container

        port = manager.ensure_running("user_123")
        assert port == 19000

    def test_restarts_stopped(self, manager, mock_docker_client):
        """Restarts a stopped container."""
        manager._cache["user_123"] = ContainerInfo("user_123", 19000, "c1", "stopped")
        mock_container = MagicMock()
        mock_container.status = "exited"
        mock_docker_client.containers.get.return_value = mock_container

        port = manager.ensure_running("user_123")
        assert port == 19000
        mock_container.start.assert_called_once()

    def test_no_container_record(self, manager):
        """Returns None if user has no container in cache."""
        port = manager.ensure_running("nonexistent")
        assert port is None


class TestExecCommand:
    """Test command execution inside containers."""

    def test_exec_success(self, manager, mock_docker_client):
        """Successful command returns stdout."""
        mock_container = MagicMock()
        mock_container.exec_run.return_value = (0, b'["agent1", "agent2"]')
        mock_docker_client.containers.get.return_value = mock_container

        result = manager.exec_command("user_123", ["openclaw", "agent", "list"])
        assert result == '["agent1", "agent2"]'

    def test_exec_failure_raises(self, manager, mock_docker_client):
        """Failed command raises ContainerError."""
        mock_container = MagicMock()
        mock_container.exec_run.return_value = (1, b"Error: agent not found")
        mock_docker_client.containers.get.return_value = mock_container

        with pytest.raises(ContainerError, match="exited with code 1"):
            manager.exec_command("user_123", ["openclaw", "agent", "get", "none"])

    def test_exec_not_found_raises(self, manager, mock_docker_client):
        """Exec on non-existent container raises ContainerError."""
        from docker.errors import NotFound

        mock_docker_client.containers.get.side_effect = NotFound("not found")

        with pytest.raises(ContainerError, match="Container not found"):
            manager.exec_command("user_123", ["openclaw", "agent", "list"])

    def test_exec_without_docker(self):
        """Exec without Docker raises ContainerError."""
        with patch("core.containers.manager.docker") as mock_docker:
            from docker.errors import DockerException

            mock_docker.from_env.side_effect = DockerException("no daemon")
            mgr = ContainerManager()

        with pytest.raises(ContainerError, match="Docker not available"):
            mgr.exec_command("user_123", ["ls"])


class TestHealthCheck:
    """Test container health checks."""

    def test_healthy_container(self, manager):
        """Healthy container returns True."""
        manager._cache["user_123"] = ContainerInfo("user_123", 19000, "c1", "running")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            assert manager.is_healthy("user_123") is True

    def test_unhealthy_no_container(self, manager):
        """No container returns False."""
        assert manager.is_healthy("nonexistent") is False

    def test_unhealthy_connection_error(self, manager):
        """Connection error returns False."""
        manager._cache["user_123"] = ContainerInfo("user_123", 19000, "c1", "running")

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            assert manager.is_healthy("user_123") is False


class TestReconcile:
    """Test startup reconciliation."""

    def test_reconcile_discovers_containers(self, manager, mock_docker_client):
        """Reconcile discovers running containers and populates cache."""
        mock_container = MagicMock()
        mock_container.name = "isol8-user-user-abc123"
        mock_container.id = "container_id_1"
        mock_container.status = "running"
        mock_container.labels = {"isol8.user_id": "user_abc123"}
        mock_container.ports = {f"{_INTERNAL_GATEWAY_PORT}/tcp": [{"HostIp": "127.0.0.1", "HostPort": "19000"}]}

        mock_docker_client.containers.list.return_value = [mock_container]

        manager.reconcile()

        assert "user_abc123" in manager._cache
        info = manager._cache["user_abc123"]
        assert info.port == 19000
        assert info.status == "running"

    def test_reconcile_empty(self, manager, mock_docker_client):
        """Reconcile with no containers leaves cache empty."""
        mock_docker_client.containers.list.return_value = []

        manager.reconcile()
        assert len(manager._cache) == 0

    def test_reconcile_without_docker(self):
        """Reconcile without Docker logs warning and returns."""
        with patch("core.containers.manager.docker") as mock_docker:
            from docker.errors import DockerException

            mock_docker.from_env.side_effect = DockerException("no daemon")
            mgr = ContainerManager()

        # Should not raise
        mgr.reconcile()
        assert len(mgr._cache) == 0


class TestEnvForContainer:
    """Test _env_for_container credential endpoint env vars."""

    def test_uses_credential_endpoint_env_vars(self, manager):
        """Container env uses ECS credential URI instead of static creds."""
        env = manager._env_for_container(gateway_token="my-secret-token")

        assert env["AWS_CONTAINER_CREDENTIALS_FULL_URI"] == "http://172.17.0.1:8000/internal/credentials"
        assert env["AWS_CONTAINER_AUTHORIZATION_TOKEN"] == "my-secret-token"
        assert "AWS_ACCESS_KEY_ID" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env

    def test_passes_brave_api_key(self, manager):
        """BRAVE_API_KEY is passed through when set."""
        with patch.dict("os.environ", {"BRAVE_API_KEY": "bk-test123"}):
            env = manager._env_for_container(gateway_token="token")
        assert env["BRAVE_API_KEY"] == "bk-test123"

    def test_sets_aws_region(self, manager):
        """AWS region env vars are set."""
        with patch.dict("os.environ", {"AWS_REGION": "us-west-2"}):
            env = manager._env_for_container(gateway_token="token")
        assert env["AWS_REGION"] == "us-west-2"
        assert env["AWS_DEFAULT_REGION"] == "us-west-2"


class TestContainerInfo:
    """Test ContainerInfo data class."""

    def test_create_info(self):
        """ContainerInfo stores all fields."""
        info = ContainerInfo("user_123", 19000, "container_abc", "running")
        assert info.user_id == "user_123"
        assert info.port == 19000
        assert info.container_id == "container_abc"
        assert info.status == "running"
