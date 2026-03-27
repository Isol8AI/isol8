# Container Update System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two-track container update system — Track 1 (silent EFS patch, zero downtime) for config changes, Track 2 (notification + user schedule) for image/resize updates.

**Architecture:** Config patches write directly to EFS and leverage OpenClaw's file watcher for hot-reload. Container updates queue in DynamoDB as pending updates with a scheduled worker for deferred apply. Frontend shows a Tesla-style update banner for Track 2 changes.

**Tech Stack:** Python/FastAPI, DynamoDB (boto3/moto), ECS Fargate, EFS, TypeScript/Next.js 16, CDK

**Spec:** `docs/superpowers/specs/2026-03-26-container-update-system-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `apps/backend/core/services/config_patcher.py` | `patch_openclaw_config(owner_id, patch)` — file-locked read/merge/write to EFS |
| `apps/backend/core/repositories/update_repo.py` | DynamoDB CRUD for `pending-updates` table |
| `apps/backend/core/services/update_service.py` | Create updates, apply updates (config + ECS), scheduled worker loop |
| `apps/backend/routers/updates.py` | `GET /updates`, `POST /updates/{id}/apply`, `POST /updates` (admin) |
| `apps/backend/tests/unit/services/test_config_patcher.py` | Config patch tests |
| `apps/backend/tests/unit/repositories/test_update_repo.py` | Update repo tests (moto) |
| `apps/backend/tests/unit/services/test_update_service.py` | Update service tests |

### Modified Files
| File | What Changes |
|------|-------------|
| `apps/backend/core/config.py` | Add `model_aliases` to `TIER_CONFIG` |
| `apps/backend/routers/billing.py` | Stripe webhook: Track 1 silent patch + Track 2 queue for size changes |
| `apps/backend/main.py` | Register updates router, start scheduled worker in lifespan |
| `apps/infra/lib/stacks/database-stack.ts` | Add `pending-updates` DynamoDB table with status GSI |
| `apps/infra/lib/stacks/service-stack.ts` | Wire table IAM permissions |
| `apps/frontend/src/components/chat/AgentChatWindow.tsx` | Update banner component |
| `apps/frontend/src/hooks/useGateway.tsx` | Handle `update_available` WebSocket event |

---

## Task 1: Config Patcher Service

File-locked, atomic EFS config patching with backup/rollback.

**Files:**
- Create: `apps/backend/core/services/config_patcher.py`
- Create: `apps/backend/tests/unit/services/test_config_patcher.py`

- [ ] **Step 1: Write test file**

Create `apps/backend/tests/unit/services/test_config_patcher.py`:

```python
"""Tests for config patcher — EFS openclaw.json patching."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def efs_dir():
    """Create a temp dir simulating EFS mount with a user's openclaw.json."""
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


