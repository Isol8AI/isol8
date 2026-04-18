"""Unit tests for routers/debug.py — dev/test-only debug endpoints."""

from unittest.mock import patch, AsyncMock, MagicMock

import pytest


class TestDeleteUserData:
    """Test DELETE /api/v1/debug/user-data — atomic per-owner teardown."""

    @pytest.mark.asyncio
    @patch("routers.debug.container_repo")
    @patch("routers.debug.api_key_repo")
    @patch("routers.debug.billing_repo")
    @patch("routers.debug.update_repo")
    @patch("routers.debug.usage_repo")
    @patch("routers.debug.channel_link_repo")
    @patch("routers.debug.user_repo")
    @patch("routers.debug.connection_service")
    @patch("routers.debug.get_ecs_manager")
    @patch("routers.debug.get_workspace")
    async def test_full_teardown_returns_summary(
        self,
        mock_workspace,
        mock_ecs_mgr,
        mock_conn_svc,
        mock_user_repo,
        mock_chan_repo,
        mock_usage_repo,
        mock_update_repo,
        mock_billing_repo,
        mock_apikey_repo,
        mock_container_repo,
        async_client,
    ):
        """Endpoint returns deleted summary and calls each subsystem teardown."""
        mock_container = {
            "owner_id": "user_test_123",
            "service_name": "openclaw-user_test_123-abc",
            "access_point_id": "fsap-abc",
            "task_definition_arn": "arn:aws:ecs:...:task-definition/foo:5",
        }
        mock_container_repo.get_by_owner_id = AsyncMock(return_value=mock_container)
        mock_container_repo.delete = AsyncMock()
        mock_apikey_repo.delete_all_for_owner = AsyncMock(return_value=2)
        mock_billing_repo.delete = AsyncMock()
        mock_update_repo.delete_all_for_owner = AsyncMock(return_value=1)
        mock_usage_repo.delete_all_for_owner = AsyncMock(return_value=4)
        mock_chan_repo.delete_all_for_owner = AsyncMock(return_value=0)
        mock_user_repo.delete = AsyncMock()
        mock_conn_svc.delete_all_for_user = AsyncMock(return_value=3)

        ecs_mgr = MagicMock()
        ecs_mgr.delete_user_service = AsyncMock()
        ecs_mgr._deregister_task_definition = MagicMock()
        mock_ecs_mgr.return_value = ecs_mgr

        ws = MagicMock()
        ws.delete_user_dir = MagicMock()
        mock_workspace.return_value = ws

        res = await async_client.delete("/api/v1/debug/user-data")

        assert res.status_code == 200
        body = res.json()
        assert body["deleted"]["ecs"] is True
        assert body["deleted"]["efs"] is True
        assert "users" in body["deleted"]["ddb"]
        assert "containers" in body["deleted"]["ddb"]
        assert "billing-accounts" in body["deleted"]["ddb"]
        assert "api-keys" in body["deleted"]["ddb"]
        assert "usage-counters" in body["deleted"]["ddb"]
        assert "pending-updates" in body["deleted"]["ddb"]
        assert "channel-links" in body["deleted"]["ddb"]
        assert "ws-connections" in body["deleted"]["ddb"]

        ecs_mgr.delete_user_service.assert_called_once_with("user_test_123")
        ws.delete_user_dir.assert_called_once_with("user_test_123")
        mock_user_repo.delete.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    @patch("routers.debug.settings")
    async def test_endpoint_disabled_in_prod(self, mock_settings, async_client):
        """Endpoint returns 403 when ENVIRONMENT == 'prod' (existing /debug guard)."""
        mock_settings.ENVIRONMENT = "prod"
        res = await async_client.delete("/api/v1/debug/user-data")
        assert res.status_code == 403
