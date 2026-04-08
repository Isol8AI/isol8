"""Tests for channel_link_service — member identity linking flow."""

import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


def _write_pairing_file(owner_dir: str, channel: str, requests: list[dict]):
    creds_dir = os.path.join(owner_dir, ".openclaw", "credentials")
    os.makedirs(creds_dir, exist_ok=True)
    path = os.path.join(creds_dir, f"{channel}-pairing.json")
    with open(path, "w") as f:
        json.dump({"version": 1, "requests": requests}, f)


@pytest.fixture
def tmp_efs(monkeypatch):
    """Tmp EFS dir with an openclaw.json scaffold for a single owner."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr("core.services.config_patcher._efs_mount_path", d)
        monkeypatch.setattr("core.services.channel_link_service._efs_mount_path", d)
        owner_id = "user_test"
        owner_dir = os.path.join(d, owner_id)
        os.makedirs(owner_dir)
        with open(os.path.join(owner_dir, "openclaw.json"), "w") as f:
            json.dump(
                {
                    "channels": {
                        "telegram": {
                            "accounts": {
                                "main": {"botToken": "xxx", "allowFrom": []},
                            },
                        },
                    },
                },
                f,
            )
        yield d, owner_id, owner_dir


@pytest.mark.asyncio
async def test_complete_link_happy_path(tmp_efs):
    _, owner_id, owner_dir = tmp_efs
    _write_pairing_file(
        owner_dir,
        "telegram",
        [
            {
                "id": "12345",
                "code": "XYZ98765",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "lastSeenAt": datetime.now(timezone.utc).isoformat(),
            },
        ],
    )

    from core.services import channel_link_service

    with patch("core.services.channel_link_service.channel_link_repo") as mock_repo:
        mock_repo.get_by_peer = AsyncMock(return_value=None)
        mock_repo.put = AsyncMock()

        result = await channel_link_service.complete_link(
            owner_id=owner_id,
            provider="telegram",
            agent_id="main",
            code="XYZ98765",
            member_id="user_bob",
        )

    assert result["status"] == "linked"
    assert result["peer_id"] == "12345"

    # allowFrom was patched
    with open(os.path.join(owner_dir, "openclaw.json")) as f:
        cfg = json.load(f)
    assert cfg["channels"]["telegram"]["accounts"]["main"]["allowFrom"] == ["12345"]

    # DynamoDB row was written
    mock_repo.put.assert_called_once()
    call_kwargs = mock_repo.put.call_args.kwargs
    assert call_kwargs["owner_id"] == owner_id
    assert call_kwargs["provider"] == "telegram"
    assert call_kwargs["agent_id"] == "main"
    assert call_kwargs["peer_id"] == "12345"
    assert call_kwargs["member_id"] == "user_bob"
    assert call_kwargs["linked_via"] == "settings"
