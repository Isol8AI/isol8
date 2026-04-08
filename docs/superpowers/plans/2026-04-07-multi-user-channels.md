# Multi-user channels implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Telegram, Discord, and Slack channels work for multi-member organizations on Isol8 running OpenClaw 2026.4.5 — with per-agent multi-bot support, self-service member identity linking via paste-the-pairing-code, and per-member billing for channel-driven traffic.

**Architecture:** Frontend wizards drive config writes through a new `PATCH /api/v1/config` REST endpoint that wraps the existing `patch_openclaw_config` EFS writer (replacing the frontend's direct use of OpenClaw's `config.patch` RPC). A new `channel_link_service` reads OpenClaw's pairing file from EFS to extract platform user IDs and stores `(owner, provider, agent, peer) → clerk_member_id` rows in a new `channel-links` DynamoDB table. Billing switches from the webchat-only `chat.final` trigger to `agent` events with `stream:"lifecycle", phase:"end"` — which OpenClaw broadcasts unconditionally for all runs (webchat and channel) — and uses a new session-key parser to resolve per-member attribution via the channel-links table.

**Tech Stack:** Python 3.12 + FastAPI + pytest + moto + boto3 (DynamoDB) on the backend; Next.js 16 + React 19 + TypeScript + Tailwind + SWR + Playwright on the frontend; CDK 2.x (TypeScript) for infrastructure. Existing patterns: repositories in `core/repositories/` return plain dicts, routers in `routers/` use Pydantic models for requests only, services in `core/services/` orchestrate repo + external calls, config writes on EFS use `fcntl.lockf` exclusive locking.

**Spec:** `docs/superpowers/specs/2026-04-07-multi-user-channels-design.md` (commit `71f7cbe` on branch `spec/multi-user-channels`). Read the spec before starting — it's the source of truth for every design choice.

**Verification reference:** OpenClaw 4.5 source is cloned at `/Users/prasiddhaparthsarthy/Desktop/openclaw`. When a task cites an OpenClaw line, you can open the file at that path to verify.

---

## Prerequisites