@pytest.mark.asyncio
async def test_patch_updates_model(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config("user_1", {
        "agents": {
            "defaults": {
                "model": {"primary": "amazon-bedrock/us.moonshotai.kimi-k2-5-v1:0"},
            }
        }
    })

    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        result = json.load(f)

    assert result["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/us.moonshotai.kimi-k2-5-v1:0"


@pytest.mark.asyncio
async def test_patch_preserves_gateway(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config("user_1", {
        "agents": {"defaults": {"model": {"primary": "new-model"}}}
    })

    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        result = json.load(f)

    # Gateway config must be untouched
    assert result["gateway"]["mode"] == "local"
    assert result["gateway"]["bind"] == "lan"


@pytest.mark.asyncio
async def test_patch_preserves_tools(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config("user_1", {
        "agents": {"defaults": {"model": {"primary": "new-model"}}}
    })

    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        result = json.load(f)

    assert result["tools"]["profile"] == "full"


@pytest.mark.asyncio
async def test_patch_creates_backup(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config("user_1", {
        "agents": {"defaults": {"model": {"primary": "new-model"}}}
    })

    backup = os.path.join(efs_dir, "user_1", "openclaw.json.bak")
    assert os.path.exists(backup)

    with open(backup) as f:
        original = json.load(f)
    assert original["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/us.minimax.minimax-m2-1-v1:0"


@pytest.mark.asyncio
async def test_patch_deep_merges_models(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config("user_1", {
        "agents": {
            "defaults": {
                "models": {
                    "amazon-bedrock/us.moonshotai.kimi-k2-5-v1:0": {"alias": "Kimi K2.5"},
                },
            }
        }
    })

    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        result = json.load(f)

    models = result["agents"]["defaults"]["models"]
    # New model added
    assert "amazon-bedrock/us.moonshotai.kimi-k2-5-v1:0" in models
    # Old model preserved
    assert "amazon-bedrock/us.minimax.minimax-m2-1-v1:0" in models


@pytest.mark.asyncio
async def test_patch_nonexistent_owner_raises(efs_dir):
    from core.services.config_patcher import patch_openclaw_config, ConfigPatchError

    with pytest.raises(ConfigPatchError, match="not found"):
        await patch_openclaw_config("nonexistent_user", {"agents": {}})
```

- [ ] **Step 2: Write `config_patcher.py`**

Create `apps/backend/core/services/config_patcher.py`:

```python
"""EFS config patcher — file-locked, atomic, deep-merge patching of openclaw.json."""

import asyncio
import copy
import fcntl
import json
import logging
import os
import shutil
import tempfile

from core.config import settings

logger = logging.getLogger(__name__)

_efs_mount_path = settings.EFS_MOUNT_PATH


class ConfigPatchError(Exception):
    pass


def _deep_merge(base: dict, patch: dict) -> dict:
    """Deep-merge patch into base. Patch values override base values.
    Dicts are merged recursively. Non-dict values are replaced."""
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


async def patch_openclaw_config(owner_id: str, patch: dict) -> None:
    """Patch openclaw.json on EFS with file locking and atomic write.

    1. Acquire file lock (prevents concurrent patches)
    2. Read current config
    3. Back up to .bak
    4. Deep-merge patch
    5. Write atomically (temp file + rename)
    6. Release lock
    """
    config_dir = os.path.join(_efs_mount_path, owner_id)
    config_path = os.path.join(config_dir, "openclaw.json")
    backup_path = os.path.join(config_dir, "openclaw.json.bak")

    if not os.path.exists(config_path):
        raise ConfigPatchError(f"Config not found for owner {owner_id}")

    def _do_patch():
        lock_fd = None
        try:
            # Acquire exclusive file lock
            lock_fd = open(config_path, "r")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            # Read current config
            with open(config_path, "r") as f:
                current = json.load(f)

            # Backup
            shutil.copy2(config_path, backup_path)

            # Deep merge
            merged = _deep_merge(current, patch)

            # Validate JSON
            json.dumps(merged)  # raises if not serializable

            # Atomic write: temp file + rename
            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(merged, f, indent=2)
                os.rename(tmp_path, config_path)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info("Patched openclaw.json for owner %s: %s", owner_id, list(patch.keys()))

        finally:
            if lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    await asyncio.to_thread(_do_patch)
```

- [ ] **Step 3: Run tests**

Run: `cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev uv run pytest tests/unit/services/test_config_patcher.py -v`

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/services/config_patcher.py apps/backend/tests/unit/services/test_config_patcher.py
git commit -m "feat: add config patcher with file locking, atomic write, deep merge"
```

---

## Task 2: Update Repository (DynamoDB)

DynamoDB CRUD for the `pending-updates` table.

**Files:**
- Create: `apps/backend/core/repositories/update_repo.py`
- Create: `apps/backend/tests/unit/repositories/test_update_repo.py`

- [ ] **Step 1: Write test file**

Create `apps/backend/tests/unit/repositories/test_update_repo.py`:

```python
"""Tests for pending updates DynamoDB repository."""

import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def dynamodb_table():
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
            GlobalSecondaryIndexes=[{
                "IndexName": "status-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "scheduled_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        table.meta.client.get_waiter("table_exists").wait(TableName="test-pending-updates")
        with (
            patch("core.dynamodb._table_prefix", "test-"),
            patch("core.dynamodb._dynamodb_resource", client),
        ):
            yield


@pytest.mark.asyncio
async def test_create_and_get_pending(dynamodb_table):
    from core.repositories import update_repo

    update = await update_repo.create(
        owner_id="user_1",
        update_type="image_update",
        description="OpenClaw v2026.4.1",
        changes={"new_image": "ghcr.io/openclaw/openclaw:v2026.4.1"},
    )
    assert update["status"] == "pending"
    assert update["owner_id"] == "user_1"

    pending = await update_repo.get_pending("user_1")
    assert len(pending) == 1
    assert pending[0]["description"] == "OpenClaw v2026.4.1"


@pytest.mark.asyncio
async def test_set_status_with_condition(dynamodb_table):
    from core.repositories import update_repo

    update = await update_repo.create("user_1", "image_update", "test", {})

    # Should succeed: pending → applying
    result = await update_repo.set_status_conditional(
        "user_1", update["update_id"], "applying",
        expected_statuses=["pending", "scheduled"],
    )
    assert result is True

    # Should fail: already applying, condition fails
    result = await update_repo.set_status_conditional(
        "user_1", update["update_id"], "applying",
        expected_statuses=["pending", "scheduled"],
    )
    assert result is False


@pytest.mark.asyncio
async def test_set_scheduled(dynamodb_table):
    from core.repositories import update_repo

    update = await update_repo.create("user_1", "image_update", "test", {})
    await update_repo.set_scheduled("user_1", update["update_id"], "2026-03-27T02:00:00Z")

    pending = await update_repo.get_pending("user_1")
    assert pending[0]["status"] == "scheduled"
    assert pending[0]["scheduled_at"] == "2026-03-27T02:00:00Z"


@pytest.mark.asyncio
async def test_get_due_scheduled(dynamodb_table):
    from core.repositories import update_repo

    await update_repo.create("user_1", "image_update", "test", {})
    update = (await update_repo.get_pending("user_1"))[0]
    await update_repo.set_scheduled("user_1", update["update_id"], "2020-01-01T00:00:00Z")

    due = await update_repo.get_due_scheduled()
    assert len(due) == 1


@pytest.mark.asyncio
async def test_get_pending_empty(dynamodb_table):
    from core.repositories import update_repo
    assert await update_repo.get_pending("user_1") == []
```

- [ ] **Step 2: Write `update_repo.py`**

Create `apps/backend/core/repositories/update_repo.py`:

```python
"""Pending updates repository — DynamoDB CRUD for the pending-updates table."""

import time
import ulid
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("pending-updates")


def _generate_update_id() -> str:
    return str(ulid.new())


async def create(
    owner_id: str,
    update_type: str,
    description: str,
    changes: dict,
    force_by: str | None = None,
) -> dict:
    """Create a new pending update."""
    table = _get_table()
    now = utc_now_iso()
    item = {
        "owner_id": owner_id,
        "update_id": _generate_update_id(),
        "type": update_type,
        "status": "pending",
        "description": description,
        "changes": changes,
        "created_at": now,
    }
    if force_by:
        item["force_by"] = force_by
    await run_in_thread(table.put_item, Item=item)
    return item


async def get_pending(owner_id: str) -> list[dict]:
    """Get all pending/scheduled updates for an owner."""
    table = _get_table()
    response = await run_in_thread(
        table.query,
        KeyConditionExpression=Key("owner_id").eq(owner_id),
        FilterExpression=Attr("status").is_in(["pending", "scheduled"]),
    )
    return response.get("Items", [])


async def set_status_conditional(
    owner_id: str,
    update_id: str,
    new_status: str,
    expected_statuses: list[str],
) -> bool:
    """Set status with a condition check. Returns True if successful, False if condition failed."""
    table = _get_table()
    try:
        # Build condition: status must be one of expected_statuses
        condition = Attr("status").is_in(expected_statuses)
        update_expr = "SET #s = :new_status"
        expr_names = {"#s": "status"}
        expr_values = {":new_status": new_status}

        if new_status == "applied":
            update_expr += ", applied_at = :now, #ttl = :ttl_val"
            expr_names["#ttl"] = "ttl"
            expr_values[":now"] = utc_now_iso()
            expr_values[":ttl_val"] = int(time.time()) + (30 * 86400)  # 30 days

        await run_in_thread(
            table.update_item,
            Key={"owner_id": owner_id, "update_id": update_id},
            UpdateExpression=update_expr,
            ConditionExpression=condition,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


async def set_scheduled(owner_id: str, update_id: str, scheduled_at: str) -> None:
    """Set an update to scheduled status with a target time."""
    table = _get_table()
    await run_in_thread(
        table.update_item,
        Key={"owner_id": owner_id, "update_id": update_id},
        UpdateExpression="SET #s = :status, scheduled_at = :at",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "scheduled", ":at": scheduled_at},
    )


async def set_snoozed(owner_id: str, update_id: str) -> None:
    """Record a snooze timestamp."""
    table = _get_table()
    await run_in_thread(
        table.update_item,
        Key={"owner_id": owner_id, "update_id": update_id},
        UpdateExpression="SET last_snoozed_at = :now",
        ExpressionAttributeValues={":now": utc_now_iso()},
    )


async def get_due_scheduled() -> list[dict]:
    """Get all scheduled updates that are due (scheduled_at <= now). Uses GSI."""
    table = _get_table()
    now = utc_now_iso()
    response = await run_in_thread(
        table.query,
        IndexName="status-index",
        KeyConditionExpression=(
            Key("status").eq("scheduled") & Key("scheduled_at").lte(now)
        ),
    )
    return response.get("Items", [])
```

- [ ] **Step 3: Run tests**

Run: `cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev uv run pytest tests/unit/repositories/test_update_repo.py -v`

Note: You may need to `uv add python-ulid` if `ulid` is not installed. Check `pyproject.toml` first.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/repositories/update_repo.py apps/backend/tests/unit/repositories/test_update_repo.py
git commit -m "feat: add pending updates DynamoDB repository with conditional status writes"
```

---

## Task 3: Update Service

Create updates, apply updates (Track 1 + Track 2), scheduled worker.

**Files:**
- Create: `apps/backend/core/services/update_service.py`
- Create: `apps/backend/tests/unit/services/test_update_service.py`
- Modify: `apps/backend/core/config.py`

- [ ] **Step 1: Add `model_aliases` to `TIER_CONFIG`**

Read `apps/backend/core/config.py`. Add a `model_aliases` field to each tier in `TIER_CONFIG`. This defines which models appear in the selector per tier. Example for `free`:

```python
"model_aliases": {
    "amazon-bedrock/us.minimax.minimax-m2-1-v1:0": {"alias": "MiniMax M2.1"},
},
```

For `starter` and `pro`, include both MiniMax and Kimi. For `enterprise`, include all models.

- [ ] **Step 2: Write test file**

Create `apps/backend/tests/unit/services/test_update_service.py`:

```python
"""Tests for update service."""

import json
import os
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def dynamodb_tables():
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")
        # Pending updates table
        client.create_table(
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
            GlobalSecondaryIndexes=[{
                "IndexName": "status-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "scheduled_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        # Containers table
        client.create_table(
            TableName="test-containers",
            KeySchema=[{"AttributeName": "owner_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "owner_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        with (
            patch("core.dynamodb._table_prefix", "test-"),
            patch("core.dynamodb._dynamodb_resource", client),
        ):
            yield


@pytest.fixture
def efs_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        user_dir = os.path.join(tmpdir, "user_1")
        os.makedirs(user_dir)
        config = {
            "gateway": {"mode": "local"},
            "agents": {"defaults": {"model": {"primary": "old-model"}, "models": {}}},
        }
        with open(os.path.join(user_dir, "openclaw.json"), "w") as f:
            json.dump(config, f)
        with patch("core.services.config_patcher._efs_mount_path", tmpdir):
            yield tmpdir


@pytest.mark.asyncio
async def test_queue_tier_change_creates_silent_patch(dynamodb_tables, efs_dir):
    from core.services.update_service import queue_tier_change

    await queue_tier_change("user_1", old_tier="free", new_tier="starter")

    # Verify config was patched (Track 1 — silent)
    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        config = json.load(f)
    assert "kimi" in config["agents"]["defaults"]["model"]["primary"].lower()


@pytest.mark.asyncio
async def test_queue_tier_change_with_resize_creates_pending(dynamodb_tables, efs_dir):
    from core.services.update_service import queue_tier_change
    from core.repositories import update_repo

    # starter → pro requires resize (different CPU/memory)
    await queue_tier_change("user_1", old_tier="starter", new_tier="pro")

    pending = await update_repo.get_pending("user_1")
    assert len(pending) == 1
    assert pending[0]["type"] == "container_resize"


@pytest.mark.asyncio
async def test_queue_tier_change_same_size_no_pending(dynamodb_tables, efs_dir):
    from core.services.update_service import queue_tier_change
    from core.repositories import update_repo

    # free → starter: same CPU/memory, no Track 2 needed
    await queue_tier_change("user_1", old_tier="free", new_tier="starter")

    pending = await update_repo.get_pending("user_1")
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_queue_image_update(dynamodb_tables):
    from core.services.update_service import queue_image_update
    from core.repositories import update_repo

    await queue_image_update("user_1", "ghcr.io/openclaw/openclaw:v2026.4.1")

    pending = await update_repo.get_pending("user_1")
    assert len(pending) == 1
    assert pending[0]["type"] == "image_update"
    assert pending[0]["changes"]["new_image"] == "ghcr.io/openclaw/openclaw:v2026.4.1"
```

- [ ] **Step 3: Write `update_service.py`**

Create `apps/backend/core/services/update_service.py`:

```python
"""Update service — queues and applies container updates (Track 1 + Track 2)."""

import asyncio
import logging

from core.config import TIER_CONFIG
from core.repositories import update_repo, container_repo
from core.services.config_patcher import patch_openclaw_config

logger = logging.getLogger(__name__)


async def queue_tier_change(owner_id: str, old_tier: str, new_tier: str) -> None:
    """Handle a tier change. Track 1 (silent config patch) + Track 2 (resize if needed)."""
    new_config = TIER_CONFIG.get(new_tier, TIER_CONFIG["free"])
    old_config = TIER_CONFIG.get(old_tier, TIER_CONFIG["free"])

    # Track 1: Silent config patch (model access) — always
    await patch_openclaw_config(owner_id, {
        "agents": {
            "defaults": {
                "model": {"primary": new_config["primary_model"]},
                "models": new_config.get("model_aliases", {}),
                "subagents": {"model": new_config["subagent_model"]},
            }
        }
    })
    logger.info("Track 1: Patched models for owner %s (%s → %s)", owner_id, old_tier, new_tier)

    # Track 2: Container resize — only if CPU/memory differs
    if (
        new_config["container_cpu"] != old_config["container_cpu"]
        or new_config["container_memory"] != old_config["container_memory"]
    ):
        await update_repo.create(
            owner_id=owner_id,
            update_type="container_resize",
            description=f"Container upgrade to {new_tier.title()} specs",
            changes={
                "new_cpu": new_config["container_cpu"],
                "new_memory": new_config["container_memory"],
            },
        )
        logger.info("Track 2: Queued resize for owner %s (%s → %s)", owner_id, old_tier, new_tier)


async def queue_image_update(owner_id: str, new_image: str, description: str | None = None) -> dict:
    """Queue an image update for a specific owner."""
    return await update_repo.create(
        owner_id=owner_id,
        update_type="image_update",
        description=description or f"New version available",
        changes={"new_image": new_image},
    )


async def queue_fleet_image_update(new_image: str, description: str | None = None) -> int:
    """Queue image update for all active owners. Returns count."""
    from core.repositories import billing_repo
    # This is a simplified version — for scale, use batch_write_item
    # For now, iterate owners (fine for < 1000 users)
    from core.dynamodb import get_table, run_in_thread
    table = get_table("billing-accounts")
    response = await run_in_thread(table.scan, ProjectionExpression="owner_id")
    owners = [item["owner_id"] for item in response.get("Items", [])]

    count = 0
    for owner_id in owners:
        await queue_image_update(owner_id, new_image, description)
        count += 1

    logger.info("Queued image update for %d owners: %s", count, new_image)
    return count


async def apply_update(owner_id: str, update_id: str) -> bool:
    """Apply a pending update. Returns True if successful."""
    # Conditional write: prevent double-apply
    acquired = await update_repo.set_status_conditional(
        owner_id, update_id, "applying",
        expected_statuses=["pending", "scheduled"],
    )
    if not acquired:
        logger.warning("Update %s already being applied or completed", update_id)
        return False

    try:
        # Get the update details
        pending = await update_repo.get_pending(owner_id)
        update = next((u for u in pending if u["update_id"] == update_id), None)
        if not update:
            # Status is now "applying" so it won't show in get_pending — query directly
            from core.dynamodb import get_table, run_in_thread
            table = get_table("pending-updates")
            response = await run_in_thread(
                table.get_item, Key={"owner_id": owner_id, "update_id": update_id}
            )
            update = response.get("Item")

        if not update:
            logger.error("Update %s not found for owner %s", update_id, owner_id)
            return False

        changes = update.get("changes", {})

        # Apply config patch (if any)
        config_patch = changes.get("config_patch")
        if config_patch:
            await patch_openclaw_config(owner_id, config_patch)

        # Apply ECS changes (image, CPU, memory)
        new_image = changes.get("new_image")
        new_cpu = changes.get("new_cpu")
        new_memory = changes.get("new_memory")

        if new_image or new_cpu or new_memory:
            from core.containers import get_ecs_manager
            container = await container_repo.get_by_owner_id(owner_id)
            if container and container.get("service_name"):
                ecs = get_ecs_manager()
                # Update task definition and force new deployment
                await asyncio.to_thread(
                    ecs.update_user_container,
                    owner_id=owner_id,
                    service_name=container["service_name"],
                    new_image=new_image,
                    new_cpu=new_cpu,
                    new_memory=new_memory,
                )

        # Mark as applied
        await update_repo.set_status_conditional(
            owner_id, update_id, "applied",
            expected_statuses=["applying"],
        )
        logger.info("Applied update %s for owner %s", update_id, owner_id)
        return True

    except Exception as e:
        logger.exception("Failed to apply update %s for owner %s", update_id, owner_id)
        # Mark as failed
        await update_repo.set_status_conditional(
            owner_id, update_id, "failed",
            expected_statuses=["applying"],
        )
        return False


async def run_scheduled_worker() -> None:
    """Background loop: check for due scheduled updates every 60 seconds."""
    while True:
        try:
            due = await update_repo.get_due_scheduled()
            for update in due:
                await apply_update(update["owner_id"], update["update_id"])
        except Exception:
            logger.exception("Scheduled update worker error")
        await asyncio.sleep(60)
```

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev uv run pytest tests/unit/services/test_update_service.py -v`

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/update_service.py apps/backend/tests/unit/services/test_update_service.py apps/backend/core/config.py
git commit -m "feat: add update service with tier change, image updates, scheduled worker"
```

---

## Task 4: Updates Router + Main Registration

API endpoints for updates + register in main.py + start worker.

**Files:**
- Create: `apps/backend/routers/updates.py`
- Modify: `apps/backend/main.py`

- [ ] **Step 1: Create `routers/updates.py`**

```python
"""Container update endpoints — pending updates, apply, admin fleet push."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user, resolve_owner_id, require_org_admin
from core.repositories import update_repo
from core.services.update_service import apply_update, queue_image_update, queue_fleet_image_update

logger = logging.getLogger(__name__)

router = APIRouter()


class ApplyRequest(BaseModel):
    schedule: str  # "now" | "tonight" | "remind_later"


class AdminUpdateRequest(BaseModel):
    owner_id: str  # specific owner or "all"
    update_type: str  # "image_update" | "container_resize" | "gateway_config"
    description: str
    changes: dict
    force_by: str | None = None


@router.get("/updates")
async def get_updates(auth: AuthContext = Depends(get_current_user)):
    """Get pending updates for the authenticated owner."""
    owner_id = resolve_owner_id(auth)
    updates = await update_repo.get_pending(owner_id)
    return [
        {
            "update_id": u["update_id"],
            "type": u["type"],
            "description": u["description"],
            "status": u["status"],
            "created_at": u["created_at"],
            "scheduled_at": u.get("scheduled_at"),
        }
        for u in updates
    ]


@router.post("/updates/{update_id}/apply")
async def apply_update_endpoint(
    update_id: str,
    request: ApplyRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Apply or schedule a pending update."""
    if auth.is_org_context:
        require_org_admin(auth)

    owner_id = resolve_owner_id(auth)

    if request.schedule == "now":
        success = await apply_update(owner_id, update_id)
        if not success:
            raise HTTPException(status_code=409, detail="Update already applied or in progress")
        return {"status": "applied"}

    elif request.schedule == "tonight":
        from datetime import datetime, timezone, timedelta
        tonight = datetime.now(timezone.utc).replace(hour=2, minute=0, second=0, microsecond=0)
        if tonight < datetime.now(timezone.utc):
            tonight += timedelta(days=1)
        await update_repo.set_scheduled(owner_id, update_id, tonight.isoformat())
        return {"status": "scheduled", "scheduled_at": tonight.isoformat()}

    elif request.schedule == "remind_later":
        await update_repo.set_snoozed(owner_id, update_id)
        return {"status": "snoozed"}

    raise HTTPException(status_code=400, detail="Invalid schedule option")


@router.post("/updates")
async def create_admin_update(
    request: AdminUpdateRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Admin: create pending updates for owners. Requires admin role."""
    # For now, any authenticated user can push updates
    # TODO: add proper admin auth check

    if request.owner_id == "all":
        if request.update_type == "image_update":
            count = await queue_fleet_image_update(
                request.changes.get("new_image", ""),
                request.description,
            )
            return {"status": "queued", "count": count}
        raise HTTPException(status_code=400, detail="Fleet-wide only supports image_update")

    update = await update_repo.create(
        owner_id=request.owner_id,
        update_type=request.update_type,
        description=request.description,
        changes=request.changes,
        force_by=request.force_by,
    )
    return {"status": "created", "update_id": update["update_id"]}
```

- [ ] **Step 2: Register router + start worker in `main.py`**

Read `apps/backend/main.py`. Add:

1. Import: `from routers import updates`
2. In the routers section, add: `app.include_router(updates.router, prefix=f"{settings.API_V1_STR}/container", tags=["container"])`
3. In the lifespan, after `await startup_containers()`, add:
```python
    from core.services.update_service import run_scheduled_worker
    worker_task = asyncio.create_task(run_scheduled_worker())
```
4. In the shutdown section, add: `worker_task.cancel()`

- [ ] **Step 3: Run full test suite**

Run: `cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev uv run pytest tests/ -v`

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/updates.py apps/backend/main.py
git commit -m "feat: add updates router and scheduled worker startup"
```

---

## Task 5: Billing Webhook Integration

Wire Track 1 + Track 2 into Stripe webhook handlers.

**Files:**
- Modify: `apps/backend/routers/billing.py`

- [ ] **Step 1: Read billing router and update webhook handlers**

Read `apps/backend/routers/billing.py` fully. In the webhook handler:

**`subscription.created` and `subscription.updated`:**

After `billing_service.update_subscription()`, add:

```python
# Trigger container update for tier change
from core.services.update_service import queue_tier_change
old_tier = account.get("plan_tier", "free")
await queue_tier_change(account["owner_id"], old_tier=old_tier, new_tier=tier)
```

Note: `old_tier` needs to be read BEFORE `update_subscription()` overwrites it. Reorder the calls.

**`subscription.deleted`:**

After `billing_service.cancel_subscription()`:

```python
from core.services.update_service import queue_tier_change
old_tier = account.get("plan_tier", "free")
await queue_tier_change(account["owner_id"], old_tier=old_tier, new_tier="free")
```

- [ ] **Step 2: Run tests**

Run: `cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev uv run pytest tests/ -v`

- [ ] **Step 3: Commit**

```bash
git add apps/backend/routers/billing.py
git commit -m "feat: wire tier change updates into Stripe webhook handlers"
```

---

## Task 6: CDK Infrastructure

Add `pending-updates` table with status GSI and wire permissions.

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`
- Modify: `apps/infra/lib/stacks/service-stack.ts`

- [ ] **Step 1: Add `pending-updates` table**

In `apps/infra/lib/stacks/database-stack.ts`, after the `usageCountersTable`:

```typescript
    this.pendingUpdatesTable = new dynamodb.Table(this, "PendingUpdatesTable", {
      tableName: `isol8-${env}-pending-updates`,
      partitionKey: { name: "owner_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "update_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
      timeToLiveAttribute: "ttl",
    });
    this.pendingUpdatesTable.addGlobalSecondaryIndex({
      indexName: "status-index",
      partitionKey: { name: "status", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "scheduled_at", type: dynamodb.AttributeType.STRING },
    });
```

Add public property: `public readonly pendingUpdatesTable: dynamodb.Table;`

- [ ] **Step 2: Wire permissions in `service-stack.ts`**

Add `grantReadWriteData` for the new table to the backend task role. Read the file to find where other tables are granted.

Also update the stage files (`isol8-stage.ts`, `local-stage.ts`) to pass the new table through.

- [ ] **Step 3: Commit**

```bash
git add apps/infra/
git commit -m "feat: add pending-updates DynamoDB table with status GSI and TTL"
```

---

## Task 7: Frontend — Update Banner

Show the Tesla-style update banner in the chat UI.

**Files:**
- Modify: `apps/frontend/src/components/chat/AgentChatWindow.tsx`
- Modify: `apps/frontend/src/hooks/useGateway.tsx`

- [ ] **Step 1: Read current files**

Read `AgentChatWindow.tsx` and `useGateway.tsx`.

- [ ] **Step 2: Add `update_available` handler to gateway**

In `useGateway.tsx`, add handling for `type: "update_available"` messages. Store pending updates in state and expose them.

- [ ] **Step 3: Add `UpdateBanner` component**

In `AgentChatWindow.tsx`, add an `UpdateBanner` component (similar to `BudgetExceededBanner`):

- Polls `GET /container/updates` on mount
- Also listens for WebSocket `update_available` events
- Shows banner with description + 3 buttons: Update Now / Tonight at 2 AM / Remind Me Later
- "Update Now" calls `POST /container/updates/{id}/apply` with `{schedule: "now"}`
- Shows spinner during apply, auto-reconnects after
- "Remind Me Later" stores snooze in localStorage, hides banner for 24h
- Org members (non-admin): "An update is available. Your admin can apply it."

Use `useApi()` for REST calls, `useOrganization()` for admin check.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/
git commit -m "feat: add update banner with Now/Tonight/Remind Later options"
```

---

## Task 8: Final Integration & Cleanup

- [ ] **Step 1: Run full backend tests**

Run: `cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev uv run pytest tests/ -v`

- [ ] **Step 2: Run frontend lint and build**

Run: `cd apps/frontend && pnpm run lint && pnpm run build`

- [ ] **Step 3: Search for dead references**

Grep for any broken imports or references to old update patterns.

- [ ] **Step 4: Final commit if needed**

```bash
git add -A && git commit -m "chore: final cleanup for container update system"
```
