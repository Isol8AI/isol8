"""Tests for update service -- tier changes, image updates, scheduled worker."""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock, AsyncMock

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def dynamodb_table():
    """Create a moto DynamoDB pending-updates table with status GSI."""
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")
        table = client.create_table(
            TableName="test-pending-updates",
            KeySchema=[
                {"AttributeName": "owner_id", "KeyType": "HASH"},
                {"AttributeName": "update_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "owner_id", "AttributeType": "S"},
                {"AttributeName": "update_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "scheduled_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "status-index",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "scheduled_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.meta.client.get_waiter("table_exists").wait(TableName="test-pending-updates")

        with (
            patch("core.dynamodb._table_prefix", "test-"),
            patch("core.dynamodb._dynamodb_resource", client),
        ):
            yield table


@pytest.fixture
def efs_dir():
    """Create a temp EFS directory with an openclaw.json for user_1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        user_dir = os.path.join(tmpdir, "user_1")
        os.makedirs(user_dir)
        config = {
            "gateway": {"mode": "local", "bind": "lan"},
            "agents": {
                "defaults": {
                    "model": {"primary": "amazon-bedrock/us.minimax.minimax-m2-1-v1:0"},
                    "models": {
                        "amazon-bedrock/us.minimax.minimax-m2-1-v1:0": {"alias": "MiniMax M2.1"},
                    },
                }
            },
            "tools": {"profile": "full"},
        }
        with open(os.path.join(user_dir, "openclaw.json"), "w") as f:
            json.dump(config, f)

        with patch("core.services.config_patcher._efs_mount_path", tmpdir):
            yield tmpdir


# ---- queue_tier_change tests ----


@pytest.mark.asyncio
async def test_queue_tier_change_free_to_starter_no_resize(dynamodb_table, efs_dir):
    """free -> starter: same container size (512/1024), so only config patch, no pending update."""
    from core.services.update_service import queue_tier_change

    result = await queue_tier_change("user_1", "free", "starter")

    # No resize update should be created (same cpu/memory)
    assert result is None

    # Config should be patched with starter model
    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        config = json.load(f)
    assert config["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/us.moonshotai.kimi-k2-5-v1:0"
    assert "amazon-bedrock/us.moonshotai.kimi-k2-5-v1:0" in config["agents"]["defaults"]["models"]


@pytest.mark.asyncio
async def test_queue_tier_change_starter_to_pro_with_resize(dynamodb_table, efs_dir):
    """starter -> pro: different container size (512/1024 -> 1024/2048), config patch + resize update."""
    from core.services.update_service import queue_tier_change

    result = await queue_tier_change("user_1", "starter", "pro")

    # A resize update should be created
    assert result is not None
    assert result["update_type"] == "container_resize"
    assert result["status"] == "pending"
    assert result["changes"]["new_cpu"] == "1024"
    assert result["changes"]["new_memory"] == "2048"

    # Config should be patched with pro model
    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        config = json.load(f)
    assert config["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/us.moonshotai.kimi-k2-5-v1:0"


@pytest.mark.asyncio
async def test_queue_tier_change_same_size_no_resize(dynamodb_table, efs_dir):
    """free -> starter: same container size, verify no update in DynamoDB."""
    from core.repositories import update_repo
    from core.services.update_service import queue_tier_change

    await queue_tier_change("user_1", "free", "starter")

    # No pending updates should exist
    pending = await update_repo.get_pending("user_1")
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_queue_tier_change_patches_subagent_model(dynamodb_table, efs_dir):
    """Verify that subagent model is included in the config patch."""
    from core.services.update_service import queue_tier_change

    await queue_tier_change("user_1", "free", "enterprise")

    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        config = json.load(f)
    # Enterprise has kimi as subagent model
    assert config["agents"]["defaults"]["subagent"]["model"] == "amazon-bedrock/us.moonshotai.kimi-k2-5-v1:0"


@pytest.mark.asyncio
async def test_queue_tier_change_preserves_existing_config(dynamodb_table, efs_dir):
    """Verify that non-agent config (gateway, tools) is preserved."""
    from core.services.update_service import queue_tier_change

    await queue_tier_change("user_1", "free", "starter")

    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        config = json.load(f)
    assert config["gateway"]["mode"] == "local"
    assert config["tools"]["profile"] == "full"


# ---- queue_image_update tests ----


@pytest.mark.asyncio
async def test_queue_image_update(dynamodb_table):
    """queue_image_update creates a pending update with the correct details."""
    from core.services.update_service import queue_image_update

    result = await queue_image_update("user_1", "ghcr.io/openclaw/openclaw:v2026.4.1")

    assert result["owner_id"] == "user_1"
    assert result["update_type"] == "image_update"
    assert result["status"] == "pending"
    assert result["changes"]["new_image"] == "ghcr.io/openclaw/openclaw:v2026.4.1"


@pytest.mark.asyncio
async def test_queue_image_update_custom_description(dynamodb_table):
    """queue_image_update uses custom description when provided."""
    from core.services.update_service import queue_image_update

    result = await queue_image_update("user_1", "img:v2", description="Security patch")

    assert result["description"] == "Security patch"


# ---- apply_update tests ----


@pytest.mark.asyncio
@patch("core.containers.get_ecs_manager")
async def test_apply_update_marks_applied(mock_ecs_mgr, dynamodb_table):
    """apply_update transitions status to applied."""
    from core.repositories import update_repo
    from core.services.update_service import apply_update

    mock_mgr = MagicMock()
    mock_mgr.resize_user_container = AsyncMock(return_value="arn:task:new")
    mock_ecs_mgr.return_value = mock_mgr

    item = await update_repo.create(
        owner_id="user_1",
        update_type="image_update",
        description="Image update",
        changes={"new_image": "img:v2"},
    )

    ok = await apply_update("user_1", item["update_id"])
    assert ok is True

    pending = await update_repo.get_pending("user_1")
    assert len(pending) == 0

    mock_mgr.resize_user_container.assert_called_once()


@pytest.mark.asyncio
async def test_apply_update_already_applying_returns_false(dynamodb_table):
    """apply_update returns False if update is already being applied."""
    from core.repositories import update_repo
    from core.services.update_service import apply_update

    item = await update_repo.create(
        owner_id="user_1",
        update_type="image_update",
        description="Image update",
        changes={"new_image": "img:v2"},
    )

    # Simulate already applying
    await update_repo.set_status_conditional("user_1", item["update_id"], "applying", ["pending"])

    ok = await apply_update("user_1", item["update_id"])
    assert ok is False