- Working directory is an Isol8 git worktree on a feature branch off `spec/multi-user-channels`.
- Backend virtualenv is set up (`cd apps/backend && uv sync`).
- Frontend dependencies installed (`pnpm install` at the repo root).
- Moto (DynamoDB mock) is already a dev dependency of the backend (verify: `uv run python -c "import moto; print(moto.__version__)"`).
- You have access to a real Telegram BotFather bot token for manual testing at the end (production or sandbox bot, doesn't matter — you just need a working token).

## Execution notes

- **Run all tests from each phase before committing that phase's final task.** The plan assumes green tests at each phase boundary.
- **Never batch unrelated changes into one commit.** Each task has its own commit message.
- **Don't modify OpenClaw.** If a task appears to require an OpenClaw source change, stop and ask — something is wrong.
- **Code style:** Python uses double quotes, type hints on public functions, and `async def` for any function that touches DynamoDB or EFS. Frontend uses TypeScript strict mode, Tailwind utility classes (no CSS modules), and SWR for GET requests.
- **Testing philosophy:** One assertion per behavior where possible. No `sleep()` in tests. Mock external I/O (EFS, DynamoDB via moto, RPC calls) but use real in-memory dicts for intermediate state.
- **Commit messages:** `area(scope): short imperative sentence` (e.g., `feat(backend): add append_to_openclaw_config_list helper`). Append the Claude Co-Authored-By trailer on every commit: `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`.

---

## File structure

### New backend files

```
apps/backend/
  core/
    repositories/
      channel_link_repo.py        # DynamoDB CRUD for channel-links table
    services/
      channel_link_service.py     # Link flow orchestration (read EFS pairing file → allowFrom + DDB)
  routers/
    config.py                     # PATCH /api/v1/config (wraps patch_openclaw_config)
  tests/
    unit/
      gateway/
        test_session_key_parser.py
        test_lifecycle_billing.py
      repositories/
        test_channel_link_repo.py
      routers/
        test_config_router.py
        test_channels_link_router.py
      services/
        test_channel_link_service.py
```

### Modified backend files

```
apps/backend/
  core/
    containers/
      config.py                   # set session.dmScope, drop channels.whatsapp from scaffold
      ecs_manager.py              # extend delete_user_service to sweep channel_links
    gateway/
      connection_pool.py          # new _parse_session_key, _resolve_member_from_session,
                                  # lifecycle/end branch, remove chat.final billing call
    services/
      config_patcher.py           # add append/remove/delete helpers
  routers/
    channels.py                   # add link endpoints, remove WhatsApp
    webhooks.py                   # extend Clerk user.deleted → sweep channel_links
  main.py                         # register routers/config.py
  tests/
    unit/
      services/
        test_config_patcher.py    # extend with tests for the new helpers
```

### New frontend files

```
apps/frontend/
  src/
    components/
      channels/
        BotSetupWizard.tsx        # shared wizard: mode "create" or "link-only"
      control/
        panels/
          AgentChannelsSection.tsx    # per-agent channels admin section
      settings/
        MyChannelsSection.tsx     # settings page section for identity linking
  tests/
    unit/
      components/
        BotSetupWizard.test.tsx
        AgentChannelsSection.test.tsx
        MyChannelsSection.test.tsx
```

### Modified frontend files

```
apps/frontend/
  src/
    app/
      settings/
        page.tsx                  # render <MyChannelsSection />
    components/
      chat/
        ProvisioningStepper.tsx   # use <BotSetupWizard /> for channel onboarding step
      control/
        ControlPanelRouter.tsx    # remove ChannelsPanel route
        ControlSidebar.tsx        # remove Channels nav item
        panels/
          AgentsPanel.tsx         # render <AgentChannelsSection /> in agent detail view
    lib/
      api.ts                      # add patchConfig helper
```

### Deleted files

```
apps/frontend/src/components/control/panels/ChannelsPanel.tsx
apps/frontend/src/components/chat/ChannelCards.tsx
apps/backend/core/services/__pycache__/usage_poller.cpython-312.pyc
```

### Infrastructure

```
apps/infra/lib/stacks/database-stack.ts   # add channelLinksTable with by-member GSI
```

---

## Phase overview

| Phase | Summary | Tasks |
|---|---|---|
| **A** | Config patcher helpers (append/remove/delete list, delete path) | A1, A2, A3 |
| **B** | `channel-links` DynamoDB table + repository | B1, B2, B3 |
| **C** | `channel_link_service` + pairing file reader | C1, C2 |
| **D** | `PATCH /api/v1/config` router | D1 |
| **E** | Channels router: add link endpoints, remove WhatsApp | E1, E2, E3 |
| **F** | Billing: session key parser + lifecycle/end trigger | F1, F2, F3 |
| **G** | Orphan sweep hooks (webhooks + ecs_manager) | G1, G2 |
| **H** | Initial openclaw.json defaults (dmScope, drop WhatsApp) | H1 |
| **I** | `BotSetupWizard` component (shell + create mode, error paths, Slack branch) | I1, I2, I3 |
| **J** | `AgentChannelsSection` component | J1 |
| **K** | `MyChannelsSection` component | K1 |
| **L** | Integration wiring (AgentsPanel, settings, onboarding) | L1, L2, L3 |
| **M** | Migrate all `config.patch` RPC callers to REST | M1 |
| **N** | Delete legacy ChannelsPanel, ChannelCards, stale `.pyc` | N1 |

---

## Phase A — Config patcher helpers

**Why first:** Every other backend phase depends on these three helpers. They're small, pure, and testable in isolation. Nailing them first de-risks everything downstream.

**What exists today:** `apps/backend/core/services/config_patcher.py` has one public function: `patch_openclaw_config(owner_id, patch: dict)` — does a locked read-modify-write with `_deep_merge`. The `_deep_merge` function REPLACES non-dict values (including lists), which is why we need new helpers for list append/remove/path-delete.

### Task A1: Add `append_to_openclaw_config_list` helper

**Files:**
- Modify: `apps/backend/core/services/config_patcher.py`
- Test: `apps/backend/tests/unit/services/test_config_patcher.py`

- [ ] **Step 1: Write the failing tests**

Add these tests at the bottom of `apps/backend/tests/unit/services/test_config_patcher.py` (if the file has no existing tests, create it with the imports below plus the tests):

```python
import json
import os
import tempfile
from unittest.mock import patch

import pytest

from core.services.config_patcher import (
    append_to_openclaw_config_list,
    ConfigPatchError,
)


@pytest.fixture
def tmp_efs_with_config(monkeypatch):
    """Write a minimal openclaw.json to a tmp 'EFS' dir and point the patcher at it."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr("core.services.config_patcher._efs_mount_path", d)
        owner_id = "user_test"
        owner_dir = os.path.join(d, owner_id)
        os.makedirs(owner_dir)
        config_path = os.path.join(owner_dir, "openclaw.json")
        with open(config_path, "w") as f:
            json.dump({"channels": {"telegram": {"accounts": {"main": {"allowFrom": ["111"]}}}}}, f)
        yield d, owner_id, config_path


@pytest.mark.asyncio
async def test_append_to_list_appends_to_existing(tmp_efs_with_config):
    _, owner_id, config_path = tmp_efs_with_config
    await append_to_openclaw_config_list(
        owner_id,
        ["channels", "telegram", "accounts", "main", "allowFrom"],
        "222",
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["telegram"]["accounts"]["main"]["allowFrom"] == ["111", "222"]


@pytest.mark.asyncio
async def test_append_to_list_creates_path_when_missing(tmp_efs_with_config):
    _, owner_id, config_path = tmp_efs_with_config
    await append_to_openclaw_config_list(
        owner_id,
        ["channels", "discord", "accounts", "sales", "allowFrom"],
        "999",
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["discord"]["accounts"]["sales"]["allowFrom"] == ["999"]


@pytest.mark.asyncio
async def test_append_to_list_dedups(tmp_efs_with_config):
    _, owner_id, config_path = tmp_efs_with_config
    await append_to_openclaw_config_list(
        owner_id,
        ["channels", "telegram", "accounts", "main", "allowFrom"],
        "111",  # already present
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["telegram"]["accounts"]["main"]["allowFrom"] == ["111"]


@pytest.mark.asyncio
async def test_append_to_list_missing_config_file_raises(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr("core.services.config_patcher._efs_mount_path", d)
        with pytest.raises(ConfigPatchError):
            await append_to_openclaw_config_list(
                "user_doesnt_exist",
                ["channels", "telegram", "accounts", "main", "allowFrom"],
                "123",
            )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_config_patcher.py -v -k "append_to_list"
```

Expected: FAIL with `ImportError: cannot import name 'append_to_openclaw_config_list'`

- [ ] **Step 3: Implement the helper**

Add this function at the bottom of `apps/backend/core/services/config_patcher.py`:

```python
async def append_to_openclaw_config_list(
    owner_id: str,
    path: list[str],
    value,
) -> None:
    """Append `value` to the list at `path` in the owner's openclaw.json.

    Semantics:
    - If `path` doesn't exist, create nested dicts as needed and initialize the
      list with `[value]`.
    - If the list already contains `value`, this is a no-op (dedup).
    - Acquires the same fcntl.lockf exclusive lock on openclaw.json as
      `patch_openclaw_config` to serialize concurrent writes.
    """
    if not path:
        raise ConfigPatchError("path must not be empty")

    config_dir = os.path.join(_efs_mount_path, owner_id)
    config_path = os.path.join(config_dir, "openclaw.json")
    backup_path = os.path.join(config_dir, "openclaw.json.bak")

    if not os.path.exists(config_path):
        raise ConfigPatchError(f"Config not found for owner {owner_id}")

    def _do_append():
        lock_fd = None
        try:
            lock_fd = open(config_path, "r+")
            fcntl.lockf(lock_fd, fcntl.LOCK_EX)

            with open(config_path, "r") as f:
                current = json.load(f)

            shutil.copy2(config_path, backup_path)

            # Walk/create the nested path, stopping one short of the leaf
            cursor = current
            for segment in path[:-1]:
                if segment not in cursor or not isinstance(cursor[segment], dict):
                    cursor[segment] = {}
                cursor = cursor[segment]

            leaf_key = path[-1]
            existing = cursor.get(leaf_key)
            if not isinstance(existing, list):
                cursor[leaf_key] = [value]
            elif value not in existing:
                existing.append(value)
            # else: already present, no-op

            json.dumps(current)  # validate serializable

            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(current, f, indent=2)
                if os.getuid() == 0:
                    os.chown(tmp_path, 1000, 1000)
                os.rename(tmp_path, config_path)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info(
                "Appended to openclaw.json list for owner %s: path=%s value=%r",
                owner_id, path, value,
            )
        finally:
            if lock_fd:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    await asyncio.to_thread(_do_append)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_config_patcher.py -v -k "append_to_list"
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_patcher.py apps/backend/tests/unit/services/test_config_patcher.py
git commit -m "$(cat <<'EOF'
feat(backend): add append_to_openclaw_config_list helper

Locked read-modify-write append helper for nested JSON lists in
openclaw.json. Creates intermediate dicts on demand, dedups on
append. Reuses the fcntl.lockf pattern from patch_openclaw_config.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task A2: Add `remove_from_openclaw_config_list` helper

**Files:**
- Modify: `apps/backend/core/services/config_patcher.py`
- Test: `apps/backend/tests/unit/services/test_config_patcher.py`

- [ ] **Step 1: Write the failing tests**

Append these tests to `apps/backend/tests/unit/services/test_config_patcher.py`:

```python
from core.services.config_patcher import remove_from_openclaw_config_list


@pytest.fixture
def tmp_efs_with_bindings(monkeypatch):
    """Minimal openclaw.json with a bindings array for predicate-removal testing."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr("core.services.config_patcher._efs_mount_path", d)
        owner_id = "user_test"
        owner_dir = os.path.join(d, owner_id)
        os.makedirs(owner_dir)
        config_path = os.path.join(owner_dir, "openclaw.json")
        with open(config_path, "w") as f:
            json.dump({
                "channels": {"telegram": {"accounts": {"main": {"allowFrom": ["111", "222", "333"]}}}},
                "bindings": [
                    {"match": {"channel": "telegram", "accountId": "main"}, "agentId": "main"},
                    {"match": {"channel": "telegram", "accountId": "sales"}, "agentId": "sales"},
                    {"match": {"channel": "discord", "accountId": "main"}, "agentId": "main"},
                ],
            }, f)
        yield d, owner_id, config_path


@pytest.mark.asyncio
async def test_remove_from_list_value_match(tmp_efs_with_bindings):
    _, owner_id, config_path = tmp_efs_with_bindings
    await remove_from_openclaw_config_list(
        owner_id,
        ["channels", "telegram", "accounts", "main", "allowFrom"],
        predicate=lambda v: v == "222",
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["telegram"]["accounts"]["main"]["allowFrom"] == ["111", "333"]


@pytest.mark.asyncio
async def test_remove_from_list_predicate_match_dict(tmp_efs_with_bindings):
    _, owner_id, config_path = tmp_efs_with_bindings
    await remove_from_openclaw_config_list(
        owner_id,
        ["bindings"],
        predicate=lambda b: (
            b.get("match", {}).get("channel") == "telegram"
            and b.get("match", {}).get("accountId") == "sales"
        ),
    )
    with open(config_path) as f:
        result = json.load(f)
    assert len(result["bindings"]) == 2
    assert all(b["match"]["accountId"] != "sales" for b in result["bindings"])


@pytest.mark.asyncio
async def test_remove_from_list_no_match_is_noop(tmp_efs_with_bindings):
    _, owner_id, config_path = tmp_efs_with_bindings
    await remove_from_openclaw_config_list(
        owner_id,
        ["channels", "telegram", "accounts", "main", "allowFrom"],
        predicate=lambda v: v == "nonexistent",
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["telegram"]["accounts"]["main"]["allowFrom"] == ["111", "222", "333"]


@pytest.mark.asyncio
async def test_remove_from_list_missing_path_is_noop(tmp_efs_with_bindings):
    _, owner_id, config_path = tmp_efs_with_bindings
    await remove_from_openclaw_config_list(
        owner_id,
        ["channels", "slack", "accounts", "main", "allowFrom"],  # doesn't exist
        predicate=lambda v: True,
    )
    with open(config_path) as f:
        result = json.load(f)
    # Original bindings untouched
    assert len(result["bindings"]) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_config_patcher.py -v -k "remove_from_list"
```

Expected: FAIL with `ImportError: cannot import name 'remove_from_openclaw_config_list'`

- [ ] **Step 3: Implement the helper**

Add this function to `apps/backend/core/services/config_patcher.py` (after `append_to_openclaw_config_list`):

```python
from typing import Callable, Any


async def remove_from_openclaw_config_list(
    owner_id: str,
    path: list[str],
    predicate: Callable[[Any], bool],
) -> None:
    """Remove entries from the list at `path` where `predicate(entry)` returns True.

    Semantics:
    - If `path` doesn't exist or isn't a list, no-op (no error).
    - Predicate-match approach supports both string matching (e.g. allowFrom)
      and structural matching (e.g. bindings dict entries).
    - Acquires the same fcntl.lockf exclusive lock as append_to_openclaw_config_list.
    """
    if not path:
        raise ConfigPatchError("path must not be empty")

    config_dir = os.path.join(_efs_mount_path, owner_id)
    config_path = os.path.join(config_dir, "openclaw.json")
    backup_path = os.path.join(config_dir, "openclaw.json.bak")

    if not os.path.exists(config_path):
        raise ConfigPatchError(f"Config not found for owner {owner_id}")

    def _do_remove():
        lock_fd = None
        try:
            lock_fd = open(config_path, "r+")
            fcntl.lockf(lock_fd, fcntl.LOCK_EX)

            with open(config_path, "r") as f:
                current = json.load(f)

            # Walk to the leaf
            cursor = current
            for segment in path[:-1]:
                if segment not in cursor or not isinstance(cursor[segment], dict):
                    return  # missing path, no-op
                cursor = cursor[segment]

            leaf_key = path[-1]
            existing = cursor.get(leaf_key)
            if not isinstance(existing, list):
                return  # not a list or missing, no-op

            filtered = [item for item in existing if not predicate(item)]
            if len(filtered) == len(existing):
                return  # nothing removed, skip the write

            cursor[leaf_key] = filtered

            shutil.copy2(config_path, backup_path)
            json.dumps(current)  # validate serializable

            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(current, f, indent=2)
                if os.getuid() == 0:
                    os.chown(tmp_path, 1000, 1000)
                os.rename(tmp_path, config_path)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info(
                "Removed from openclaw.json list for owner %s: path=%s removed=%d",
                owner_id, path, len(existing) - len(filtered),
            )
        finally:
            if lock_fd:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    await asyncio.to_thread(_do_remove)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_config_patcher.py -v -k "remove_from_list"
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_patcher.py apps/backend/tests/unit/services/test_config_patcher.py
git commit -m "$(cat <<'EOF'
feat(backend): add remove_from_openclaw_config_list helper

Predicate-based list removal for nested openclaw.json arrays. Supports
both string equality (allowFrom entries) and structural matching
(bindings dicts). No-op for missing paths.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task A3: Add `delete_openclaw_config_path` helper

**Files:**
- Modify: `apps/backend/core/services/config_patcher.py`
- Test: `apps/backend/tests/unit/services/test_config_patcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/unit/services/test_config_patcher.py`:

```python
from core.services.config_patcher import delete_openclaw_config_path


@pytest.fixture
def tmp_efs_with_multi_accounts(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr("core.services.config_patcher._efs_mount_path", d)
        owner_id = "user_test"
        owner_dir = os.path.join(d, owner_id)
        os.makedirs(owner_dir)
        config_path = os.path.join(owner_dir, "openclaw.json")
        with open(config_path, "w") as f:
            json.dump({
                "channels": {
                    "telegram": {
                        "accounts": {
                            "main": {"botToken": "aaa", "allowFrom": ["111"]},
                            "sales": {"botToken": "bbb", "allowFrom": ["222"]},
                        },
                    },
                },
            }, f)
        yield d, owner_id, config_path


@pytest.mark.asyncio
async def test_delete_path_removes_nested_key(tmp_efs_with_multi_accounts):
    _, owner_id, config_path = tmp_efs_with_multi_accounts
    await delete_openclaw_config_path(
        owner_id,
        ["channels", "telegram", "accounts", "sales"],
    )
    with open(config_path) as f:
        result = json.load(f)
    # sales removed, main preserved
    assert "sales" not in result["channels"]["telegram"]["accounts"]
    assert "main" in result["channels"]["telegram"]["accounts"]
    assert result["channels"]["telegram"]["accounts"]["main"]["botToken"] == "aaa"


@pytest.mark.asyncio
async def test_delete_path_leaves_empty_parent_as_empty_dict(tmp_efs_with_multi_accounts):
    _, owner_id, config_path = tmp_efs_with_multi_accounts
    await delete_openclaw_config_path(owner_id, ["channels", "telegram", "accounts", "main"])
    await delete_openclaw_config_path(owner_id, ["channels", "telegram", "accounts", "sales"])
    with open(config_path) as f:
        result = json.load(f)
    # The parent accounts dict is left as {} rather than being pruned
    assert result["channels"]["telegram"]["accounts"] == {}


@pytest.mark.asyncio
async def test_delete_path_missing_key_is_noop(tmp_efs_with_multi_accounts):
    _, owner_id, config_path = tmp_efs_with_multi_accounts
    await delete_openclaw_config_path(
        owner_id,
        ["channels", "telegram", "accounts", "does_not_exist"],
    )
    with open(config_path) as f:
        result = json.load(f)
    # Nothing removed
    assert "main" in result["channels"]["telegram"]["accounts"]
    assert "sales" in result["channels"]["telegram"]["accounts"]


@pytest.mark.asyncio
async def test_delete_path_missing_intermediate_is_noop(tmp_efs_with_multi_accounts):
    _, owner_id, config_path = tmp_efs_with_multi_accounts
    await delete_openclaw_config_path(
        owner_id,
        ["channels", "slack", "accounts", "main"],  # slack branch doesn't exist
    )
    with open(config_path) as f:
        result = json.load(f)
    assert "main" in result["channels"]["telegram"]["accounts"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_config_patcher.py -v -k "delete_path"
```

Expected: FAIL with `ImportError: cannot import name 'delete_openclaw_config_path'`

- [ ] **Step 3: Implement the helper**

Add to `apps/backend/core/services/config_patcher.py`:

```python
async def delete_openclaw_config_path(
    owner_id: str,
    path: list[str],
) -> None:
    """Remove the key at `path` from the owner's openclaw.json entirely.

    Semantics:
    - If any intermediate path segment is missing, no-op (no error).
    - If the leaf key doesn't exist, no-op.
    - If the parent dict is empty after removal, it is left as `{}` rather
      than being pruned recursively. OpenClaw treats empty dicts the same
      as missing keys for `channels.*.accounts`.
    - Acquires the same fcntl.lockf exclusive lock as the other helpers.
    """
    if not path:
        raise ConfigPatchError("path must not be empty")

    config_dir = os.path.join(_efs_mount_path, owner_id)
    config_path = os.path.join(config_dir, "openclaw.json")
    backup_path = os.path.join(config_dir, "openclaw.json.bak")

    if not os.path.exists(config_path):
        raise ConfigPatchError(f"Config not found for owner {owner_id}")

    def _do_delete():
        lock_fd = None
        try:
            lock_fd = open(config_path, "r+")
            fcntl.lockf(lock_fd, fcntl.LOCK_EX)

            with open(config_path, "r") as f:
                current = json.load(f)

            # Walk to the parent of the leaf
            cursor = current
            for segment in path[:-1]:
                if segment not in cursor or not isinstance(cursor[segment], dict):
                    return  # missing intermediate, no-op
                cursor = cursor[segment]

            leaf_key = path[-1]
            if leaf_key not in cursor:
                return  # already absent, no-op

            shutil.copy2(config_path, backup_path)
            del cursor[leaf_key]

            json.dumps(current)  # validate serializable

            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(current, f, indent=2)
                if os.getuid() == 0:
                    os.chown(tmp_path, 1000, 1000)
                os.rename(tmp_path, config_path)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info(
                "Deleted openclaw.json path for owner %s: path=%s",
                owner_id, path,
            )
        finally:
            if lock_fd:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    await asyncio.to_thread(_do_delete)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_config_patcher.py -v
```

Expected: all 12 tests in this file PASS (4 append + 4 remove + 4 delete).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_patcher.py apps/backend/tests/unit/services/test_config_patcher.py
git commit -m "$(cat <<'EOF'
feat(backend): add delete_openclaw_config_path helper

Removes a key at a nested JSON path from openclaw.json. Missing path
is a no-op. Empty parent dicts are left as {} rather than pruned
recursively. Used by the bot-deletion flow to remove channels.<provider>.accounts.<agent_id>.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B — `channel-links` DynamoDB table + repository

**Why now:** The channel link service (Phase C) writes rows here. The billing parser (Phase F) reads rows here. Both need the table to exist and the repo functions to be in place before they can be wired up.

**What exists today:** `apps/backend/core/repositories/` has one repo per table (`container_repo.py`, `billing_repo.py`, `user_repo.py`, etc.), all following the same pattern: `get_table("short_name")` from `core/dynamodb.py`, async functions using `run_in_thread`. `apps/infra/lib/stacks/database-stack.ts` declares every table. We mirror both patterns.

### Task B1: Add `channel-links` table to CDK database stack

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`

- [ ] **Step 1: Read the existing table definitions to match the pattern**

```bash
sed -n '40,75p' apps/infra/lib/stacks/database-stack.ts
```

Study the existing `containersTable` and `billingTable` blocks — we'll follow the same shape (PAY_PER_REQUEST, point-in-time recovery, KMS encryption, env-gated removal policy).

- [ ] **Step 2: Add the public field declaration**

Edit `apps/infra/lib/stacks/database-stack.ts`. Find the `public readonly` block at the top of the class:

```typescript
  public readonly usersTable: dynamodb.Table;
  public readonly containersTable: dynamodb.Table;
  public readonly billingTable: dynamodb.Table;
  public readonly apiKeysTable: dynamodb.Table;
  public readonly usageCountersTable: dynamodb.Table;
  public readonly pendingUpdatesTable: dynamodb.Table;
```

Add one more line after `pendingUpdatesTable`:

```typescript
  public readonly channelLinksTable: dynamodb.Table;
```

- [ ] **Step 3: Add the table definition**

In the same file, after the `pendingUpdatesTable` block (after the GSI `addGlobalSecondaryIndex` call with the `status-index` on pendingUpdates), insert:

```typescript
    this.channelLinksTable = new dynamodb.Table(this, "ChannelLinksTable", {
      tableName: `isol8-${env}-channel-links`,
      partitionKey: { name: "owner_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });
    this.channelLinksTable.addGlobalSecondaryIndex({
      indexName: "by-member",
      partitionKey: { name: "member_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "owner_provider_agent", type: dynamodb.AttributeType.STRING },
    });
```

Note the `sk` attribute holds `"provider#agent_id#peer_id"` (the composite sort key from the spec), and the GSI sort key is `owner_id#provider#agent_id` stored denormalized as `owner_provider_agent`. Both composite keys are opaque strings the repo layer will construct.

- [ ] **Step 4: Verify the CDK synth still works**

```bash
cd apps/infra && npx cdk synth isol8-dev-database 2>&1 | tail -20
```

Expected: `Successfully synthesized to ...` with no errors. If you see a resource change diff, that's expected (new table + GSI).

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts
git commit -m "$(cat <<'EOF'
feat(infra): add channel-links DynamoDB table

New table for per-member channel identity links. PK=owner_id, SK is a
composite provider#agent_id#peer_id. by-member GSI for Settings page
lookups ("show me all my links across orgs").

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task B2: Implement `channel_link_repo` (put, get, query, delete)

**Files:**
- Create: `apps/backend/core/repositories/channel_link_repo.py`
- Test: `apps/backend/tests/unit/repositories/test_channel_link_repo.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/repositories/test_channel_link_repo.py`:

```python
import os

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def dynamodb_setup(monkeypatch):
    """Create the channel-links table in moto and point the repo at it."""
    monkeypatch.setenv("DYNAMODB_TABLE_PREFIX", "test-")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    with mock_aws():
        # Reset the cached resource/table prefix so the fixture's env vars take effect
        import importlib
        import core.dynamodb
        importlib.reload(core.dynamodb)

        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-channel-links",
            KeySchema=[
                {"AttributeName": "owner_id", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "owner_id", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "member_id", "AttributeType": "S"},
                {"AttributeName": "owner_provider_agent", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by-member",
                    "KeySchema": [
                        {"AttributeName": "member_id", "KeyType": "HASH"},
                        {"AttributeName": "owner_provider_agent", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName="test-channel-links")

        import core.repositories.channel_link_repo  # noqa: F401

        yield


@pytest.mark.asyncio
async def test_put_and_get_by_peer(dynamodb_setup):
    from core.repositories import channel_link_repo

    await channel_link_repo.put(
        owner_id="org_1",
        provider="telegram",
        agent_id="sales",
        peer_id="99999",
        member_id="user_bob",
        linked_via="settings",
    )
    link = await channel_link_repo.get_by_peer(
        owner_id="org_1",
        provider="telegram",
        agent_id="sales",
        peer_id="99999",
    )
    assert link is not None
    assert link["member_id"] == "user_bob"
    assert link["linked_via"] == "settings"
    assert link["provider"] == "telegram"
    assert link["agent_id"] == "sales"
    assert link["peer_id"] == "99999"


@pytest.mark.asyncio
async def test_get_by_peer_miss_returns_none(dynamodb_setup):
    from core.repositories import channel_link_repo
    result = await channel_link_repo.get_by_peer(
        owner_id="org_1", provider="telegram", agent_id="sales", peer_id="00000",
    )
    assert result is None


@pytest.mark.asyncio
async def test_query_by_member_across_orgs(dynamodb_setup):
    from core.repositories import channel_link_repo
    await channel_link_repo.put(
        owner_id="org_1", provider="telegram", agent_id="main", peer_id="111",
        member_id="user_bob", linked_via="wizard",
    )
    await channel_link_repo.put(
        owner_id="org_2", provider="discord", agent_id="main", peer_id="222",
        member_id="user_bob", linked_via="settings",
    )
    await channel_link_repo.put(
        owner_id="org_1", provider="telegram", agent_id="main", peer_id="333",
        member_id="user_alice", linked_via="wizard",
    )

    bob_links = await channel_link_repo.query_by_member("user_bob")
    assert len(bob_links) == 2
    orgs = {l["owner_id"] for l in bob_links}
    assert orgs == {"org_1", "org_2"}


@pytest.mark.asyncio
async def test_delete_link(dynamodb_setup):
    from core.repositories import channel_link_repo
    await channel_link_repo.put(
        owner_id="org_1", provider="telegram", agent_id="sales", peer_id="99999",
        member_id="user_bob", linked_via="settings",
    )
    await channel_link_repo.delete(
        owner_id="org_1", provider="telegram", agent_id="sales", peer_id="99999",
    )
    result = await channel_link_repo.get_by_peer(
        owner_id="org_1", provider="telegram", agent_id="sales", peer_id="99999",
    )
    assert result is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/repositories/test_channel_link_repo.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.repositories.channel_link_repo'`

- [ ] **Step 3: Implement the repo**

Create `apps/backend/core/repositories/channel_link_repo.py`:

```python
"""Channel link repository — DynamoDB operations for the channel-links table.

Stores per-member identity links to per-agent channel bots. Primary key is
(owner_id, sk="provider#agent_id#peer_id"). The by-member GSI supports
querying all links for one Clerk member across all their orgs.
"""

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("channel-links")


def _sk(provider: str, agent_id: str, peer_id: str) -> str:
    return f"{provider}#{agent_id}#{peer_id}"


def _owner_provider_agent(owner_id: str, provider: str, agent_id: str) -> str:
    return f"{owner_id}#{provider}#{agent_id}"


async def put(
    *,
    owner_id: str,
    provider: str,
    agent_id: str,
    peer_id: str,
    member_id: str,
    linked_via: str,
) -> dict:
    """Create or overwrite a channel link row."""
    item = {
        "owner_id": owner_id,
        "sk": _sk(provider, agent_id, peer_id),
        "provider": provider,
        "agent_id": agent_id,
        "peer_id": peer_id,
        "member_id": member_id,
        "linked_via": linked_via,
        "linked_at": utc_now_iso(),
        # Denormalized composite for the by-member GSI sort key
        "owner_provider_agent": _owner_provider_agent(owner_id, provider, agent_id),
    }
    table = _get_table()
    await run_in_thread(table.put_item, Item=item)
    return item


async def get_by_peer(
    *,
    owner_id: str,
    provider: str,
    agent_id: str,
    peer_id: str,
) -> dict | None:
    """Look up a single link row by its full primary key."""
    table = _get_table()
    response = await run_in_thread(
        table.get_item,
        Key={"owner_id": owner_id, "sk": _sk(provider, agent_id, peer_id)},
    )
    return response.get("Item")


async def query_by_member(member_id: str) -> list[dict]:
    """Return all link rows for a Clerk member across all orgs.

    Uses the by-member GSI.
    """
    table = _get_table()
    response = await run_in_thread(
        table.query,
        IndexName="by-member",
        KeyConditionExpression=Key("member_id").eq(member_id),
    )
    return response.get("Items", [])


async def delete(
    *,
    owner_id: str,
    provider: str,
    agent_id: str,
    peer_id: str,
) -> None:
    """Delete a single link row."""
    table = _get_table()
    await run_in_thread(
        table.delete_item,
        Key={"owner_id": owner_id, "sk": _sk(provider, agent_id, peer_id)},
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/repositories/test_channel_link_repo.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/repositories/channel_link_repo.py apps/backend/tests/unit/repositories/test_channel_link_repo.py
git commit -m "$(cat <<'EOF'
feat(backend): add channel_link_repo with put/get/query/delete

DynamoDB repo for the channel-links table. PK=owner_id, SK is the
composite provider#agent_id#peer_id. query_by_member uses the by-member
GSI to support Settings page lookups across all orgs a user belongs to.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task B3: Add sweep helpers for cleanup flows

**Files:**
- Modify: `apps/backend/core/repositories/channel_link_repo.py`
- Test: `apps/backend/tests/unit/repositories/test_channel_link_repo.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/unit/repositories/test_channel_link_repo.py`:

```python
@pytest.mark.asyncio
async def test_sweep_by_owner_provider_agent(dynamodb_setup):
    from core.repositories import channel_link_repo
    # Seed: two bots with members linked
    for peer in ["111", "222", "333"]:
        await channel_link_repo.put(
            owner_id="org_1", provider="telegram", agent_id="main", peer_id=peer,
            member_id=f"user_{peer}", linked_via="settings",
        )
    for peer in ["444", "555"]:
        await channel_link_repo.put(
            owner_id="org_1", provider="telegram", agent_id="sales", peer_id=peer,
            member_id=f"user_{peer}", linked_via="settings",
        )

    # Sweep only the main-agent bot
    count = await channel_link_repo.sweep_by_owner_provider_agent(
        owner_id="org_1", provider="telegram", agent_id="main",
    )
    assert count == 3

    # main is gone, sales is intact
    assert await channel_link_repo.get_by_peer(
        owner_id="org_1", provider="telegram", agent_id="main", peer_id="111",
    ) is None
    assert await channel_link_repo.get_by_peer(
        owner_id="org_1", provider="telegram", agent_id="sales", peer_id="444",
    ) is not None


@pytest.mark.asyncio
async def test_sweep_by_owner(dynamodb_setup):
    from core.repositories import channel_link_repo
    # Seed across two orgs
    await channel_link_repo.put(
        owner_id="org_a", provider="telegram", agent_id="main", peer_id="111",
        member_id="user_1", linked_via="settings",
    )
    await channel_link_repo.put(
        owner_id="org_a", provider="discord", agent_id="main", peer_id="222",
        member_id="user_1", linked_via="settings",
    )
    await channel_link_repo.put(
        owner_id="org_b", provider="telegram", agent_id="main", peer_id="333",
        member_id="user_1", linked_via="settings",
    )

    count = await channel_link_repo.sweep_by_owner("org_a")
    assert count == 2

    assert await channel_link_repo.get_by_peer(
        owner_id="org_a", provider="telegram", agent_id="main", peer_id="111",
    ) is None
    # org_b untouched
    assert await channel_link_repo.get_by_peer(
        owner_id="org_b", provider="telegram", agent_id="main", peer_id="333",
    ) is not None


@pytest.mark.asyncio
async def test_sweep_by_member(dynamodb_setup):
    from core.repositories import channel_link_repo
    # Bob is in two orgs
    await channel_link_repo.put(
        owner_id="org_a", provider="telegram", agent_id="main", peer_id="111",
        member_id="user_bob", linked_via="settings",
    )
    await channel_link_repo.put(
        owner_id="org_b", provider="discord", agent_id="main", peer_id="222",
        member_id="user_bob", linked_via="settings",
    )
    # Alice is in one
    await channel_link_repo.put(
        owner_id="org_a", provider="telegram", agent_id="main", peer_id="333",
        member_id="user_alice", linked_via="settings",
    )

    count = await channel_link_repo.sweep_by_member("user_bob")
    assert count == 2

    # Bob's rows gone, Alice untouched
    assert len(await channel_link_repo.query_by_member("user_bob")) == 0
    assert len(await channel_link_repo.query_by_member("user_alice")) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/repositories/test_channel_link_repo.py -v -k "sweep"
```

Expected: FAIL with `AttributeError: module 'core.repositories.channel_link_repo' has no attribute 'sweep_by_owner_provider_agent'`

- [ ] **Step 3: Implement the sweep helpers**

Append to `apps/backend/core/repositories/channel_link_repo.py`:

```python
async def sweep_by_owner_provider_agent(
    *,
    owner_id: str,
    provider: str,
    agent_id: str,
) -> int:
    """Delete all link rows for one bot. Used by bot-delete cleanup.

    Returns the number of rows deleted.
    """
    table = _get_table()
    prefix = f"{provider}#{agent_id}#"
    response = await run_in_thread(
        table.query,
        KeyConditionExpression=Key("owner_id").eq(owner_id) & Key("sk").begins_with(prefix),
    )
    items = response.get("Items", [])
    if not items:
        return 0

    # DynamoDB BatchWriteItem max 25 per batch
    for i in range(0, len(items), 25):
        batch = items[i : i + 25]
        with table.batch_writer() as writer:
            for item in batch:
                await run_in_thread(
                    writer.delete_item,
                    Key={"owner_id": item["owner_id"], "sk": item["sk"]},
                )
    return len(items)


async def sweep_by_owner(owner_id: str) -> int:
    """Delete all link rows for one container. Used by container-delete cleanup.

    Returns the number of rows deleted.
    """
    table = _get_table()
    response = await run_in_thread(
        table.query,
        KeyConditionExpression=Key("owner_id").eq(owner_id),
    )
    items = response.get("Items", [])
    if not items:
        return 0

    for i in range(0, len(items), 25):
        batch = items[i : i + 25]
        with table.batch_writer() as writer:
            for item in batch:
                await run_in_thread(
                    writer.delete_item,
                    Key={"owner_id": item["owner_id"], "sk": item["sk"]},
                )
    return len(items)


async def sweep_by_member(member_id: str) -> int:
    """Delete all link rows for a Clerk member. Used by Clerk user.deleted webhook.

    Queries the by-member GSI, then deletes via the main table keys.
    Returns the number of rows deleted.
    """
    items = await query_by_member(member_id)
    if not items:
        return 0

    table = _get_table()
    for i in range(0, len(items), 25):
        batch = items[i : i + 25]
        with table.batch_writer() as writer:
            for item in batch:
                await run_in_thread(
                    writer.delete_item,
                    Key={"owner_id": item["owner_id"], "sk": item["sk"]},
                )
    return len(items)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/repositories/test_channel_link_repo.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/repositories/channel_link_repo.py apps/backend/tests/unit/repositories/test_channel_link_repo.py
git commit -m "$(cat <<'EOF'
feat(backend): add channel_link_repo sweep helpers

Three cleanup sweeps for orphan rows: by bot (bot-delete), by owner
(container-delete), by member (Clerk user.deleted webhook). All three
use batch_writer with 25-row chunks per DynamoDB limits.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — `channel_link_service` + pairing file reader

**Why now:** Phase B's repo gives us the storage primitive; now we need the orchestrator that reads OpenClaw's pairing file from EFS, finds the matching code, extracts the platform user ID, writes to `allowFrom`, and persists the link row. This is the service layer that the REST router (Phase E) will call.

**What exists today:** Nothing in `core/services/` touches EFS pairing files. The pattern for EFS reads we're matching: `core/containers/config.py`'s read path (reads `openclaw.json` directly from `/mnt/efs/users/<owner_id>/`). For service error classes, see `core/services/config_patcher.py:ConfigPatchError` and `core/services/billing_service.py:BillingServiceError`.

**The pairing file format** (from `openclaw/src/pairing/pairing-store.ts:43-54`):

```json
{
  "version": 1,
  "requests": [
    {
      "id": "12345",              // platform user ID (Telegram numeric, Discord snowflake, etc.)
      "code": "XYZ98765",         // 8-character uppercase code
      "createdAt": "2026-04-07T12:00:00.000Z",
      "lastSeenAt": "2026-04-07T12:00:00.000Z",
      "meta": {}                  // optional
    }
  ]
}
```

Path: `/mnt/efs/users/<owner_id>/.openclaw/credentials/<channel>-pairing.json`. Codes expire after 1 hour (OpenClaw's `pairing-store.ts:175-194` prunes on read, but we can't rely on our read coinciding with a prune, so we check expiry ourselves).

### Task C1: Implement `channel_link_service.complete_link` happy path

**Files:**
- Create: `apps/backend/core/services/channel_link_service.py`
- Test: `apps/backend/tests/unit/services/test_channel_link_service.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/services/test_channel_link_service.py`:

```python
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest


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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_channel_link_service.py::test_complete_link_happy_path -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.services.channel_link_service'`

- [ ] **Step 3: Implement the service**

Create `apps/backend/core/services/channel_link_service.py`:

```python
"""Channel link service — member identity linking flow.

Reads OpenClaw's pairing file from EFS to extract the platform user ID
corresponding to a pairing code, adds the peer to the bot's allowFrom via
the locked EFS writer, and persists the link row in DynamoDB.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from core.config import settings
from core.repositories import channel_link_repo
from core.services.config_patcher import append_to_openclaw_config_list

logger = logging.getLogger(__name__)

_efs_mount_path = settings.EFS_MOUNT_PATH

PAIRING_CODE_TTL = timedelta(hours=1)


class ChannelLinkError(Exception):
    """Base class for channel link service errors."""


class PairingCodeNotFoundError(ChannelLinkError):
    """The pairing code was not found in the EFS pairing file or has expired."""


def _pairing_file_path(owner_id: str, provider: str) -> str:
    return os.path.join(
        _efs_mount_path,
        owner_id,
        ".openclaw",
        "credentials",
        f"{provider}-pairing.json",
    )


def _read_pairing_requests(owner_id: str, provider: str) -> list[dict]:
    """Read the pairing file and return its requests list.

    Returns [] if the file doesn't exist (pairing file is only created on
    first unknown DM). Non-existent is not an error — it means no unknown
    senders have DMed the bot yet.
    """
    path = _pairing_file_path(owner_id, provider)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            store = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "Failed to read pairing file for owner %s provider %s: %s",
            owner_id, provider, e,
        )
        return []
    requests = store.get("requests", [])
    return requests if isinstance(requests, list) else []


