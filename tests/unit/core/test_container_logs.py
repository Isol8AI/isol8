"""Test get_container_logs method on ContainerManager."""

import pytest
from unittest.mock import MagicMock

from core.containers.manager import ContainerManager, ContainerError


class TestGetContainerLogs:
    def test_get_logs_returns_string(self):
        mock_docker = MagicMock()
        mock_container = MagicMock()
        mock_container.logs.return_value = b"2026-02-27 INFO Started\n"
        mock_docker.containers.get.return_value = mock_container

        manager = ContainerManager.__new__(ContainerManager)
        manager._docker = mock_docker
        manager._cache = {}
        manager._lock = MagicMock()

        result = manager.get_container_logs("user_123", tail=50)
        assert "Started" in result
        mock_container.logs.assert_called_once_with(tail=50, timestamps=True)

    def test_get_logs_no_docker(self):
        manager = ContainerManager.__new__(ContainerManager)
        manager._docker = None
        with pytest.raises(ContainerError):
            manager.get_container_logs("user_123")