def _is_expired(created_at_iso: str) -> bool:
    try:
        created = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - created > PAIRING_CODE_TTL


async def complete_link(
    *,
    owner_id: str,
    provider: str,
    agent_id: str,
    code: str,
    member_id: str,
    linked_via: str = "settings",
) -> dict:
    """Complete the member-linking flow by matching a pairing code.

    Steps:
    1. Read the pairing file for this owner/provider from EFS.
    2. Find the entry with the given code (case-insensitive), unexpired.
    3. Extract the `id` field (the platform user ID).
    4. Append the platform user ID to the bot's allowFrom list.
    5. Write the link row to DynamoDB.

    Returns: {"status": "linked", "peer_id": <platform user id>}

    Raises:
        PairingCodeNotFoundError: if the code is missing or expired.
    """
    requests = _read_pairing_requests(owner_id, provider)
    code_upper = code.strip().upper()

    match = None
    for req in requests:
        req_code = str(req.get("code", "")).strip().upper()
        if req_code != code_upper:
            continue
        created_at = str(req.get("createdAt", ""))
        if _is_expired(created_at):
            continue
        match = req
        break

    if match is None:
        raise PairingCodeNotFoundError(
            f"No pending pairing request for code {code_upper} on {provider}"
        )

    peer_id = str(match.get("id", "")).strip()
    if not peer_id:
        raise PairingCodeNotFoundError(
            f"Pairing entry for code {code_upper} has no platform user id"
        )

    # Write allowFrom entry (dedup-aware append)
    await append_to_openclaw_config_list(
        owner_id,
        ["channels", provider, "accounts", agent_id, "allowFrom"],
        peer_id,
    )

    # Persist the link row
    await channel_link_repo.put(
        owner_id=owner_id,
        provider=provider,
        agent_id=agent_id,
        peer_id=peer_id,
        member_id=member_id,
        linked_via=linked_via,
    )

    logger.info(
        "Linked %s peer %s to member %s on owner %s (agent %s)",
        provider, peer_id, member_id, owner_id, agent_id,
    )

    return {"status": "linked", "peer_id": peer_id}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_channel_link_service.py::test_complete_link_happy_path -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/channel_link_service.py apps/backend/tests/unit/services/test_channel_link_service.py
git commit -m "$(cat <<'EOF'
feat(backend): add channel_link_service happy path

Reads OpenClaw's pairing file from EFS, matches by code, extracts
the platform user id, appends to allowFrom, and persists to DynamoDB.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task C2: Error paths — not found, expired, already linked, peer collision

**Files:**
- Modify: `apps/backend/core/services/channel_link_service.py`
- Test: `apps/backend/tests/unit/services/test_channel_link_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/unit/services/test_channel_link_service.py`:

```python
@pytest.mark.asyncio
async def test_complete_link_code_not_found(tmp_efs):
    _, owner_id, owner_dir = tmp_efs
    _write_pairing_file(owner_dir, "telegram", [])  # empty

    from core.services import channel_link_service

    with patch("core.services.channel_link_service.channel_link_repo") as mock_repo:
        mock_repo.get_by_peer = AsyncMock(return_value=None)
        with pytest.raises(channel_link_service.PairingCodeNotFoundError):
            await channel_link_service.complete_link(
                owner_id=owner_id, provider="telegram", agent_id="main",
                code="XYZ98765", member_id="user_bob",
            )


@pytest.mark.asyncio
async def test_complete_link_pairing_file_missing(tmp_efs):
    _, owner_id, _ = tmp_efs
    # Don't write any pairing file

    from core.services import channel_link_service

    with patch("core.services.channel_link_service.channel_link_repo") as mock_repo:
        mock_repo.get_by_peer = AsyncMock(return_value=None)
        with pytest.raises(channel_link_service.PairingCodeNotFoundError):
            await channel_link_service.complete_link(
                owner_id=owner_id, provider="telegram", agent_id="main",
                code="XYZ98765", member_id="user_bob",
            )


@pytest.mark.asyncio
async def test_complete_link_code_expired(tmp_efs):
    _, owner_id, owner_dir = tmp_efs
    # createdAt is 2 hours ago
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _write_pairing_file(
        owner_dir, "telegram",
        [{"id": "12345", "code": "XYZ98765", "createdAt": old_ts, "lastSeenAt": old_ts}],
    )

    from core.services import channel_link_service

    with patch("core.services.channel_link_service.channel_link_repo") as mock_repo:
        mock_repo.get_by_peer = AsyncMock(return_value=None)
        with pytest.raises(channel_link_service.PairingCodeNotFoundError):
            await channel_link_service.complete_link(
                owner_id=owner_id, provider="telegram", agent_id="main",
                code="XYZ98765", member_id="user_bob",
            )


@pytest.mark.asyncio
async def test_complete_link_wrong_channel_file(tmp_efs):
    _, owner_id, owner_dir = tmp_efs
    # Code lives in telegram file
    _write_pairing_file(
        owner_dir, "telegram",
        [{
            "id": "12345", "code": "XYZ98765",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "lastSeenAt": datetime.now(timezone.utc).isoformat(),
        }],
    )

    from core.services import channel_link_service

    # Caller asks for discord → should miss
    with patch("core.services.channel_link_service.channel_link_repo") as mock_repo:
        mock_repo.get_by_peer = AsyncMock(return_value=None)
        with pytest.raises(channel_link_service.PairingCodeNotFoundError):
            await channel_link_service.complete_link(
                owner_id=owner_id, provider="discord", agent_id="main",
                code="XYZ98765", member_id="user_bob",
            )


@pytest.mark.asyncio
async def test_complete_link_already_linked_same_member_idempotent(tmp_efs):
    _, owner_id, owner_dir = tmp_efs
    _write_pairing_file(
        owner_dir, "telegram",
        [{
            "id": "12345", "code": "XYZ98765",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "lastSeenAt": datetime.now(timezone.utc).isoformat(),
        }],
    )

    from core.services import channel_link_service

    existing_row = {
        "owner_id": owner_id, "provider": "telegram", "agent_id": "main",
        "peer_id": "12345", "member_id": "user_bob", "linked_via": "wizard",
    }
    with patch("core.services.channel_link_service.channel_link_repo") as mock_repo:
        mock_repo.get_by_peer = AsyncMock(return_value=existing_row)
        mock_repo.put = AsyncMock()
        result = await channel_link_service.complete_link(
            owner_id=owner_id, provider="telegram", agent_id="main",
            code="XYZ98765", member_id="user_bob",
        )
    assert result["status"] == "already_linked"
    mock_repo.put.assert_not_called()


@pytest.mark.asyncio
async def test_complete_link_peer_already_linked_other_member_raises(tmp_efs):
    _, owner_id, owner_dir = tmp_efs
    _write_pairing_file(
        owner_dir, "telegram",
        [{
            "id": "12345", "code": "XYZ98765",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "lastSeenAt": datetime.now(timezone.utc).isoformat(),
        }],
    )

    from core.services import channel_link_service

    existing_row = {
        "owner_id": owner_id, "provider": "telegram", "agent_id": "main",
        "peer_id": "12345", "member_id": "user_alice", "linked_via": "wizard",
    }
    with patch("core.services.channel_link_service.channel_link_repo") as mock_repo:
        mock_repo.get_by_peer = AsyncMock(return_value=existing_row)
        mock_repo.put = AsyncMock()
        with pytest.raises(channel_link_service.PeerAlreadyLinkedError):
            await channel_link_service.complete_link(
                owner_id=owner_id, provider="telegram", agent_id="main",
                code="XYZ98765", member_id="user_bob",  # different member
            )
    mock_repo.put.assert_not_called()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_channel_link_service.py -v
```

Expected: 6 new tests FAIL (one passes — happy path from C1). Most failures are around `PeerAlreadyLinkedError` not existing, and the idempotent-already-linked short-circuit not being implemented yet.

- [ ] **Step 3: Update the service to handle the error paths**

Add the `PeerAlreadyLinkedError` class and the pre-check logic in `apps/backend/core/services/channel_link_service.py`. After the `PairingCodeNotFoundError` class definition, add:

```python
class PeerAlreadyLinkedError(ChannelLinkError):
    """The platform user ID is already linked to a different Clerk member."""
```

Then update `complete_link` to check for an existing link before writing. Insert this block **after** we've found the `match` and extracted `peer_id`, and **before** the `append_to_openclaw_config_list` call:

```python
    # Check for an existing link row for this (owner, provider, agent, peer)
    existing = await channel_link_repo.get_by_peer(
        owner_id=owner_id,
        provider=provider,
        agent_id=agent_id,
        peer_id=peer_id,
    )
    if existing is not None:
        if existing.get("member_id") == member_id:
            logger.info(
                "Link already exists for member %s on %s peer %s — no-op",
                member_id, provider, peer_id,
            )
            return {"status": "already_linked", "peer_id": peer_id}
        raise PeerAlreadyLinkedError(
            f"Peer {peer_id} on {provider}/{agent_id} is already linked to another member"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_channel_link_service.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/channel_link_service.py apps/backend/tests/unit/services/test_channel_link_service.py
git commit -m "$(cat <<'EOF'
feat(backend): channel_link_service error paths

Adds PairingCodeNotFoundError (missing, expired, wrong channel, no
pairing file yet) and PeerAlreadyLinkedError (shoulder-surfed code,
peer linked to different member). Idempotent re-link for the same
(owner, provider, agent, peer, member) tuple.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase D — `PATCH /api/v1/config` router

**Why now:** The frontend wizards (Phase I onwards) need a single REST endpoint for config writes. This endpoint replaces the frontend's direct use of OpenClaw's `config.patch` RPC, unifying all config-write code paths through `patch_openclaw_config` on EFS. Backend services already use that helper; this task just exposes it to the frontend with proper auth, tier gating, and org RBAC.

**What exists today:** `apps/backend/routers/updates.py` already has `PATCH /api/v1/container/config/{owner_id}` — an admin-only endpoint that takes an arbitrary `owner_id` in the path. We can't reuse it directly because it's admin-only and takes owner_id as a path param. We need a new endpoint that derives owner_id from the auth context.

**Tier gating rules** (from the spec, and matching `core/config.py` TIER_CONFIG):
- Free tier: cannot enable channels. Any patch that touches `channels.*` fields (except the top-level `channels` key existing with all `enabled: false` — which Phase H writes on provision) is rejected with `403 channels_require_paid_tier`.
- Starter / Pro / Enterprise: can freely patch channels.

### Task D1: `PATCH /api/v1/config` endpoint with auth, tier gate, and admin requirement

**Files:**
- Create: `apps/backend/routers/config.py`
- Modify: `apps/backend/main.py`
- Test: `apps/backend/tests/unit/routers/test_config_router.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/routers/test_config_router.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from core.auth import AuthContext


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _personal_auth(user_id: str = "user_personal") -> AuthContext:
    return AuthContext(user_id=user_id, org_id=None, org_role=None, email="test@example.com")


def _org_admin_auth(user_id: str = "user_admin", org_id: str = "org_1") -> AuthContext:
    return AuthContext(user_id=user_id, org_id=org_id, org_role="org:admin", email="admin@example.com")


def _org_member_auth(user_id: str = "user_member", org_id: str = "org_1") -> AuthContext:
    return AuthContext(user_id=user_id, org_id=org_id, org_role="org:member", email="member@example.com")


def _patch_auth(auth: AuthContext):
    """Override the FastAPI dependency that returns the auth context."""
    from core.auth import get_current_user
    from main import app
    app.dependency_overrides[get_current_user] = lambda: auth
    return lambda: app.dependency_overrides.pop(get_current_user, None)


def _mock_billing(tier: str):
    return patch(
        "routers.config.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": tier}),
    )


def test_patch_config_personal_user_succeeds(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, \
             _mock_billing("starter"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"enabled": True}}}},
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
        call_args = mock_patch.call_args
        assert call_args[0][0] == "user_personal"
    finally:
        cleanup()


def test_patch_config_org_admin_succeeds(client):
    cleanup = _patch_auth(_org_admin_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, \
             _mock_billing("pro"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"enabled": True}}}},
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
        assert mock_patch.call_args[0][0] == "org_1"
    finally:
        cleanup()


def test_patch_config_org_member_rejected(client):
    cleanup = _patch_auth(_org_member_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, \
             _mock_billing("pro"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"enabled": True}}}},
            )
        assert resp.status_code == 403
        mock_patch.assert_not_called()
    finally:
        cleanup()


def test_patch_config_free_tier_channels_rejected(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, \
             _mock_billing("free"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"enabled": True}}}},
            )
        assert resp.status_code == 403
        assert "channels_require_paid_tier" in resp.json().get("detail", "")
        mock_patch.assert_not_called()
    finally:
        cleanup()


def test_patch_config_free_tier_non_channels_succeeds(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, \
             _mock_billing("free"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"tools": {"profile": "full"}}},
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
    finally:
        cleanup()


def test_patch_config_validation_rejects_non_dict_patch(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        resp = client.patch(
            "/api/v1/config",
            json={"patch": "not a dict"},
        )
        assert resp.status_code == 422  # Pydantic rejects
    finally:
        cleanup()


def test_patch_config_rejects_token_collision(client):
    """Pasting a token already assigned to a different agent returns 409."""
    cleanup = _patch_auth(_personal_auth())
    try:
        existing_cfg = {
            "channels": {
                "telegram": {
                    "accounts": {
                        "main": {"botToken": "SHARED_TOKEN"},
                    },
                },
            },
        }
        with patch("routers.config.patch_openclaw_config", AsyncMock()), \
             patch(
                 "core.containers.config.read_openclaw_config_from_efs",
                 AsyncMock(return_value=existing_cfg),
             ), _mock_billing("pro"):
            resp = client.patch(
                "/api/v1/config",
                json={
                    "patch": {
                        "channels": {
                            "telegram": {
                                "accounts": {
                                    "sales": {"botToken": "SHARED_TOKEN"},
                                },
                            },
                        },
                    },
                },
            )
        assert resp.status_code == 409
        assert "token_already_assigned_to_other_agent" in resp.json().get("detail", "")
    finally:
        cleanup()


def test_patch_config_allows_overwriting_own_agent_token(client):
    """Updating the SAME agent's token is fine (overwrite)."""
    cleanup = _patch_auth(_personal_auth())
    try:
        existing_cfg = {
            "channels": {
                "telegram": {
                    "accounts": {
                        "main": {"botToken": "OLD_TOKEN"},
                    },
                },
            },
        }
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, \
             patch(
                 "core.containers.config.read_openclaw_config_from_efs",
                 AsyncMock(return_value=existing_cfg),
             ), _mock_billing("pro"):
            resp = client.patch(
                "/api/v1/config",
                json={
                    "patch": {
                        "channels": {
                            "telegram": {
                                "accounts": {
                                    "main": {"botToken": "NEW_TOKEN"},
                                },
                            },
                        },
                    },
                },
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
    finally:
        cleanup()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_config_router.py -v
```

Expected: all tests FAIL (module doesn't exist yet).

- [ ] **Step 3: Implement the router**

Create `apps/backend/routers/config.py`:

```python
"""Config router — unified EFS-write endpoint for openclaw.json patches.

Wraps patch_openclaw_config. Derives owner_id from the auth context,
enforces org_admin for org callers, and tier-gates channel-related
patches behind Starter+.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import (
    AuthContext,
    get_current_user,
    require_org_admin,
    resolve_owner_id,
)
from core.repositories import billing_repo
from core.services.config_patcher import (
    ConfigPatchError,
    patch_openclaw_config,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ConfigPatchBody(BaseModel):
    patch: dict


def _patch_touches_channels(patch: dict) -> bool:
    """Return True if the patch modifies any channels.<provider>.* fields.

    A top-level `channels` key alone is fine (e.g., the initial scaffold);
    we only care if the caller is trying to configure channel accounts,
    tokens, bindings, etc.
    """
    if not isinstance(patch, dict):
        return False
    channels = patch.get("channels")
    if not isinstance(channels, dict) or not channels:
        return False
    # Any non-empty nested dict under channels.* means an actual config
    for _provider, provider_cfg in channels.items():
        if isinstance(provider_cfg, dict) and provider_cfg:
            return True
    return False


@router.patch(
    "",
    summary="Patch the caller's openclaw.json config",
    description=(
        "Deep-merges the patch into the caller's owner_id openclaw.json on EFS. "
        "Derives owner_id from auth context (org_id if org, else user_id). "
        "Requires org_admin for org callers. Tier-gates channel fields."
    ),
)
async def patch_config(
    body: ConfigPatchBody,
    auth: AuthContext = Depends(get_current_user),
):
    # Org admin check (personal context passes through)
    require_org_admin(auth)

    owner_id = resolve_owner_id(auth)

    # Tier gate on channel fields
    if _patch_touches_channels(body.patch):
        account = await billing_repo.get_by_owner_id(owner_id)
        tier = (account or {}).get("plan_tier", "free")
        if tier == "free":
            raise HTTPException(
                status_code=403,
                detail="channels_require_paid_tier",
            )

        # Bot token collision pre-check: scan the patch for any
        # channels.<provider>.accounts.<agent_id>.botToken values and verify
        # they aren't already assigned to a DIFFERENT agent in the existing
        # openclaw.json. Prevents two agents accidentally sharing a bot.
        await _check_token_collision(owner_id, body.patch)

    try:
        await patch_openclaw_config(owner_id, body.patch)
    except ConfigPatchError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "patched", "owner_id": owner_id}


async def _check_token_collision(owner_id: str, patch: dict) -> None:
    """Raise 409 token_already_assigned_to_other_agent if the patch introduces
    a botToken that already exists under a different accounts.<agent_id> entry
    in the owner's openclaw.json.
    """
    from core.containers.config import read_openclaw_config_from_efs

    channels = patch.get("channels")
    if not isinstance(channels, dict):
        return

    # Collect (provider, agent_id, token) tuples in the patch
    patch_tokens: list[tuple[str, str, str]] = []
    for provider, provider_cfg in channels.items():
        if not isinstance(provider_cfg, dict):
            continue
        accounts = provider_cfg.get("accounts")
        if not isinstance(accounts, dict):
            continue
        for agent_id, account_cfg in accounts.items():
            if not isinstance(account_cfg, dict):
                continue
            token = account_cfg.get("botToken")
            if isinstance(token, str) and token.strip():
                patch_tokens.append((provider, agent_id, token.strip()))

    if not patch_tokens:
        return

    current = await read_openclaw_config_from_efs(owner_id) or {}
    current_channels = current.get("channels", {}) if isinstance(current, dict) else {}

    for provider, incoming_agent, incoming_token in patch_tokens:
        provider_cfg = current_channels.get(provider, {})
        if not isinstance(provider_cfg, dict):
            continue
        existing_accounts = provider_cfg.get("accounts", {})
        if not isinstance(existing_accounts, dict):
            continue
        for existing_agent, existing_cfg in existing_accounts.items():
            if existing_agent == incoming_agent:
                continue  # same agent, overwrite is fine
            if not isinstance(existing_cfg, dict):
                continue
            if existing_cfg.get("botToken") == incoming_token:
                raise HTTPException(
                    status_code=409,
                    detail="token_already_assigned_to_other_agent",
                )
```

- [ ] **Step 4: Register the router in `main.py`**

Edit `apps/backend/main.py`. Find the import block at line 20 that looks like:

```python
from routers import (
    users,
    websocket_chat,
    billing,
    ...
)
```

Add `config` to the import list (keep alphabetized among the existing entries, or append — match the existing convention). Then find the `app.include_router(...)` block and add this line (group it near the other channel/config routers):

```python
app.include_router(config.router, prefix="/api/v1/config", tags=["config"])
```

- [ ] **Step 5: Run the tests to verify they pass, then commit**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_config_router.py -v
```

Expected: 6 tests PASS.

```bash
git add apps/backend/routers/config.py apps/backend/main.py apps/backend/tests/unit/routers/test_config_router.py
git commit -m "$(cat <<'EOF'
feat(backend): add PATCH /api/v1/config endpoint

Unified EFS-write endpoint for openclaw.json patches. Derives owner_id
from auth context, requires org_admin for org callers, and tier-gates
channel-related fields behind Starter+. Replaces frontend direct use of
the OpenClaw config.patch RPC in a follow-up phase.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase E — Channels router: link endpoints + WhatsApp removal

**Why now:** The service (Phase C) and storage (Phase B) are in place. Now expose them via REST so the frontend wizards (Phase I+) can call them. Also drop WhatsApp code since it's out of scope.

**What exists today:** `apps/backend/routers/channels.py` has: `GET /`, `POST /telegram`, `POST /discord`, `POST /whatsapp/pair`, `GET /whatsapp/qr`, `DELETE /{provider}`. All of them call `_send_channel_rpc` which proxies to OpenClaw's `channels.configure` RPC. The spec replaces the `POST /telegram` / `POST /discord` configure endpoints with the new unified `PATCH /api/v1/config` path (done in Phase D), so we don't need those anymore either.

**New endpoints:**

- `POST /api/v1/channels/link/{provider}/complete` — body `{agent_id, code, linked_via?}` → calls `channel_link_service.complete_link`. Returns `200 {status, peer_id}` or `404 pairing_code_not_found` or `409 peer_already_linked`.
- `DELETE /api/v1/channels/link/{provider}/{agent_id}` — unlinks the calling member from the given bot. Removes their peer_id from `allowFrom` + deletes the DynamoDB row.
- `GET /api/v1/channels/links/me` — returns the caller's link status across all bots in their container, grouped by provider. See the data flow section of the spec for the exact response shape.

**Removed endpoints:** `POST /telegram`, `POST /discord`, `POST /whatsapp/pair`, `GET /whatsapp/qr`. The `DELETE /{provider}` endpoint becomes the admin bot-delete path and gets rewritten to use the new helpers from Phase A.

### Task E1: Remove WhatsApp + old configure endpoints from channels router

**Files:**
- Modify: `apps/backend/routers/channels.py`
- Test: `apps/backend/tests/unit/routers/test_channels_link_router.py` (new)

- [ ] **Step 1: Write the failing test for the admin bot-delete endpoint**

Create `apps/backend/tests/unit/routers/test_channels_link_router.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from core.auth import AuthContext


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _patch_auth(auth: AuthContext):
    from core.auth import get_current_user
    from main import app
    app.dependency_overrides[get_current_user] = lambda: auth
    return lambda: app.dependency_overrides.pop(get_current_user, None)


def _personal_auth(user_id: str = "user_personal") -> AuthContext:
    return AuthContext(user_id=user_id, org_id=None, org_role=None, email="test@example.com")


def test_delete_bot_unsupported_provider_returns_400(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        resp = client.delete("/api/v1/channels/link/whatsapp/main")
        assert resp.status_code == 400
    finally:
        cleanup()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_channels_link_router.py -v
```

Expected: FAIL (endpoint doesn't exist yet; probably 404).

- [ ] **Step 3: Replace the contents of `routers/channels.py`**

Overwrite `apps/backend/routers/channels.py` with the new shape:

```python
"""Channel management router.

Exposes:
- POST /link/{provider}/complete — member self-link flow
- DELETE /link/{provider}/{agent_id} — member self-unlink
- DELETE /{provider}/{agent_id} — admin bot delete
- GET /links/me — list caller's channel link status across bots

The old configure endpoints (POST /telegram, POST /discord, WhatsApp
pairing) are removed — bot configuration now goes through PATCH /api/v1/config.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import (
    AuthContext,
    get_current_user,
    require_org_admin,
    resolve_owner_id,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_PROVIDERS = {"telegram", "discord", "slack"}


def _validate_provider(provider: str) -> str:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
    return provider


@router.delete(
    "/{provider}/{agent_id}",
    summary="Admin: delete a bot from an agent (WhatsApp not supported, hence the 400 guard)",
)
async def admin_delete_bot(
    provider: str,
    agent_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    require_org_admin(auth)
    owner_id = resolve_owner_id(auth)
    # Full implementation arrives in Task E2 (needs channel_link_repo sweep + config helpers)
    raise HTTPException(status_code=501, detail="not_yet_implemented")
```

This intentionally-stubby module (a) drops WhatsApp and the old configure endpoints, (b) establishes the new provider guard, and (c) gives Task E2/E3 a base to extend. Subsequent tasks fill in real behavior.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_channels_link_router.py -v
```

Expected: PASS (the one test just verifies 400 for the unsupported provider).

Also run the broader test suite to make sure nothing else was importing the deleted endpoints:

```bash
cd apps/backend && uv run pytest tests/unit/ -v --ignore=tests/unit/services/test_usage_service.py 2>&1 | tail -20
```

Expected: no new failures. If anything broke (e.g., an existing test imported `configure_telegram`), investigate and update — the old behavior is gone.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/channels.py apps/backend/tests/unit/routers/test_channels_link_router.py
git commit -m "$(cat <<'EOF'
refactor(backend): strip channels router down to link + admin delete

Removes POST /telegram, POST /discord, POST /whatsapp/pair, GET
/whatsapp/qr, and the generic DELETE /{provider}. Configure-time writes
now go through PATCH /api/v1/config. Provider set is telegram/discord/
slack — whatsapp is unsupported and returns 400. Remaining endpoints
are stubs to be filled in by the next tasks.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task E2: `POST /channels/link/{provider}/complete` endpoint

**Files:**
- Modify: `apps/backend/routers/channels.py`
- Test: `apps/backend/tests/unit/routers/test_channels_link_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/unit/routers/test_channels_link_router.py`:

```python
def test_link_complete_happy_path(client):
    cleanup = _patch_auth(_personal_auth("user_bob"))
    try:
        with patch(
            "routers.channels.channel_link_service.complete_link",
            AsyncMock(return_value={"status": "linked", "peer_id": "12345"}),
        ) as mock_link:
            resp = client.post(
                "/api/v1/channels/link/telegram/complete",
                json={"agent_id": "main", "code": "XYZ98765"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "linked"
        assert resp.json()["peer_id"] == "12345"
        mock_link.assert_awaited_once()
        kwargs = mock_link.call_args.kwargs
        assert kwargs["owner_id"] == "user_bob"
        assert kwargs["provider"] == "telegram"
        assert kwargs["agent_id"] == "main"
        assert kwargs["code"] == "XYZ98765"
        assert kwargs["member_id"] == "user_bob"  # the caller's clerk user_id
    finally:
        cleanup()


def test_link_complete_code_not_found_returns_404(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        from core.services.channel_link_service import PairingCodeNotFoundError
        with patch(
            "routers.channels.channel_link_service.complete_link",
            AsyncMock(side_effect=PairingCodeNotFoundError("not found")),
        ):
            resp = client.post(
                "/api/v1/channels/link/telegram/complete",
                json={"agent_id": "main", "code": "BAD"},
            )
        assert resp.status_code == 404
    finally:
        cleanup()


def test_link_complete_peer_already_linked_returns_409(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        from core.services.channel_link_service import PeerAlreadyLinkedError
        with patch(
            "routers.channels.channel_link_service.complete_link",
            AsyncMock(side_effect=PeerAlreadyLinkedError("taken")),
        ):
            resp = client.post(
                "/api/v1/channels/link/telegram/complete",
                json={"agent_id": "main", "code": "XYZ98765"},
            )
        assert resp.status_code == 409
    finally:
        cleanup()


def test_link_complete_unsupported_provider_returns_400(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        resp = client.post(
            "/api/v1/channels/link/whatsapp/complete",
            json={"agent_id": "main", "code": "XYZ"},
        )
        assert resp.status_code == 400
    finally:
        cleanup()


def test_link_complete_uses_member_id_not_owner_for_org_callers(client):
    from core.auth import AuthContext
    auth = AuthContext(
        user_id="user_bob", org_id="org_1",
        org_role="org:member", email="bob@example.com",
    )
    cleanup = _patch_auth(auth)
    try:
        with patch(
            "routers.channels.channel_link_service.complete_link",
            AsyncMock(return_value={"status": "linked", "peer_id": "12345"}),
        ) as mock_link:
            resp = client.post(
                "/api/v1/channels/link/telegram/complete",
                json={"agent_id": "main", "code": "XYZ98765"},
            )
        assert resp.status_code == 200
        kwargs = mock_link.call_args.kwargs
        assert kwargs["owner_id"] == "org_1"   # container is the org
        assert kwargs["member_id"] == "user_bob"   # the clerk member is Bob
    finally:
        cleanup()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_channels_link_router.py -v -k "link_complete"
```

Expected: FAIL (endpoint not implemented).

- [ ] **Step 3: Implement the endpoint**

Add to `apps/backend/routers/channels.py` (after the imports, before the admin delete handler):

```python
from core.services import channel_link_service


class LinkCompleteBody(BaseModel):
    agent_id: str
    code: str


@router.post(
    "/link/{provider}/complete",
    summary="Complete the member-link flow by pasting the pairing code",
)
async def link_complete(
    provider: str,
    body: LinkCompleteBody,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    owner_id = resolve_owner_id(auth)
    member_id = auth.user_id  # always the caller, even in org context

    try:
        result = await channel_link_service.complete_link(
            owner_id=owner_id,
            provider=provider,
            agent_id=body.agent_id,
            code=body.code,
            member_id=member_id,
            linked_via="settings",
        )
    except channel_link_service.PairingCodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except channel_link_service.PeerAlreadyLinkedError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_channels_link_router.py -v -k "link_complete"
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/channels.py apps/backend/tests/unit/routers/test_channels_link_router.py
git commit -m "$(cat <<'EOF'
feat(backend): POST /channels/link/{provider}/complete endpoint

Member self-link via paste-the-pairing-code. 404 for missing/expired
code, 409 for peer-already-linked-to-other-member, 400 for unsupported
providers. In org context, writes against the org's container but
records the caller's clerk_user_id as the linked member.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task E3: `GET /channels/links/me` + `DELETE /channels/link/{provider}/{agent_id}` + fill in admin bot-delete

**Files:**
- Modify: `apps/backend/routers/channels.py`
- Modify: `apps/backend/core/containers/config.py` (add a small helper `read_openclaw_config_from_efs(owner_id)` that returns the parsed JSON or None — used by `GET /links/me`)
- Test: `apps/backend/tests/unit/routers/test_channels_link_router.py`

- [ ] **Step 1: Write the failing tests for the three remaining endpoints**

Append to `apps/backend/tests/unit/routers/test_channels_link_router.py`:

```python
def test_get_links_me_returns_grouped_by_provider(client):
    cleanup = _patch_auth(_personal_auth("user_bob"))
    try:
        fake_config = {
            "channels": {
                "telegram": {
                    "accounts": {
                        "main": {"botToken": "xxx"},
                        "sales": {"botToken": "yyy"},
                    },
                },
                "discord": {
                    "accounts": {},
                },
            },
        }
        fake_links = [
            {
                "owner_id": "user_bob", "provider": "telegram",
                "agent_id": "main", "peer_id": "12345",
                "member_id": "user_bob",
            },
        ]
        with patch(
            "routers.channels.read_openclaw_config_from_efs",
            AsyncMock(return_value=fake_config),
        ), patch(
            "routers.channels.channel_link_repo.query_by_member",
            AsyncMock(return_value=fake_links),
        ):
            resp = client.get("/api/v1/channels/links/me")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["telegram"]) == 2  # main + sales
        main = next(b for b in body["telegram"] if b["agent_id"] == "main")
        assert main["linked"] is True
        sales = next(b for b in body["telegram"] if b["agent_id"] == "sales")
        assert sales["linked"] is False
        assert body["discord"] == []
        assert body["slack"] == []
        # Personal user is always admin of their own container
        assert body["can_create_bots"] is True
    finally:
        cleanup()


def test_get_links_me_org_member_cannot_create_bots(client):
    from core.auth import AuthContext
    auth = AuthContext(
        user_id="user_bob", org_id="org_1",
        org_role="org:member", email="bob@example.com",
    )
    cleanup = _patch_auth(auth)
    try:
        with patch(
            "routers.channels.read_openclaw_config_from_efs",
            AsyncMock(return_value={"channels": {"telegram": {"accounts": {}}}}),
        ), patch(
            "routers.channels.channel_link_repo.query_by_member",
            AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/channels/links/me")
        assert resp.status_code == 200
        assert resp.json()["can_create_bots"] is False
    finally:
        cleanup()


def test_delete_link_unlinks_self(client):
    cleanup = _patch_auth(_personal_auth("user_bob"))
    try:
        fake_link = {
            "owner_id": "user_bob", "provider": "telegram",
            "agent_id": "main", "peer_id": "12345",
            "member_id": "user_bob",
        }
        with patch(
            "routers.channels.channel_link_repo.get_by_peer",
            AsyncMock(return_value=fake_link),
        ), patch(
            "routers.channels.channel_link_repo.query_by_member",
            AsyncMock(return_value=[fake_link]),
        ) as mock_query, patch(
            "routers.channels.channel_link_repo.delete",
            AsyncMock(),
        ) as mock_delete, patch(
            "routers.channels.remove_from_openclaw_config_list",
            AsyncMock(),
        ) as mock_remove:
            resp = client.delete("/api/v1/channels/link/telegram/main")
        assert resp.status_code == 200
        mock_delete.assert_awaited_once()
        mock_remove.assert_awaited_once()
        call = mock_remove.call_args
        # path is allowFrom
        assert call[0][1] == ["channels", "telegram", "accounts", "main", "allowFrom"]


def test_admin_delete_bot_sweeps_links_and_config(client):
    from core.auth import AuthContext
    auth = AuthContext(
        user_id="admin_a", org_id="org_1",
        org_role="org:admin", email="admin@example.com",
    )
    cleanup = _patch_auth(auth)
    try:
        with patch(
            "routers.channels.delete_openclaw_config_path",
            AsyncMock(),
        ) as mock_del_path, patch(
            "routers.channels.remove_from_openclaw_config_list",
            AsyncMock(),
        ) as mock_rm_binding, patch(
            "routers.channels.channel_link_repo.sweep_by_owner_provider_agent",
            AsyncMock(return_value=3),
        ) as mock_sweep:
            resp = client.delete("/api/v1/channels/telegram/sales")
        assert resp.status_code == 200
        mock_del_path.assert_awaited_once()
        mock_rm_binding.assert_awaited_once()
        mock_sweep.assert_awaited_once()
        assert resp.json()["links_swept"] == 3
    finally:
        cleanup()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_channels_link_router.py -v
```

Expected: the 4 new tests FAIL (missing imports, stub endpoint still raises 501, etc.).

- [ ] **Step 3: Add the `read_openclaw_config_from_efs` helper**

Append to `apps/backend/core/containers/config.py`:

```python
async def read_openclaw_config_from_efs(owner_id: str) -> dict | None:
    """Read and parse openclaw.json directly from EFS.

    Works even when the container is scaled down (no gateway RPC needed).
    Returns None if the file doesn't exist yet.
    """
    import asyncio
    import json
    import os

    config_path = os.path.join(_efs_mount_path, owner_id, "openclaw.json")
    if not os.path.exists(config_path):
        return None

    def _read():
        with open(config_path, "r") as f:
            return json.load(f)

    return await asyncio.to_thread(_read)
```

If `_efs_mount_path` isn't defined in `core/containers/config.py` at module scope, add `from core.config import settings` at the top (if missing) and `_efs_mount_path = settings.EFS_MOUNT_PATH` near the top. **Check first** — it may already be there.

- [ ] **Step 4: Finish `channels.py` with the three new endpoints**

Replace the stub admin-delete endpoint in `apps/backend/routers/channels.py` with the full implementation, and add the two new endpoints. The final file should look like:

```python
"""Channel management router.

Exposes:
- GET /links/me — list caller's channel link status across bots
- POST /link/{provider}/complete — member self-link flow
- DELETE /link/{provider}/{agent_id} — member self-unlink
- DELETE /{provider}/{agent_id} — admin bot delete
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import (
    AuthContext,
    get_current_user,
    require_org_admin,
    resolve_owner_id,
)
from core.containers.config import read_openclaw_config_from_efs
from core.repositories import channel_link_repo
from core.services import channel_link_service
from core.services.config_patcher import (
    delete_openclaw_config_path,
    remove_from_openclaw_config_list,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_PROVIDERS = {"telegram", "discord", "slack"}


def _validate_provider(provider: str) -> str:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
    return provider


class LinkCompleteBody(BaseModel):
    agent_id: str
    code: str


@router.get("/links/me", summary="List the caller's channel link status across all bots")
async def get_links_me(auth: AuthContext = Depends(get_current_user)):
    owner_id = resolve_owner_id(auth)
    member_id = auth.user_id

    config = await read_openclaw_config_from_efs(owner_id) or {}
    channels_cfg = config.get("channels", {}) if isinstance(config, dict) else {}

    # Look up all link rows for this member
    all_member_links = await channel_link_repo.query_by_member(member_id)
    links_for_owner = {
        (link["provider"], link["agent_id"]): link
        for link in all_member_links
        if link.get("owner_id") == owner_id
    }

    result: dict = {"can_create_bots": not auth.is_org_context or auth.is_org_admin}
    for provider in ("telegram", "discord", "slack"):
        provider_cfg = channels_cfg.get(provider, {}) if isinstance(channels_cfg, dict) else {}
        accounts = provider_cfg.get("accounts", {}) if isinstance(provider_cfg, dict) else {}
        bots = []
        if isinstance(accounts, dict):
            for agent_id in accounts.keys():
                linked = (provider, agent_id) in links_for_owner
                bots.append({
                    "agent_id": agent_id,
                    "bot_username": agent_id,  # placeholder; live name comes from channels.status later
                    "linked": linked,
                })
        result[provider] = bots
    return result


@router.post(
    "/link/{provider}/complete",
    summary="Complete the member-link flow by pasting the pairing code",
)
async def link_complete(
    provider: str,
    body: LinkCompleteBody,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    owner_id = resolve_owner_id(auth)
    member_id = auth.user_id

    try:
        result = await channel_link_service.complete_link(
            owner_id=owner_id,
            provider=provider,
            agent_id=body.agent_id,
            code=body.code,
            member_id=member_id,
            linked_via="settings",
        )
    except channel_link_service.PairingCodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except channel_link_service.PeerAlreadyLinkedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result


@router.delete(
    "/link/{provider}/{agent_id}",
    summary="Unlink the caller's identity from a bot",
)
async def link_delete(
    provider: str,
    agent_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    owner_id = resolve_owner_id(auth)
    member_id = auth.user_id

    # Find the member's own row for this bot
    member_rows = await channel_link_repo.query_by_member(member_id)
    match = next(
        (
            row for row in member_rows
            if row.get("owner_id") == owner_id
            and row.get("provider") == provider
            and row.get("agent_id") == agent_id
        ),
        None,
    )
    if match is None:
        return {"status": "not_linked"}

    peer_id = match["peer_id"]

    await remove_from_openclaw_config_list(
        owner_id,
        ["channels", provider, "accounts", agent_id, "allowFrom"],
        predicate=lambda v: v == peer_id,
    )
    await channel_link_repo.delete(
        owner_id=owner_id, provider=provider, agent_id=agent_id, peer_id=peer_id,
    )
    return {"status": "unlinked"}


@router.delete(
    "/{provider}/{agent_id}",
    summary="Admin: delete a bot from an agent entirely",
)
async def admin_delete_bot(
    provider: str,
    agent_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    require_org_admin(auth)
    owner_id = resolve_owner_id(auth)

    # Remove the account block
    await delete_openclaw_config_path(
        owner_id,
        ["channels", provider, "accounts", agent_id],
    )
    # Remove the binding that routes this (provider, accountId) to the agent
    await remove_from_openclaw_config_list(
        owner_id,
        ["bindings"],
        predicate=lambda b: (
            isinstance(b, dict)
            and b.get("match", {}).get("channel") == provider
            and b.get("match", {}).get("accountId") == agent_id
        ),
    )
    # Sweep channel-link rows for this bot
    count = await channel_link_repo.sweep_by_owner_provider_agent(
        owner_id=owner_id, provider=provider, agent_id=agent_id,
    )
    logger.info(
        "Admin %s deleted %s bot for agent %s in owner %s (swept %d links)",
        auth.user_id, provider, agent_id, owner_id, count,
    )
    return {"status": "deleted", "links_swept": count}
```

- [ ] **Step 5: Run the tests and commit**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_channels_link_router.py -v
```

Expected: all 10 tests PASS (1 from E1 + 5 from E2 + 4 from E3).

```bash
git add apps/backend/routers/channels.py apps/backend/core/containers/config.py apps/backend/tests/unit/routers/test_channels_link_router.py
git commit -m "$(cat <<'EOF'
feat(backend): channels router — GET /links/me, DELETE link, admin delete bot

- GET /links/me reads openclaw.json directly from EFS (works when
  container is scaled down), queries by-member GSI, joins, returns
  per-provider bot lists with link status and can_create_bots flag.
- DELETE /link/{provider}/{agent_id} self-unlinks the caller (removes
  their peer_id from allowFrom + deletes the DynamoDB row).
- DELETE /{provider}/{agent_id} is the admin bot-delete path: sweeps
  the account config path, removes the matching binding, and deletes
  all channel_link rows for that bot.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase F — Billing parser rewrite + lifecycle/end trigger

**Why now:** This is the second pillar of the spec and is orthogonal to phases A-E (it doesn't depend on any of them beyond `channel_link_repo.get_by_peer` from Phase B). It fixes the pre-existing bug that group sessions write `member:telegram:{period}` and adds per-member channel DM billing via `channel_link_repo` lookups.

**What exists today:** `apps/backend/core/gateway/connection_pool.py:284-340` has `_record_usage_from_session` which triggers only on `chat.final` events for webchat. Lines 306-307 have the broken parser (`parts[2] if parts[2] != "main" else self.user_id`). Line 484 calls it from the `chat.final` branch.

**What changes:**
1. Add `_parse_session_key(session_key)` — pure function, no I/O.
2. Add `_resolve_member_from_session(parsed)` — async, calls `channel_link_repo.get_by_peer` for DM sessions.
3. Rewrite `_record_usage_from_session` to use the new parser + resolver.
4. Add a new branch in `_handle_message` for `agent` events with `stream:"lifecycle"` + `phase:"end"` that triggers the billing path.
5. Remove the `chat.final → _record_usage_from_session` call (keep UI signaling for webchat).

**Key architectural fact** (verified at `openclaw/src/gateway/server-chat.ts:936`): the `broadcast("agent", agentPayload)` lives in the `else` branch of `if (isToolEvent) { ... } else { ... }` and fires for every non-tool agent event regardless of channel surface. Lifecycle events (`stream === "lifecycle"`) are not tool events, so they always reach the operator WS.

### Task F1: Add `_parse_session_key` pure function + tests

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py`
- Test: `apps/backend/tests/unit/gateway/test_session_key_parser.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/gateway/test_session_key_parser.py`:

```python
import pytest

from core.gateway.connection_pool import _parse_session_key


@pytest.mark.parametrize(
    "session_key,expected",
    [
        # Personal webchat
        (
            "agent:main:main",
            {"agent_id": "main", "source": "webchat"},
        ),
        # Org webchat — parts[2] is a Clerk user_id
        (
            "agent:main:user_2abc123",
            {"agent_id": "main", "source": "webchat", "member_id": "user_2abc123"},
        ),
        # Channel DM (per-account-channel-peer)
        (
            "agent:sales:telegram:sales:direct:99999",
            {
                "agent_id": "sales",
                "source": "dm",
                "channel": "telegram",
                "peer_id": "99999",
            },
        ),
        # Channel group
        (
            "agent:main:telegram:group:-1001234567890",
            {
                "agent_id": "main",
                "source": "group",
                "channel": "telegram",
                "group_id": "-1001234567890",
            },
        ),
        # Group with topic (Telegram forum)
        (
            "agent:main:telegram:group:-1001234567890:topic:42",
            {
                "agent_id": "main",
                "source": "group",
                "channel": "telegram",
                "group_id": "-1001234567890",
            },
        ),
        # Slack channel
        (
            "agent:main:slack:channel:C123ABC",
            {
                "agent_id": "main",
                "source": "channel",
                "channel": "slack",
                "channel_id": "C123ABC",
            },
        ),
        # Slack thread
        (
            "agent:main:slack:channel:C123ABC:thread:1234.5678",
            {
                "agent_id": "main",
                "source": "channel",
                "channel": "slack",
                "channel_id": "C123ABC",
            },
        ),
        # Malformed
        ("garbage", {}),
        ("", {}),
        # Sub-agent webchat (3 parts, parts[2] == main)
        ("agent:research_subagent:main", {"agent_id": "research_subagent", "source": "webchat"}),
    ],
)
def test_parse_session_key(session_key, expected):
    result = _parse_session_key(session_key)
    assert result == expected


def test_group_key_does_not_return_literal_channel_as_member_id():
    """Regression test for the pre-existing parser bug where group session
    keys wrote member:telegram:{period}. The new parser must NOT expose
    'telegram' (or any channel name) as a member_id anywhere."""
    result = _parse_session_key("agent:main:telegram:group:-100123")
    assert result.get("source") == "group"
    assert "member_id" not in result
    # Nothing in the result should equal the literal 'telegram' as a member id field
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/gateway/test_session_key_parser.py -v
```

Expected: FAIL with `ImportError: cannot import name '_parse_session_key'`.

- [ ] **Step 3: Add the `_parse_session_key` function**

Add this as a **module-level function** (not a method) near the bottom of `apps/backend/core/gateway/connection_pool.py`. Place it below the existing class and before any `if __name__` block:

```python
def _parse_session_key(session_key: str) -> dict:
    """Parse an OpenClaw session key into its components.

    Shapes (from openclaw/src/routing/session-key.ts with dmScope=per-account-channel-peer):
      Personal webchat:  agent:<agentId>:main
      Org webchat:       agent:<agentId>:<clerk_user_id>
      Channel DM:        agent:<agentId>:<channel>:<accountId>:direct:<peerId>
      Channel group:     agent:<agentId>:<channel>:group:<id>(:topic:<topicId>)?
      Channel room:      agent:<agentId>:<channel>:channel:<id>(:thread:<threadId>)?

    Returns dict with:
      - empty {} for malformed input
      - {agent_id, source} for webchat personal
      - {agent_id, source, member_id} for org webchat (member_id is the clerk user_id)
      - {agent_id, source, channel, peer_id} for channel DMs (source="dm")
      - {agent_id, source, channel, group_id} for channel groups (source="group")
      - {agent_id, source, channel, channel_id} for channel rooms (source="channel")
    """
    parts = session_key.split(":")
    if len(parts) < 3 or parts[0] != "agent":
        return {}
    agent_id = parts[1]

    # Webchat: 3 parts (agent:<agentId>:<sessionName>)
    if len(parts) == 3:
        if parts[2] == "main":
            return {"agent_id": agent_id, "source": "webchat"}
        # Org webchat — parts[2] is a Clerk user_id
        return {
            "agent_id": agent_id,
            "source": "webchat",
            "member_id": parts[2],
        }

    # Channel DM (per-account-channel-peer):
    # agent:<agentId>:<channel>:<accountId>:direct:<peerId>
    # In our design accountId == agentId so we don't extract parts[3] separately.
    if len(parts) == 6 and parts[4] == "direct":
        return {
            "agent_id": agent_id,
            "source": "dm",
            "channel": parts[2],
            "peer_id": parts[5],
        }

    # Channel group: agent:<agentId>:<channel>:group:<id>(:topic:<topicId>)?
    if len(parts) >= 5 and parts[3] == "group":
        return {
            "agent_id": agent_id,
            "source": "group",
            "channel": parts[2],
            "group_id": parts[4],
        }

    # Channel room: agent:<agentId>:<channel>:channel:<id>(:thread:<threadId>)?
    if len(parts) >= 5 and parts[3] == "channel":
        return {
            "agent_id": agent_id,
            "source": "channel",
            "channel": parts[2],
            "channel_id": parts[4],
        }

    return {"agent_id": agent_id, "source": "unknown"}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/gateway/test_session_key_parser.py -v
```

Expected: all 11 parametrized + 1 regression test PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/gateway/connection_pool.py apps/backend/tests/unit/gateway/test_session_key_parser.py
git commit -m "$(cat <<'EOF'
feat(backend): add _parse_session_key helper

Pure function that parses OpenClaw session keys into structured form.
Handles personal/org webchat, channel DMs, groups (with optional
topic), and Slack/Discord channels (with optional thread). Replaces
the broken parts[2] heuristic. Regression test asserts group keys no
longer surface the literal 'telegram' string as a member id.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task F2: Lifecycle/end billing trigger + member resolver

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py`
- Test: `apps/backend/tests/unit/gateway/test_lifecycle_billing.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/gateway/test_lifecycle_billing.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def conn():
    """Build a minimal GatewayConnection instance with enough state for billing tests."""
    from core.gateway.connection_pool import GatewayConnection

    c = GatewayConnection.__new__(GatewayConnection)
    c.user_id = "org_1"
    c._frontend_connections = set()
    c._pending_rpcs = {}
    c._management_api = MagicMock()
    return c


def test_lifecycle_end_for_channel_dm_triggers_billing_with_linked_member(conn):
    payload = {
        "runId": "run-1",
        "stream": "lifecycle",
        "data": {"phase": "end"},
        "sessionKey": "agent:sales:telegram:sales:direct:99999",
    }

    with patch(
        "core.gateway.connection_pool.channel_link_repo.get_by_peer",
        AsyncMock(return_value={"member_id": "user_bob", "peer_id": "99999"}),
    ) as mock_get, patch.object(
        conn, "_fetch_and_record_usage", AsyncMock(),
    ) as mock_fetch:
        conn._handle_message({
            "type": "event",
            "event": "agent",
            "payload": payload,
        })
        # Allow the async task created by _record_usage_from_session to run
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0.05))
        finally:
            loop.close()

    # The fetch ran with the resolved member_id
    mock_fetch.assert_awaited()
    call = mock_fetch.call_args
    assert call[0][0] == "agent:sales:telegram:sales:direct:99999"
    assert call[0][1] == "user_bob"


def test_lifecycle_end_for_channel_dm_unlinked_falls_back_to_owner(conn):
    payload = {
        "runId": "run-2",
        "stream": "lifecycle",
        "data": {"phase": "end"},
        "sessionKey": "agent:sales:telegram:sales:direct:66666",
    }

    with patch(
        "core.gateway.connection_pool.channel_link_repo.get_by_peer",
        AsyncMock(return_value=None),
    ), patch.object(
        conn, "_fetch_and_record_usage", AsyncMock(),
    ) as mock_fetch:
        conn._handle_message({"type": "event", "event": "agent", "payload": payload})
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0.05))
        finally:
            loop.close()

    mock_fetch.assert_awaited()
    # Unlinked → falls back to owner (self.user_id = "org_1")
    assert mock_fetch.call_args[0][1] == "org_1"


def test_lifecycle_end_for_org_webchat_uses_clerk_member(conn):
    payload = {
        "runId": "run-3",
        "stream": "lifecycle",
        "data": {"phase": "end"},
        "sessionKey": "agent:main:user_bob",
    }

    with patch(
        "core.gateway.connection_pool.channel_link_repo.get_by_peer",
        AsyncMock(return_value=None),
    ), patch.object(
        conn, "_fetch_and_record_usage", AsyncMock(),
    ) as mock_fetch:
        conn._handle_message({"type": "event", "event": "agent", "payload": payload})
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0.05))
        finally:
            loop.close()

    mock_fetch.assert_awaited()
    assert mock_fetch.call_args[0][1] == "user_bob"


def test_lifecycle_error_does_not_trigger_billing(conn):
    payload = {
        "runId": "run-4",
        "stream": "lifecycle",
        "data": {"phase": "error"},  # error, not end
        "sessionKey": "agent:main:telegram:main:direct:12345",
    }

    with patch.object(conn, "_fetch_and_record_usage", AsyncMock()) as mock_fetch:
        conn._handle_message({"type": "event", "event": "agent", "payload": payload})
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0.05))
        finally:
            loop.close()

    mock_fetch.assert_not_awaited()


def test_group_session_key_bills_under_owner_not_literal_channel(conn):
    """Regression: pre-existing parser bug wrote member:telegram:{period}."""
    payload = {
        "runId": "run-5",
        "stream": "lifecycle",
        "data": {"phase": "end"},
        "sessionKey": "agent:main:telegram:group:-100123",
    }

    with patch.object(conn, "_fetch_and_record_usage", AsyncMock()) as mock_fetch:
        conn._handle_message({"type": "event", "event": "agent", "payload": payload})
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0.05))
        finally:
            loop.close()

    mock_fetch.assert_awaited()
    # Must NOT be the literal 'telegram'
    assert mock_fetch.call_args[0][1] != "telegram"
    # Should fall back to owner
    assert mock_fetch.call_args[0][1] == "org_1"


def test_chat_final_no_longer_calls_billing(conn):
    """chat.final still fires UI signals but not billing (lifecycle is the new trigger)."""
    payload = {
        "sessionKey": "agent:main:main",
        "state": "final",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    }

    with patch.object(conn, "_fetch_and_record_usage", AsyncMock()) as mock_fetch, \
         patch.object(conn, "_forward_to_frontends") as mock_forward:
        conn._handle_message({"type": "event", "event": "chat", "payload": payload})

    # Billing NOT called from chat.final anymore
    mock_fetch.assert_not_awaited()
    # But UI signal IS forwarded ({"type": "done"})
    any_done = any(
        isinstance(c[0][0], dict) and c[0][0].get("type") == "done"
        for c in mock_forward.call_args_list
    )
    assert any_done
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/gateway/test_lifecycle_billing.py -v
```

Expected: FAIL — the lifecycle/end branch doesn't exist and `chat.final` still calls billing.

- [ ] **Step 3: Add `_resolve_member_from_session`, rewrite `_record_usage_from_session`, add the lifecycle branch, remove the chat.final billing call**

Edit `apps/backend/core/gateway/connection_pool.py` and make four changes:

**3a.** Add an import at the top (if not present):

```python
from core.repositories import channel_link_repo
```

**3b.** Add a new method `_resolve_member_from_session` inside the `GatewayConnection` class, right below the existing `_record_usage_from_session` method:

```python
    async def _resolve_member_from_session(self, parsed: dict) -> str:
        """Map a parsed session key to the Clerk member_id.

        Falls back to self.user_id (the owner) if no per-member attribution
        is available (unlinked DM, group, channel, webchat-personal, unknown).
        """
        if parsed.get("source") == "dm":
            link = await channel_link_repo.get_by_peer(
                owner_id=self.user_id,
                provider=parsed["channel"],
                agent_id=parsed["agent_id"],
                peer_id=parsed["peer_id"],
            )
            if link:
                return link.get("member_id", self.user_id)
            return self.user_id

        if parsed.get("source") == "webchat" and parsed.get("member_id"):
            return parsed["member_id"]

        return self.user_id
```

**3c.** Rewrite `_record_usage_from_session` to use the new parser and spawn a lookup-then-fetch task. Replace the entire existing body of `_record_usage_from_session` with:

```python
    def _record_usage_from_session(self, payload: dict) -> None:
        """Record usage after a billable event by resolving the session key
        to a member_id and querying session tokens.

        Triggered from the `agent` event lifecycle/end branch below (not
        from chat.final, which only fires for webchat and doesn't exist for
        channel-driven runs).
        """
        session_key = payload.get("sessionKey", "")
        if not session_key:
            logger.warning(
                "No sessionKey in billable event for user %s — cannot record usage",
                self.user_id,
            )
            return

        parsed = _parse_session_key(session_key)
        if not parsed:
            logger.warning(
                "Malformed sessionKey %r for user %s — cannot record usage",
                session_key, self.user_id,
            )
            return

        async def _resolve_then_record():
            member_id = await self._resolve_member_from_session(parsed)
            await self._fetch_and_record_usage(session_key, member_id)

        asyncio.create_task(_resolve_then_record())
```

**3d.** Add the lifecycle/end branch in `_handle_message`. Find the existing `elif event_name == "agent":` block (around line 451). Right **before** the `transformed = self._transform_agent_event(payload)` line, add:

```python
                # Billing: lifecycle/end fires once per completed agent run
                # for BOTH webchat and channel-driven runs (webchat's chat.final
                # only fires for webchat, so we use lifecycle/end instead).
                if (
                    stream == "lifecycle"
                    and isinstance(payload.get("data"), dict)
                    and payload["data"].get("phase") == "end"
                ):
                    self._record_usage_from_session(payload)
```

**3e.** Remove the `_record_usage_from_session(payload)` call from the `chat.final` branch. Find:

```python
                if state == "final":
                    ...
                    self._forward_to_frontends({"type": "done"})
                    # Record usage by querying session for token counts
                    self._record_usage_from_session(payload)
```

Delete the last two lines (the comment and the `_record_usage_from_session(payload)` call). The `chat.final` branch still fires `{"type": "done"}` to the frontend — we're only removing the billing call.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/gateway/test_lifecycle_billing.py tests/unit/gateway/test_session_key_parser.py -v
```

Expected: all tests PASS (12 parser + 6 billing).

Also run the existing connection_pool tests to make sure nothing else broke:

```bash
cd apps/backend && uv run pytest tests/unit/gateway/ -v 2>&1 | tail -30
```

Expected: no new failures.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/gateway/connection_pool.py apps/backend/tests/unit/gateway/test_lifecycle_billing.py
git commit -m "$(cat <<'EOF'
feat(backend): lifecycle/end billing trigger + per-member channel DM attribution

Switches the billing trigger from chat.final (webchat only) to agent
events with stream=lifecycle, phase=end (fires for all runs via the
unconditional broadcast at openclaw/src/gateway/server-chat.ts:936).

Adds _resolve_member_from_session which looks up the channel_link
row for DM sessions and falls back to owner_id for groups/channels/
webchat-personal/unknown. Org webchat sessions preserve per-member
attribution because the parser pulls the clerk user_id directly from
parts[2] of the session key.

Removes the chat.final → _record_usage_from_session call (billing is
now lifecycle-driven). chat.final still fires the UI {type: done}
signal for webchat streaming.

Also implicitly fixes the pre-existing parser bug that attributed
group sessions to the literal string "telegram".

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase G — Orphan sweep hooks

**Why now:** Links can become orphaned by three events: admin deletes a bot (handled in Phase E's admin delete endpoint — already does its own sweep), container is deleted entirely (`ecs_manager.delete_user_service`), or a Clerk user is deleted (`webhooks.py`). We wire up the last two.

### Task G1: Extend Clerk `user.deleted` webhook to sweep by member

**Files:**
- Modify: `apps/backend/routers/webhooks.py`
- Test: (inline assertion via a small test in `test_channels_link_router.py` — keep the test footprint small)

- [ ] **Step 1: Read the existing webhook handler to match the pattern**

```bash
grep -n "user.deleted\|user\\.deleted\|\"deleted\"" apps/backend/routers/webhooks.py
```

Find the Clerk webhook handler. It dispatches on event type (e.g., `user.created`, `user.updated`, `user.deleted`). We'll extend the `deleted` branch.

- [ ] **Step 2: Add the sweep call**

Edit `apps/backend/routers/webhooks.py`. Find the branch that handles `user.deleted` (look for a string match like `"user.deleted"` or an if-elif dispatch). Add the sweep call inside that branch:

```python
    from core.repositories import channel_link_repo
    count = await channel_link_repo.sweep_by_member(user_id)
    logger.info("Swept %d channel_link rows for deleted user %s", count, user_id)
```

Place it near the other deletion steps in the handler, before whatever the handler currently returns. Use whatever variable name the existing handler uses for the Clerk user id (probably `user_id` or `clerk_user_id` — match the existing code).

If the webhook handler file doesn't have a `user.deleted` branch at all (possible — the existing handler may only cover `user.created`/`user.updated`), add a new branch:

```python
    elif event_type == "user.deleted":
        user_id = data.get("id")
        if user_id:
            from core.repositories import channel_link_repo
            count = await channel_link_repo.sweep_by_member(user_id)
            logger.info(
                "Clerk user.deleted webhook: swept %d channel_link rows for %s",
                count, user_id,
            )
```

- [ ] **Step 3: Verify no tests broke**

```bash
cd apps/backend && uv run pytest tests/ -v 2>&1 | tail -20
```

Expected: no new failures.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/webhooks.py
git commit -m "$(cat <<'EOF'
feat(backend): sweep channel_links on Clerk user.deleted webhook

When a Clerk user is deleted, also delete every channel_link row
they own across all orgs they were a member of. Uses the by-member
GSI to find rows and BatchWriteItem to delete them in 25-row chunks.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task G2: Extend `ecs_manager.delete_user_service` to sweep by owner

**Files:**
- Modify: `apps/backend/core/containers/ecs_manager.py`

- [ ] **Step 1: Find the existing `delete_user_service` method**

```bash
grep -n "async def delete_user_service\|def delete_user_service" apps/backend/core/containers/ecs_manager.py
```

This method tears down a whole container (the ECS service, task definition, EFS access point, Container DB row). We add one more cleanup: sweep the `channel_links` rows for this owner.

- [ ] **Step 2: Add the sweep call**

In `apps/backend/core/containers/ecs_manager.py`, find `delete_user_service`. At the END of the method body (after all the ECS/EFS/DB cleanup but before any final `logger.info(...)` or `return`), add:

```python
        # Sweep channel_links rows for this owner
        try:
            from core.repositories import channel_link_repo
            link_count = await channel_link_repo.sweep_by_owner(user_id)
            if link_count:
                logger.info(
                    "Swept %d channel_link rows for deleted container (owner=%s)",
                    link_count, user_id,
                )
        except Exception:
            # Non-fatal — the container is already gone, orphan rows are
            # cheap to keep. Log and continue.
            logger.exception(
                "Failed to sweep channel_link rows for owner %s after container delete",
                user_id,
            )
```

- [ ] **Step 3: Run the existing ecs_manager tests to confirm nothing broke**

```bash
cd apps/backend && uv run pytest tests/ -k "ecs_manager or delete_user_service" -v 2>&1 | tail -20
```

Expected: same number of passes as before (the sweep wraps its own try/except so it can't regress the existing flow).

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/containers/ecs_manager.py
git commit -m "$(cat <<'EOF'
feat(backend): sweep channel_links on container teardown

When delete_user_service tears down a container, also sweep all
channel_link rows for that owner. Wrapped in try/except so orphan
sweep failures don't block container deletion.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase H — Initial openclaw.json defaults

**Why now:** All newly-provisioned containers should get `session.dmScope: "per-account-channel-peer"` by default, and the initial scaffold should drop WhatsApp. This is a one-file change to `core/containers/config.py` `write_openclaw_config`.

### Task H1: Set `session.dmScope` and drop WhatsApp from initial scaffold

**Files:**
- Modify: `apps/backend/core/containers/config.py`

- [ ] **Step 1: Find the initial channels scaffold**

```bash
grep -n "channels.*enabled.*false\|whatsapp\|dmPolicy" apps/backend/core/containers/config.py | head -20
```

Locate the block that writes `channels.telegram`, `channels.whatsapp`, `channels.discord` with `enabled: false`. Around line 468 based on the spec.

- [ ] **Step 2: Remove WhatsApp and add `session.dmScope`**

In `apps/backend/core/containers/config.py`, find the `"channels": { ... }` block in `write_openclaw_config`. Delete the `"whatsapp": { "enabled": False, "dmPolicy": "pairing" }` entry entirely.

In the same config dict, find the top-level keys (alongside `channels`, `agents`, `memory`, `tools`, etc.). Add a new `"session"` key:

```python
        "session": {
            "dmScope": "per-account-channel-peer",
        },
```

Place it near the other top-level keys alphabetically or match whatever ordering the existing file uses (the file already has `agents`, `memory`, `tools`, `channels`, etc. — add `session` near `agents` or wherever it fits).

- [ ] **Step 3: Verify the existing unit tests still pass**

If there are tests for `write_openclaw_config`:

```bash
cd apps/backend && uv run pytest tests/ -k "write_openclaw_config or containers_config" -v 2>&1 | tail -20
```

If a test explicitly asserts `channels.whatsapp` exists, **update the test** to remove that assertion (whatsapp is gone). If a test snapshot captures the full config dict, regenerate the snapshot.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/containers/config.py
git commit -m "$(cat <<'EOF'
feat(backend): set per-account-channel-peer dmScope, drop whatsapp scaffold

New containers are provisioned with session.dmScope="per-account-channel-peer"
so DMs from different senders get isolated session keys by default. The
initial channels scaffold also drops the whatsapp block entirely (whatsapp
is unsupported in this design).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase I — `BotSetupWizard` shared frontend component

**Why now:** Backend is done. The wizard is the shared React component used by both the Agents tab (create mode) and the Settings page (link-only mode). We build it in isolation with its tests before wiring it into either parent.

**What exists today:** `apps/frontend/src/lib/api.ts` has `useApi()` returning authenticated `{ get, post, patch, del }` helpers. `apps/frontend/src/hooks/useGatewayRpc.ts` has `useGatewayRpcMutation` for RPC calls (we'll use this only to poll `channels.status` during the wait-for-chokidar step — we use the new REST `PATCH /api/v1/config` for all writes, never the old `config.patch` RPC). The existing `ChannelsPanel.tsx` is a useful reference for how the existing code talks to the container, but we're NOT extending it — the wizard is a fresh component.

### Task I1: Wizard shell + token paste step ("create" mode)

**Files:**
- Create: `apps/frontend/src/components/channels/BotSetupWizard.tsx`
- Test: `apps/frontend/tests/unit/components/BotSetupWizard.test.tsx`

- [ ] **Step 1: Add the `patchConfig` helper to the API module**

Edit `apps/frontend/src/lib/api.ts`. Find the `useApi` hook and look for the existing `patch` method. Add a thin typed helper at the end of the returned object:

```typescript
    patchConfig: async (patch: Record<string, unknown>) => {
      return await doRequest<{ status: string; owner_id: string }>(
        "PATCH", "/config", { patch },
      );
    },
```

(If the existing module doesn't use a `doRequest` pattern, use whatever pattern the file uses to add a method that calls `PATCH /api/v1/config` with body `{patch: <the patch dict>}` and returns JSON.)

- [ ] **Step 2: Write a test for the shell + token paste step**

Create `apps/frontend/tests/unit/components/BotSetupWizard.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { BotSetupWizard } from "@/components/channels/BotSetupWizard";

vi.mock("@/lib/api", () => ({
  useApi: () => ({
    patchConfig: vi.fn().mockResolvedValue({ status: "patched", owner_id: "user_test" }),
    post: vi.fn().mockResolvedValue({ status: "linked", peer_id: "12345" }),
  }),
}));

vi.mock("@/hooks/useGatewayRpc", () => ({
  useGatewayRpcMutation: () => vi.fn().mockResolvedValue({ accounts: [{ connected: true }] }),
}));

describe("BotSetupWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the token paste step in create mode", () => {
    render(
      <BotSetupWizard
        mode="create"
        provider="telegram"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/bot token/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("enables the next button once a token is typed", async () => {
    const user = userEvent.setup();
    render(
      <BotSetupWizard
        mode="create"
        provider="telegram"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/bot token/i), "123:abcABC");
    expect(screen.getByRole("button", { name: /next/i })).toBeEnabled();
  });

  it("skips the token step in link-only mode", () => {
    render(
      <BotSetupWizard
        mode="link-only"
        provider="telegram"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText(/bot token/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/pairing code/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd apps/frontend && pnpm test BotSetupWizard -- --run
```

Expected: FAIL with `Cannot find module '@/components/channels/BotSetupWizard'`.

- [ ] **Step 4: Implement the component**

Create `apps/frontend/src/components/channels/BotSetupWizard.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";
import { useGatewayRpcMutation } from "@/hooks/useGatewayRpc";

type Provider = "telegram" | "discord" | "slack";
type Mode = "create" | "link-only";

export interface BotSetupWizardProps {
  mode: Mode;
  provider: Provider;
  agentId: string;
  onComplete: (result: { peer_id: string }) => void;
  onCancel: () => void;
}

type Step = "token" | "waiting" | "pair" | "done";

const PROVIDER_LABELS: Record<Provider, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
};

export function BotSetupWizard({
  mode,
  provider,
  agentId,
  onComplete,
  onCancel,
}: BotSetupWizardProps) {
  const api = useApi();
  const callRpc = useGatewayRpcMutation();

  const [step, setStep] = useState<Step>(mode === "create" ? "token" : "pair");
  const [token, setToken] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const label = PROVIDER_LABELS[provider];

  const handleTokenSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      // Build the config patch for this provider + agent
      const patch: Record<string, unknown> = {
        channels: {
          [provider]: {
            enabled: true,
            accounts: {
              [agentId]: {
                botToken: token.trim(),
                dmPolicy: "pairing",
              },
            },
          },
        },
      };
      await api.patchConfig(patch);
      setStep("waiting");
      // Poll channels.status until the account reports connected
      const deadline = Date.now() + 30_000;
      while (Date.now() < deadline) {
        try {
          const status = await callRpc("channels.status", { probe: false });
          const accounts =
            (status as { channelAccounts?: Record<string, { connected?: boolean }[]> })
              ?.channelAccounts?.[provider] ?? [];
          if (accounts.some((a) => a.connected)) {
            setStep("pair");
            return;
          }
        } catch {
          // fall through to retry
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
      setError("Container took too long to start the bot. Check the agent's channel status.");
      setStep("token");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStep("token");
    } finally {
      setBusy(false);
    }
  };

  const handleCodeSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{ status: string; peer_id: string }>(
        `/channels/link/${provider}/complete`,
        { agent_id: agentId, code: code.trim() },
      );
      setStep("done");
      onComplete({ peer_id: result.peer_id });
    } catch (e) {
      const err = e as { status?: number; message?: string };
      if (err.status === 404) {
        setError("Code expired or not found. DM the bot again and try a new code.");
      } else if (err.status === 409) {
        setError("This account is already linked to another member.");
      } else {
        setError(err.message || String(e));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 space-y-4 max-w-md">
      <h3 className="text-lg font-semibold">
        {mode === "create" ? `Set up ${label} bot` : `Link your ${label} identity`}
      </h3>

      {step === "token" && (
        <div className="space-y-3">
          <label className="block text-sm font-medium">
            {label} bot token
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={provider === "telegram" ? "123456:ABC-DEF..." : "token..."}
              className="mt-1 w-full rounded-md border border-[#e0dbd0] bg-white px-3 py-2 text-sm font-mono"
            />
          </label>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex gap-2">
            <Button variant="outline" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={handleTokenSubmit} disabled={busy || !token.trim()}>
              {busy && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
              Next
            </Button>
          </div>
        </div>
      )}

      {step === "waiting" && (
        <div className="flex items-center gap-2 text-sm text-[#8a8578]">
          <Loader2 className="h-4 w-4 animate-spin" />
          Starting your bot...
        </div>
      )}

      {step === "pair" && (
        <div className="space-y-3">
          <p className="text-sm">
            DM your {label} bot from your phone. It will reply with an 8-character code.
            Paste it below within 1 hour.
          </p>
          <label className="block text-sm font-medium">
            Pairing code
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="ABC12345"
              className="mt-1 w-full rounded-md border border-[#e0dbd0] bg-white px-3 py-2 text-sm font-mono"
            />
          </label>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex gap-2">
            <Button variant="outline" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={handleCodeSubmit} disabled={busy || code.length < 4}>
              {busy && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
              Link
            </Button>
          </div>
        </div>
      )}

      {step === "done" && (
        <p className="text-sm text-[#2d8a4e]">✅ Linked.</p>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run the tests and commit**

```bash
cd apps/frontend && pnpm test BotSetupWizard -- --run
```

Expected: 3 tests PASS.

```bash
git add apps/frontend/src/components/channels/BotSetupWizard.tsx apps/frontend/tests/unit/components/BotSetupWizard.test.tsx apps/frontend/src/lib/api.ts
git commit -m "$(cat <<'EOF'
feat(frontend): BotSetupWizard shared component

Shared wizard with two modes: "create" (admin path — paste token →
wait for chokidar → paste pairing code) and "link-only" (member path
— paste pairing code only). Uses the new PATCH /api/v1/config REST
endpoint (not the OpenClaw config.patch RPC) and POST /channels/link/
{provider}/complete for the link step.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task I2: Wizard error handling tests

**Files:**
- Modify: `apps/frontend/tests/unit/components/BotSetupWizard.test.tsx`

- [ ] **Step 1: Add tests for the 404 and 409 error paths**

Append to `apps/frontend/tests/unit/components/BotSetupWizard.test.tsx`:

```tsx
  it("shows friendly message on 404 code not found", async () => {
    const post = vi.fn().mockRejectedValue({ status: 404, message: "not found" });
    vi.doMock("@/lib/api", () => ({
      useApi: () => ({ patchConfig: vi.fn(), post }),
    }));
    const { BotSetupWizard: Wiz } = await import("@/components/channels/BotSetupWizard");
    render(
      <Wiz
        mode="link-only" provider="telegram" agentId="main"
        onComplete={vi.fn()} onCancel={vi.fn()}
      />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/pairing code/i), "BADCODE");
    await user.click(screen.getByRole("button", { name: /link/i }));
    await waitFor(() => {
      expect(screen.getByText(/code expired or not found/i)).toBeInTheDocument();
    });
  });

  it("shows friendly message on 409 peer already linked", async () => {
    const post = vi.fn().mockRejectedValue({ status: 409, message: "conflict" });
    vi.doMock("@/lib/api", () => ({
      useApi: () => ({ patchConfig: vi.fn(), post }),
    }));
    const { BotSetupWizard: Wiz } = await import("@/components/channels/BotSetupWizard");
    render(
      <Wiz
        mode="link-only" provider="telegram" agentId="main"
        onComplete={vi.fn()} onCancel={vi.fn()}
      />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/pairing code/i), "ABC12345");
    await user.click(screen.getByRole("button", { name: /link/i }));
    await waitFor(() => {
      expect(screen.getByText(/already linked to another member/i)).toBeInTheDocument();
    });
  });
```

- [ ] **Step 2: Run the tests to verify they pass**

```bash
cd apps/frontend && pnpm test BotSetupWizard -- --run
```

Expected: 5 tests PASS total.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/tests/unit/components/BotSetupWizard.test.tsx
git commit -m "$(cat <<'EOF'
test(frontend): BotSetupWizard 404 and 409 error paths

Asserts the wizard shows user-friendly messages for pairing code
expired/not found (404) and peer already linked to another member
(409) instead of raw API errors.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task I3: Slack-specific token fields + static manifest

**Why:** Slack apps in Socket Mode need TWO tokens (`xapp-...` app-level token and `xoxb-...` bot token), not one. The wizard also needs to surface a static manifest the user copies into `api.slack.com/apps?new_app=1`. This is the only provider-specific branch in the wizard; Telegram and Discord stay single-token.

**Files:**
- Modify: `apps/frontend/src/components/channels/BotSetupWizard.tsx`
- Modify: `apps/frontend/tests/unit/components/BotSetupWizard.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `apps/frontend/tests/unit/components/BotSetupWizard.test.tsx`:

```tsx
  it("shows TWO token fields plus a manifest block when provider is slack", () => {
    render(
      <BotSetupWizard
        mode="create"
        provider="slack"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/app.level token/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/bot token/i)).toBeInTheDocument();
    // Manifest instructions visible
    expect(screen.getByText(/paste.*manifest.*slack/i)).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && pnpm test BotSetupWizard -- --run -t "slack"
```

Expected: FAIL — the wizard doesn't have a Slack branch yet.

- [ ] **Step 3: Add the Slack branch**

Edit `apps/frontend/src/components/channels/BotSetupWizard.tsx`. Above the component, add the static manifest constant:

```tsx
const SLACK_APP_MANIFEST = `display_information:
  name: Isol8 Agent
features:
  bot_user:
    display_name: Isol8 Agent
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - chat:write
      - im:history
      - im:read
      - im:write
      - users:read
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.im
  socket_mode_enabled: true`;
```

Then add state for the second Slack token:

```tsx
  const [slackAppToken, setSlackAppToken] = useState("");
```

Modify `handleTokenSubmit` to write both tokens when provider is `slack`:

```tsx
  const handleTokenSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      const accountCfg: Record<string, unknown> =
        provider === "slack"
          ? {
              mode: "socket",
              appToken: slackAppToken.trim(),
              botToken: token.trim(),
              dmPolicy: "pairing",
            }
          : {
              botToken: token.trim(),
              dmPolicy: "pairing",
            };
      const patch: Record<string, unknown> = {
        channels: {
          [provider]: {
            enabled: true,
            accounts: {
              [agentId]: accountCfg,
            },
          },
        },
      };
      await api.patchConfig(patch);
      setStep("waiting");
      // ... rest of the existing handleTokenSubmit unchanged
```

Replace the token step JSX with a provider-aware version. Update the `{step === "token" && ...}` block:

```tsx
      {step === "token" && (
        <div className="space-y-3">
          {provider === "slack" && (
            <div className="rounded-md bg-[#f3efe6] p-3 text-xs space-y-2">
              <p className="font-semibold">Paste this manifest when creating a new Slack app:</p>
              <pre className="whitespace-pre-wrap font-mono text-[10px] bg-white p-2 rounded border border-[#e0dbd0]">
                {SLACK_APP_MANIFEST}
              </pre>
              <p>
                Go to{" "}
                <a
                  href="https://api.slack.com/apps?new_app=1"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                >
                  api.slack.com/apps
                </a>
                , choose "From an app manifest", paste the above, install to your workspace,
                then copy the two tokens below.
              </p>
            </div>
          )}
          {provider === "slack" && (
            <label className="block text-sm font-medium">
              App-Level Token (xapp-...)
              <input
                type="password"
                value={slackAppToken}
                onChange={(e) => setSlackAppToken(e.target.value)}
                placeholder="xapp-..."
                className="mt-1 w-full rounded-md border border-[#e0dbd0] bg-white px-3 py-2 text-sm font-mono"
              />
            </label>
          )}
          <label className="block text-sm font-medium">
            {provider === "slack" ? "Bot Token (xoxb-...)" : `${label} bot token`}
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={
                provider === "telegram"
                  ? "123456:ABC-DEF..."
                  : provider === "slack"
                    ? "xoxb-..."
                    : "token..."
              }
              className="mt-1 w-full rounded-md border border-[#e0dbd0] bg-white px-3 py-2 text-sm font-mono"
            />
          </label>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex gap-2">
            <Button variant="outline" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button
              onClick={handleTokenSubmit}
              disabled={
                busy
                || !token.trim()
                || (provider === "slack" && !slackAppToken.trim())
              }
            >
              {busy && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
              Next
            </Button>
          </div>
        </div>
      )}
```

- [ ] **Step 4: Run all wizard tests to verify they pass**

```bash
cd apps/frontend && pnpm test BotSetupWizard -- --run
```

Expected: all 6 tests PASS (3 from I1 + 2 from I2 + 1 from I3).

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/channels/BotSetupWizard.tsx apps/frontend/tests/unit/components/BotSetupWizard.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): BotSetupWizard Slack branch — two tokens + static manifest

Slack apps in Socket Mode need an App-Level Token (xapp-...) AND a
Bot Token (xoxb-...), not just one. The wizard shows both fields plus
a static YAML manifest the user pastes into api.slack.com/apps during
app creation. Telegram and Discord are unchanged — single token field.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase J — `AgentChannelsSection` component

**Why now:** Per-agent admin section that renders inside the Agents tab's agent detail view. Uses the `BotSetupWizard` from Phase I.

### Task J1: Build `AgentChannelsSection` + tests

**Files:**
- Create: `apps/frontend/src/components/control/panels/AgentChannelsSection.tsx`
- Test: `apps/frontend/tests/unit/components/AgentChannelsSection.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `apps/frontend/tests/unit/components/AgentChannelsSection.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { AgentChannelsSection } from "@/components/control/panels/AgentChannelsSection";

const mockData = {
  telegram: [{ agent_id: "main", bot_username: "main", linked: true }],
  discord: [],
  slack: [],
  can_create_bots: true,
};

vi.mock("swr", async () => {
  const actual = await vi.importActual<typeof import("swr")>("swr");
  return {
    ...actual,
    default: () => ({ data: mockData, error: null, isLoading: false, mutate: vi.fn() }),
  };
});

vi.mock("@/lib/api", () => ({
  useApi: () => ({
    get: vi.fn().mockResolvedValue(mockData),
    del: vi.fn(),
  }),
}));

describe("AgentChannelsSection", () => {
  it("renders telegram, discord, and slack (no whatsapp)", () => {
    render(<AgentChannelsSection agentId="main" />);
    expect(screen.getByText(/telegram/i)).toBeInTheDocument();
    expect(screen.getByText(/discord/i)).toBeInTheDocument();
    expect(screen.getByText(/slack/i)).toBeInTheDocument();
    expect(screen.queryByText(/whatsapp/i)).not.toBeInTheDocument();
  });

  it("shows add-bot buttons when can_create_bots is true", () => {
    render(<AgentChannelsSection agentId="main" />);
    expect(screen.getAllByRole("button", { name: /add.*bot/i }).length).toBeGreaterThan(0);
  });

  it("hides add-bot buttons for non-admin members", async () => {
    const { AgentChannelsSection: Section } = await import(
      "@/components/control/panels/AgentChannelsSection"
    );
    vi.doMock("swr", () => ({
      default: () => ({
        data: { ...mockData, can_create_bots: false },
        error: null,
        isLoading: false,
        mutate: vi.fn(),
      }),
    }));
    render(<Section agentId="main" />);
    expect(screen.queryByRole("button", { name: /add.*bot/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && pnpm test AgentChannelsSection -- --run
```

Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement the component**

Create `apps/frontend/src/components/control/panels/AgentChannelsSection.tsx`:

```tsx
"use client";

import { useState } from "react";
import useSWR from "swr";
import { Plus, Trash2, CheckCircle2, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";
import { BotSetupWizard } from "@/components/channels/BotSetupWizard";

type Provider = "telegram" | "discord" | "slack";

interface BotEntry {
  agent_id: string;
  bot_username: string;
  linked: boolean;
}

interface LinksMeResponse {
  telegram: BotEntry[];
  discord: BotEntry[];
  slack: BotEntry[];
  can_create_bots: boolean;
}

interface AgentChannelsSectionProps {
  agentId: string;
}

const PROVIDERS: Provider[] = ["telegram", "discord", "slack"];
const PROVIDER_LABELS: Record<Provider, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
};

export function AgentChannelsSection({ agentId }: AgentChannelsSectionProps) {
  const api = useApi();
  const { data, mutate } = useSWR<LinksMeResponse>(
    "/channels/links/me",
    () => api.get<LinksMeResponse>("/channels/links/me"),
  );
  const [wizardFor, setWizardFor] = useState<Provider | null>(null);

  if (!data) {
    return <div className="p-4 text-sm text-[#8a8578]">Loading channels…</div>;
  }

  const handleDelete = async (provider: Provider) => {
    if (!confirm(`Delete the ${PROVIDER_LABELS[provider]} bot for this agent? This cannot be undone.`)) {
      return;
    }
    await api.del(`/channels/${provider}/${agentId}`);
    mutate();
  };

  return (
    <div className="space-y-4 p-4">
      <h3 className="text-sm font-semibold">Channels</h3>
      {PROVIDERS.map((provider) => {
        const bots = data[provider].filter((b) => b.agent_id === agentId);
        return (
          <div key={provider} className="rounded-md border border-[#e0dbd0] p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-[#8a8578]">
                {PROVIDER_LABELS[provider]}
              </span>
            </div>
            {bots.length === 0 ? (
              <p className="text-xs text-[#8a8578]">No bot configured</p>
            ) : (
              bots.map((bot) => (
                <div key={bot.agent_id} className="flex items-center gap-2 text-sm">
                  {bot.linked ? (
                    <CheckCircle2 className="h-4 w-4 text-[#2d8a4e]" />
                  ) : (
                    <AlertCircle className="h-4 w-4 text-amber-500" />
                  )}
                  <span className="font-mono">@{bot.bot_username}</span>
                  <div className="flex-1" />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDelete(provider)}
                    aria-label={`Delete ${provider} bot`}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              ))
            )}
            {data.can_create_bots && bots.length === 0 && (
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => setWizardFor(provider)}
              >
                <Plus className="h-3 w-3 mr-1" />
                Add {PROVIDER_LABELS[provider]} bot
              </Button>
            )}
          </div>
        );
      })}

      {wizardFor && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl">
            <BotSetupWizard
              mode="create"
              provider={wizardFor}
              agentId={agentId}
              onComplete={() => {
                setWizardFor(null);
                mutate();
              }}
              onCancel={() => setWizardFor(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests and commit**

```bash
cd apps/frontend && pnpm test AgentChannelsSection -- --run
```

Expected: 3 tests PASS.

```bash
git add apps/frontend/src/components/control/panels/AgentChannelsSection.tsx apps/frontend/tests/unit/components/AgentChannelsSection.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): AgentChannelsSection admin component

Per-agent admin section for channel bot configuration. Lists telegram,
discord, slack (no whatsapp). Renders BotSetupWizard in create mode
when admin clicks "Add bot". Hides all add-bot buttons when the caller
is an org member without admin rights.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase K — `MyChannelsSection` settings component

### Task K1: Build `MyChannelsSection` + tests

**Files:**
- Create: `apps/frontend/src/components/settings/MyChannelsSection.tsx`
- Test: `apps/frontend/tests/unit/components/MyChannelsSection.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `apps/frontend/tests/unit/components/MyChannelsSection.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { MyChannelsSection } from "@/components/settings/MyChannelsSection";

const mockData = {
  telegram: [
    { agent_id: "main", bot_username: "main", linked: true },
    { agent_id: "sales", bot_username: "sales", linked: false },
  ],
  discord: [],
  slack: [],
  can_create_bots: false,
};

vi.mock("swr", async () => {
  const actual = await vi.importActual<typeof import("swr")>("swr");
  return {
    ...actual,
    default: () => ({ data: mockData, error: null, isLoading: false, mutate: vi.fn() }),
  };
});

vi.mock("@/lib/api", () => ({
  useApi: () => ({
    get: vi.fn().mockResolvedValue(mockData),
    del: vi.fn(),
  }),
}));

describe("MyChannelsSection", () => {
  it("lists bots grouped by provider", () => {
    render(<MyChannelsSection />);
    expect(screen.getByText(/telegram/i)).toBeInTheDocument();
    expect(screen.getByText(/@main/)).toBeInTheDocument();
    expect(screen.getByText(/@sales/)).toBeInTheDocument();
  });

  it("shows Link button for unlinked bots", () => {
    render(<MyChannelsSection />);
    expect(screen.getByRole("button", { name: /link/i })).toBeInTheDocument();
  });

  it("shows Unlink for linked bots", () => {
    render(<MyChannelsSection />);
    expect(screen.getByRole("button", { name: /unlink/i })).toBeInTheDocument();
  });

  it("shows empty state with Agents-tab hint for non-admin members", () => {
    render(<MyChannelsSection />);
    // Discord has no bots and can_create_bots is false
    expect(screen.getByText(/no discord bots/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && pnpm test MyChannelsSection -- --run
```

Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement the component**

Create `apps/frontend/src/components/settings/MyChannelsSection.tsx`:

```tsx
"use client";

import { useState } from "react";
import useSWR from "swr";
import { CheckCircle2, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";
import { BotSetupWizard } from "@/components/channels/BotSetupWizard";

type Provider = "telegram" | "discord" | "slack";

interface BotEntry {
  agent_id: string;
  bot_username: string;
  linked: boolean;
}

interface LinksMeResponse {
  telegram: BotEntry[];
  discord: BotEntry[];
  slack: BotEntry[];
  can_create_bots: boolean;
}

const PROVIDERS: Provider[] = ["telegram", "discord", "slack"];
const PROVIDER_LABELS: Record<Provider, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
};

export function MyChannelsSection() {
  const api = useApi();
  const { data, mutate } = useSWR<LinksMeResponse>(
    "/channels/links/me",
    () => api.get<LinksMeResponse>("/channels/links/me"),
  );
  const [wizard, setWizard] = useState<{ provider: Provider; agentId: string } | null>(null);

  if (!data) {
    return <div className="p-4 text-sm text-[#8a8578]">Loading…</div>;
  }

  const handleUnlink = async (provider: Provider, agentId: string) => {
    if (!confirm(`Unlink your ${PROVIDER_LABELS[provider]} from this bot?`)) return;
    await api.del(`/channels/link/${provider}/${agentId}`);
    mutate();
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">My Channels</h2>
        <p className="text-xs text-[#8a8578]">
          Link your Telegram, Discord, and Slack identities to your organization's bots.
        </p>
      </div>

      {PROVIDERS.map((provider) => {
        const bots = data[provider];
        return (
          <div key={provider} className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-[#8a8578]">
              {PROVIDER_LABELS[provider]}
            </h3>
            {bots.length === 0 ? (
              <div className="rounded-md border border-[#e0dbd0] p-3 text-xs text-[#8a8578]">
                No {PROVIDER_LABELS[provider]} bots set up in this container.
                {data.can_create_bots && " Set one up from your agent's Channels tab."}
              </div>
            ) : (
              <div className="space-y-2">
                {bots.map((bot) => (
                  <div
                    key={bot.agent_id}
                    className="flex items-center gap-3 rounded-md border border-[#e0dbd0] p-3"
                  >
                    {bot.linked ? (
                      <CheckCircle2 className="h-4 w-4 text-[#2d8a4e]" />
                    ) : (
                      <AlertCircle className="h-4 w-4 text-amber-500" />
                    )}
                    <div className="flex-1">
                      <p className="text-sm font-mono">@{bot.bot_username}</p>
                      <p className="text-xs text-[#8a8578]">{bot.agent_id} agent</p>
                    </div>
                    {bot.linked ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleUnlink(provider, bot.agent_id)}
                      >
                        Unlink
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => setWizard({ provider, agentId: bot.agent_id })}
                      >
                        Link
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {wizard && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl">
            <BotSetupWizard
              mode="link-only"
              provider={wizard.provider}
              agentId={wizard.agentId}
              onComplete={() => {
                setWizard(null);
                mutate();
              }}
              onCancel={() => setWizard(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests and commit**

```bash
cd apps/frontend && pnpm test MyChannelsSection -- --run
```

Expected: 4 tests PASS.

```bash
git add apps/frontend/src/components/settings/MyChannelsSection.tsx apps/frontend/tests/unit/components/MyChannelsSection.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): MyChannelsSection for per-member identity linking

Settings page section listing all bots in the user's container grouped
by provider, with per-bot Link/Unlink buttons. Uses BotSetupWizard in
link-only mode. Shows empty-state hint for providers with no bots,
pointing org admins to the Agents tab.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase L — Integration wiring

**Why now:** Phase I, J, K built the components in isolation. Now wire them into the parent pages.

### Task L1: Render `AgentChannelsSection` inside `AgentsPanel`

**Files:**
- Modify: `apps/frontend/src/components/control/panels/AgentsPanel.tsx`

- [ ] **Step 1: Find the agent detail view**

```bash
grep -n "selectedAgent\|AgentDetail\|<div.*agent" apps/frontend/src/components/control/panels/AgentsPanel.tsx | head -20
```

Locate where the panel renders the detail view for a selected agent. Inside that section, we'll add the channels component.

- [ ] **Step 2: Import and render**

Add import at the top of `apps/frontend/src/components/control/panels/AgentsPanel.tsx`:

```tsx
import { AgentChannelsSection } from "./AgentChannelsSection";
```

Then, in the agent detail section, after the existing agent settings (name/model/instructions/etc.), add:

```tsx
<AgentChannelsSection agentId={selectedAgent.id} />
```

(Use whatever variable name the existing code uses for the selected agent — could be `activeAgent`, `currentAgent`, `agent`, etc. Match the existing code.)

- [ ] **Step 3: Smoke test that the frontend still builds**

```bash
cd apps/frontend && pnpm run build 2>&1 | tail -20
```

Expected: build succeeds (no TypeScript errors).

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/control/panels/AgentsPanel.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): render AgentChannelsSection in AgentsPanel detail view

Wires the per-agent channels admin section into the Agents tab's
selected-agent detail view.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task L2: Render `MyChannelsSection` in the Settings page

**Files:**
- Modify: `apps/frontend/src/app/settings/page.tsx`

- [ ] **Step 1: Import and render**

Edit `apps/frontend/src/app/settings/page.tsx`. Add import:

```tsx
import { MyChannelsSection } from "@/components/settings/MyChannelsSection";
```

Find where the page renders its settings sections (keys, billing, etc.) and add:

```tsx
<MyChannelsSection />
```

Place it adjacent to the other per-user sections (BYOK keys, billing). Match the existing section layout / spacing.

- [ ] **Step 2: Smoke test + commit**

```bash
cd apps/frontend && pnpm run build 2>&1 | tail -10
```

Expected: build succeeds.

```bash
git add apps/frontend/src/app/settings/page.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): render MyChannelsSection in settings page

Adds the per-member channel linking section to the user's Settings
page, next to the existing key management and billing sections.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task L3: Replace the channel step in `ProvisioningStepper` with `BotSetupWizard`

**Files:**
- Modify: `apps/frontend/src/components/chat/ProvisioningStepper.tsx`

- [ ] **Step 1: Find the existing channel step**

```bash
grep -n "ChannelSetupStep\|channel.*step\|provisioning.*channel" apps/frontend/src/components/chat/ProvisioningStepper.tsx | head -10
```

Find the step in the provisioning flow that prompts for channel setup. We replace its inner content with `BotSetupWizard` in create mode, targeting the `main` agent.

- [ ] **Step 2: Replace the content**

Edit `apps/frontend/src/components/chat/ProvisioningStepper.tsx`. Find the component or JSX block for the channels onboarding step. Replace its body with:

```tsx
<BotSetupWizard
  mode="create"
  provider="telegram"
  agentId="main"
  onComplete={() => goToNextStep()}
  onCancel={() => goToNextStep()}  // channel setup is optional
/>
```

Adjust `goToNextStep` to match whatever the existing stepper uses to advance. Import the wizard at the top:

```tsx
import { BotSetupWizard } from "@/components/channels/BotSetupWizard";
```

- [ ] **Step 3: Smoke test + commit**

```bash
cd apps/frontend && pnpm run build 2>&1 | tail -10
```

Expected: build succeeds.

```bash
git add apps/frontend/src/components/chat/ProvisioningStepper.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): use BotSetupWizard in ProvisioningStepper channel step

Replaces the standalone channel onboarding step with the shared
BotSetupWizard component (create mode, targeting the auto-created
main agent). First-time users get walked through Telegram setup
as part of their onboarding flow.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase M — Migrate all `config.patch` RPC callers

**Why now:** The backend `PATCH /api/v1/config` endpoint (Phase D) is ready, and the new wizard already uses it. This phase cleans up the legacy call sites so all frontend config writes go through one path.

### Task M1: Find and replace all `config.patch` RPC callers

**Files:**
- Modify: any file that calls `useGatewayRpcMutation("config.patch", ...)` or `callRpc("config.patch", ...)`

- [ ] **Step 1: Find all call sites**

```bash
grep -rn '"config.patch"' apps/frontend/src 2>&1 | grep -v "\.test\." | head -20
```

List every file that references the `config.patch` RPC. Expected call sites (may vary):
- `apps/frontend/src/components/control/panels/ChannelsPanel.tsx` (about to be deleted in Phase N — skip if you're deleting it in the same phase)
- `apps/frontend/src/components/chat/ChannelCards.tsx` (about to be deleted in Phase N — skip if deleting)
- Possibly others in control panels (config editor, allowlist management, etc.)

- [ ] **Step 2: Migrate each call site**

For each call site that is NOT being deleted in Phase N, replace the pattern:

```tsx
const callRpc = useGatewayRpcMutation();
await callRpc("config.patch", { raw: JSON.stringify(patch), baseHash: snapshot.hash });
```

with:

```tsx
const api = useApi();
await api.patchConfig(patch);
```

Remove `useGatewayRpcMutation` imports where no longer needed. Adjust error handling — the REST endpoint returns 403 for free-tier-channels and org-member-without-admin; surface these as friendly messages where appropriate.

- [ ] **Step 3: Smoke test + commit**

```bash
cd apps/frontend && pnpm run build 2>&1 | tail -20
cd apps/frontend && pnpm test -- --run 2>&1 | tail -20
```

Expected: build succeeds, no new test failures.

```bash
git add apps/frontend/src/
git commit -m "$(cat <<'EOF'
refactor(frontend): migrate all config.patch RPC callers to PATCH /api/v1/config

Replaces every direct use of OpenClaw's config.patch RPC with the new
REST endpoint that wraps patch_openclaw_config on EFS. Single code
path for frontend config writes, independent of gateway WS health.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase N — Final cleanup

### Task N1: Delete legacy files + register webhook handler + remove Channels sidebar nav

**Files:**
- Delete: `apps/frontend/src/components/control/panels/ChannelsPanel.tsx`
- Delete: `apps/frontend/src/components/chat/ChannelCards.tsx`
- Delete: `apps/backend/core/services/__pycache__/usage_poller.cpython-312.pyc`
- Modify: `apps/frontend/src/components/control/ControlPanelRouter.tsx` (remove Channels route)
- Modify: `apps/frontend/src/components/control/ControlSidebar.tsx` (remove Channels nav item)

- [ ] **Step 1: Delete the legacy files**

```bash
rm apps/frontend/src/components/control/panels/ChannelsPanel.tsx
rm apps/frontend/src/components/chat/ChannelCards.tsx
rm -f apps/backend/core/services/__pycache__/usage_poller.cpython-312.pyc
```

- [ ] **Step 2: Remove imports and references**

In `apps/frontend/src/components/control/ControlPanelRouter.tsx`, find and delete:
- The `import { ChannelsPanel } ...` line
- The route branch that renders `<ChannelsPanel />` (typically a case in a switch or an if-branch)

In `apps/frontend/src/components/control/ControlSidebar.tsx`, find and delete:
- The nav entry for Channels (icon + label + onClick handler)

Also check for any remaining imports of `ChannelCards`:

```bash
grep -rn "ChannelCards\|ChannelsPanel" apps/frontend/src 2>&1 | grep -v "\.bak"
```

Expected output: empty (every reference is gone). If any remain, delete them.

- [ ] **Step 3: Build the frontend to catch any missed references**

```bash
cd apps/frontend && pnpm run build 2>&1 | tail -30
```

Expected: build succeeds. If TypeScript complains about missing imports, fix them by removing the orphaned references.

- [ ] **Step 4: Run the full backend + frontend test suites**

```bash
cd apps/backend && uv run pytest tests/ -v 2>&1 | tail -20
cd apps/frontend && pnpm test -- --run 2>&1 | tail -20
```

Expected: all tests pass. Investigate any failures — do NOT commit until green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore: remove legacy ChannelsPanel, ChannelCards, and stale usage_poller cache

- Deletes the standalone ChannelsPanel (control sidebar) and ChannelCards
  (chat onboarding) — replaced by AgentChannelsSection and MyChannelsSection.
- Removes the Channels route + sidebar nav entry.
- Deletes the stale usage_poller.pyc cache file (source was removed in an
  earlier DynamoDB migration but the .pyc lingered).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

After all phases are complete, run the full test suite and spot-check the manual checklist from the spec:

```bash
# Backend
cd apps/backend && uv run pytest tests/ -v

# Frontend
cd apps/frontend && pnpm test -- --run
cd apps/frontend && pnpm run build

# Lint
cd apps/frontend && pnpm run lint
```

Then work through the manual checklist from the spec's "Manual verification checklist" section against a real dev container. Every item MUST pass before merging to `main`.

**Specifically:**
- Set up a Telegram bot for a personal user end-to-end
- Add a second bot (Discord or Slack) to the same user
- Sign in as an org admin, set up bots for two agents, confirm routing works
- Sign in as an org member, self-link via Settings, confirm usage attribution
- Downgrade a Pro user to Free, verify the container scales down and bots stop, re-upgrade and verify they resume without re-linking
- Send a message in a Telegram group with the bot, check usage records, confirm `member_id == owner_id` (NOT the literal `"telegram"` string)
- Have two org members chat via the in-app webchat, verify per-member billing still works

If any manual check fails, STOP and debug before merging. Don't "fix it later."








