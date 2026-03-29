# Organization Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable Clerk organizations to share a single OpenClaw container, workspace, and billing, with role-based permissions (admin vs member).

**Architecture:** Introduce an `owner_id` abstraction — `org_id` when in org context, `user_id` when personal. All container, EFS, and gateway lookups switch from bare `user_id` to `owner_id`. The DynamoDB containers table PK (`user_id`) is reused as `owner_id` with no schema migration. Session keys include `user_id` for conversation isolation. The gateway pool indexes by `owner_id` so all org members share one connection to one container.

**Tech Stack:** Python/FastAPI (backend), AWS CDK/DynamoDB/ECS/EFS (infra), Next.js 16/Clerk/React (frontend)

**Worktree:** `/Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support` (branch: `feature/org-support`)

---

## Key Design Decisions

1. **`owner_id` pattern:** `resolve_owner_id(auth) -> str` returns `auth.org_id` if org context, else `auth.user_id`. Every container/workspace/pool lookup uses this instead of `user_id`.
2. **No DynamoDB schema migration:** The containers table PK field is named `user_id` but will hold `owner_id` values (org_id for orgs, user_id for personal). Add `owner_type` attribute to distinguish.
3. **Session isolation:** For **org contexts only**, chat session key uses `agent:{agent_id}:{user_id}` to silo conversations per member. Personal users keep `agent:{agent_id}:main` — no history breakage.
4. **Gateway pool fan-out:** Pool keys by `owner_id`. All org members' frontend connections live under the same `owner_id` key. Agent events fan out to ALL connected org members.
5. **Permissions:** `require_org_admin` decorator for admin-only endpoints. No new Clerk config needed — roles already flow through JWT.
6. **EFS paths stay under `/users/`:** The EFS access point root stays at `/users/{owner_id}` for both personal and org containers. The `workspace.py` module is already parameterized by ID string and works transparently. No need for a separate `/orgs/` namespace — the access point provides isolation.
7. **`x-forwarded-user` header:** For org containers, OpenClaw sees the `owner_id` (org_id) as the user identity. This is correct — the container is the org's container. Usage tracking uses `owner_id` for billing attribution (billed to the org). Per-member usage breakdowns are a future enhancement.
8. **All routers updated:** Every router that resolves a container or writes to EFS must use `resolve_owner_id(auth)` instead of `auth.user_id`. This includes: `container_rpc.py`, `websocket_chat.py`, `debug.py`, `container.py` (status/retry), `channels.py`, `integrations.py`, `control_ui_proxy.py`, `settings_keys.py`.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `apps/backend/core/auth.py` | Modify | Add `resolve_owner_id()`, `require_org_admin` dependency |
| `apps/backend/core/repositories/container_repo.py` | Modify | Add `get_by_owner_id()` alias, `owner_type`/`org_id` fields |
| `apps/backend/core/containers/ecs_manager.py` | Modify | Accept `owner_id` + `owner_type` throughout lifecycle |
| `apps/backend/core/containers/workspace.py` | No change | Already parameterized by ID string — passes through |
| `apps/backend/core/containers/config.py` | No change | Config generation is ID-agnostic |
| `apps/backend/core/gateway/connection_pool.py` | Modify | Key pool by `owner_id`, fix stale `_device_identities` ref |
| `apps/backend/routers/websocket_chat.py` | Modify | Resolve `owner_id` from connection, org-aware routing |
| `apps/backend/routers/container_rpc.py` | Modify | Resolve container by `owner_id` |
| `apps/backend/routers/container.py` | Modify | Status/retry endpoints use `resolve_owner_id` |
| `apps/backend/routers/channels.py` | Modify | Channel RPC uses `resolve_owner_id` |
| `apps/backend/routers/integrations.py` | Modify | MCP server CRUD uses `resolve_owner_id`, admin-gated writes |
| `apps/backend/routers/control_ui_proxy.py` | Modify | Control UI proxy uses `resolve_owner_id` |
| `apps/backend/routers/settings_keys.py` | Modify | API key CRUD uses `resolve_owner_id`, admin-gated writes |
| `apps/backend/core/services/connection_service.py` | No change | Already stores `org_id` |
| `apps/infra/lib/stacks/database-stack.ts` | Modify | Add `owner-type-index` GSI |
| `apps/frontend/src/lib/api.ts` | No change | Auth header already carries org context via Clerk JWT |
| `apps/frontend/src/hooks/useGateway.tsx` | No change | WebSocket token carries org claims automatically |
| `apps/frontend/src/components/chat/ChatLayout.tsx` | Modify | Add Clerk `OrganizationSwitcher` |
| `apps/frontend/src/components/chat/ProvisioningStepper.tsx` | Modify | Handle org provisioning flow |
| `apps/frontend/src/components/control/ControlSidebar.tsx` | Modify | Gate admin-only panels by org role |

---

## Task 1: Auth — `resolve_owner_id` and `require_org_admin`

The foundation. Every other task depends on these two helpers.

**Files:**
- Modify: `apps/backend/core/auth.py:49-79`
- Test: `apps/backend/tests/unit/core/test_auth.py`

- [ ] **Step 1: Write failing tests for `resolve_owner_id` and `require_org_admin`**

```python
# apps/backend/tests/unit/core/test_auth_org.py
"""Tests for organization auth helpers."""

import os
os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

import pytest
from fastapi import HTTPException

from core.auth import AuthContext, resolve_owner_id, require_org_admin


class TestResolveOwnerId:
    def test_personal_context_returns_user_id(self):
        auth = AuthContext(user_id="user_123")
        assert resolve_owner_id(auth) == "user_123"

    def test_org_context_returns_org_id(self):
        auth = AuthContext(user_id="user_123", org_id="org_456", org_role="org:admin")
        assert resolve_owner_id(auth) == "org_456"

    def test_org_member_returns_org_id(self):
        auth = AuthContext(user_id="user_123", org_id="org_456", org_role="org:member")
        assert resolve_owner_id(auth) == "org_456"


class TestRequireOrgAdmin:
    def test_personal_context_passes(self):
        """Personal users are not in an org — no admin check needed."""
        auth = AuthContext(user_id="user_123")
        result = require_org_admin(auth)
        assert result == auth

    def test_org_admin_passes(self):
        auth = AuthContext(user_id="user_123", org_id="org_456", org_role="org:admin")
        result = require_org_admin(auth)
        assert result == auth

    def test_org_member_raises_403(self):
        auth = AuthContext(user_id="user_123", org_id="org_456", org_role="org:member")
        with pytest.raises(HTTPException) as exc_info:
            require_org_admin(auth)
        assert exc_info.value.status_code == 403

    def test_org_no_role_raises_403(self):
        auth = AuthContext(user_id="user_123", org_id="org_456")
        with pytest.raises(HTTPException) as exc_info:
            require_org_admin(auth)
        assert exc_info.value.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/core/test_auth_org.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_owner_id'`

- [ ] **Step 3: Implement `resolve_owner_id` and `require_org_admin`**

Add to `apps/backend/core/auth.py` after the `AuthContext` class (after line 79):

```python
def resolve_owner_id(auth: AuthContext) -> str:
    """Return the container/workspace owner: org_id if in org, else user_id."""
    return auth.org_id if auth.is_org_context else auth.user_id


def get_owner_type(auth: AuthContext) -> str:
    """Return 'org' or 'personal' based on auth context."""
    return "org" if auth.is_org_context else "personal"


def require_org_admin(auth: AuthContext) -> AuthContext:
    """Raise 403 if user is in an org but not an admin. Personal context passes through."""
    if auth.is_org_context and not auth.is_org_admin:
        raise HTTPException(status_code=403, detail="Organization admin access required")
    return auth
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/core/test_auth_org.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Add org-context conftest fixtures**

Add to `apps/backend/tests/conftest.py` after `mock_auth_context` fixture (after line 41):

```python
@pytest.fixture
def mock_org_admin_context() -> AuthContext:
    """Mock auth context for org admin."""
    return AuthContext(
        user_id="user_test_123",
        org_id="org_test_456",
        org_role="org:admin",
        org_slug="test-org",
        org_permissions=["org:billing:manage"],
    )


@pytest.fixture
def mock_org_member_context() -> AuthContext:
    """Mock auth context for org member (non-admin)."""
    return AuthContext(
        user_id="user_test_789",
        org_id="org_test_456",
        org_role="org:member",
        org_slug="test-org",
    )


@pytest.fixture
def mock_org_admin_user(mock_org_admin_context):
    """Dependency override for get_current_user with org admin context."""
    async def _mock():
        return mock_org_admin_context
    return _mock


@pytest.fixture
def mock_org_member_user(mock_org_member_context):
    """Dependency override for get_current_user with org member context."""
    async def _mock():
        return mock_org_member_context
    return _mock
```

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: All existing tests PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/backend/core/auth.py apps/backend/tests/unit/core/test_auth_org.py apps/backend/tests/conftest.py
git commit -m "feat(auth): add resolve_owner_id, require_org_admin, org test fixtures"
```

---

## Task 2: Container Repo — Owner-Aware Operations

Make the container repo work with `owner_id` (which is user_id for personal, org_id for orgs).

**Files:**
- Modify: `apps/backend/core/repositories/container_repo.py`
- Test: `apps/backend/tests/unit/repositories/test_container_repo.py`

- [ ] **Step 1: Write failing tests for org container operations**

Append to `apps/backend/tests/unit/repositories/test_container_repo.py`:

```python
@pytest.mark.asyncio
async def test_upsert_org_container(dynamodb_table):
    """Org containers store owner_type and org_id fields."""
    from core.repositories import container_repo

    result = await container_repo.upsert(
        "org_456",
        {
            "gateway_token": "tok_org",
            "status": "provisioning",
            "owner_type": "org",
            "org_id": "org_456",
        },
    )
    assert result["user_id"] == "org_456"  # PK stores owner_id
    assert result["owner_type"] == "org"
    assert result["org_id"] == "org_456"


@pytest.mark.asyncio
async def test_get_by_user_id_works_for_org_owner(dynamodb_table):
    """get_by_user_id works when PK holds an org_id."""
    from core.repositories import container_repo

    await container_repo.upsert(
        "org_456",
        {"gateway_token": "tok_org", "status": "running", "owner_type": "org"},
    )
    item = await container_repo.get_by_user_id("org_456")
    assert item is not None
    assert item["owner_type"] == "org"
```

- [ ] **Step 2: Run tests to verify they pass (existing code already supports this)**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_container_repo.py -v`
Expected: ALL PASS — DynamoDB is schema-less, new attributes just work. This confirms the approach.

- [ ] **Step 3: Add `get_by_owner_id` alias for clarity**

Add to `apps/backend/core/repositories/container_repo.py` after `get_by_user_id` (after line 17):

```python
# Alias: owner_id is user_id for personal, org_id for orgs.
# The DynamoDB PK "user_id" holds the owner_id value.
get_by_owner_id = get_by_user_id
```

- [ ] **Step 4: Run full repo tests**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_container_repo.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/backend/core/repositories/container_repo.py apps/backend/tests/unit/repositories/test_container_repo.py
git commit -m "feat(repo): add owner_type/org_id fields, get_by_owner_id alias"
```

---

## Task 3: CDK — Add Owner Type GSI

Add a GSI so we can query containers by `owner_type` (e.g., list all org containers).

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts:38-54`

- [ ] **Step 1: Add GSI to containers table**

Add after the `status-index` GSI (after line 54 in `database-stack.ts`):

```typescript
    this.containersTable.addGlobalSecondaryIndex({
      indexName: "owner-type-index",
      partitionKey: { name: "owner_type", type: dynamodb.AttributeType.STRING },
    });
```

- [ ] **Step 2: Verify CDK synth succeeds**

Run: `cd apps/infra && npx cdk synth --quiet 2>&1 | head -5`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/infra/lib/stacks/database-stack.ts
git commit -m "feat(infra): add owner-type-index GSI to containers table"
```

---

## Task 4: ECS Manager — Owner-Aware Provisioning

Change the ECS manager to accept `owner_id` instead of `user_id` for all service lifecycle operations.

**Files:**
- Modify: `apps/backend/core/containers/ecs_manager.py`
- Test: `apps/backend/tests/unit/containers/test_ecs_manager.py`

- [ ] **Step 1: Write failing tests for org provisioning**

Create `apps/backend/tests/unit/containers/test_ecs_manager_org.py`:

```python
"""Tests for org-aware ECS manager operations."""

import os
os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from core.containers.ecs_manager import EcsManager


class TestServiceNaming:
    """Service name generation works for both user_ids and org_ids."""

    def test_personal_service_name(self):
        mgr = EcsManager.__new__(EcsManager)
        name = mgr._service_name("user_abc123")
        assert name.startswith("openclaw-user_abc123-")
        assert len(name) <= 255

    def test_org_service_name(self):
        mgr = EcsManager.__new__(EcsManager)
        name = mgr._service_name("org_xyz789")
        assert name.startswith("openclaw-org_xyz789-")
        assert len(name) <= 255

    def test_different_ids_produce_different_names(self):
        mgr = EcsManager.__new__(EcsManager)
        assert mgr._service_name("user_abc") != mgr._service_name("org_xyz")
```

- [ ] **Step 2: Run tests to verify they pass (service naming is already ID-agnostic)**

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager_org.py -v`
Expected: ALL PASS — `_service_name()` already works with any string ID.

- [ ] **Step 3: Update `create_user_service` to accept `owner_type` param**

In `apps/backend/core/containers/ecs_manager.py`, modify the `create_user_service` signature at line 205 and the upsert at line 230:

Change line 205:
```python
    async def create_user_service(self, user_id: str, gateway_token: str, owner_type: str = "personal") -> str:
```

Change the upsert at lines 230-238:
```python
        await container_repo.upsert(
            user_id,
            {
                "service_name": service_name,
                "gateway_token": gateway_token,
                "status": "provisioning",
                "substatus": None,
                "owner_type": owner_type,
            },
        )
```

- [ ] **Step 4: Update `_create_access_point` tags for org awareness**

The EFS access point root stays at `/users/{owner_id}` for both personal and org containers — no path change needed. The `workspace.py` module already writes to `{EFS_MOUNT_PATH}/{owner_id}/` which aligns.

In `apps/backend/core/containers/ecs_manager.py`, update only the tags at lines 96-100 to record `owner_type`:

```python
                Tags=[
                    {"Key": "Name", "Value": f"isol8-{user_id}"},
                    {"Key": "owner_id", "Value": user_id},
                    {"Key": "owner_type", "Value": owner_type},
                    {"Key": "ManagedBy", "Value": "isol8-backend"},
                ],
```

Add `owner_type` parameter to the method signature at line 68 (for tag use only):
```python
    def _create_access_point(self, user_id: str, owner_type: str = "personal") -> str:
```

- [ ] **Step 5: Thread `owner_type` through the provisioning chain**

In `provision_user_container` (line 573), pass `owner_type` to `create_user_service`:

Change line 702:
```python
        service_name = await self.create_user_service(user_id, gateway_token, owner_type=owner_type)
```

Add `owner_type` parameter to the method signature at line 573:
```python
    async def provision_user_container(self, user_id: str, owner_type: str = "personal") -> str:
```

Thread through `_create_access_point` call at line 242:
```python
            access_point_id = self._create_access_point(user_id, owner_type=owner_type)
```

- [ ] **Step 6: Run full backend tests**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: ALL PASS (default `owner_type="personal"` preserves backwards compat)

- [ ] **Step 7: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/backend/core/containers/ecs_manager.py apps/backend/tests/unit/containers/test_ecs_manager_org.py
git commit -m "feat(ecs): org-aware provisioning with owner_type param and /orgs/ EFS paths"
```

---

## Task 5: Gateway Connection Pool — Owner-Aware Routing

Change the pool to key by `owner_id` so all org members share one gateway connection.

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py`
- Test: `apps/backend/tests/unit/core/test_connection_pool.py`

- [ ] **Step 1: Write failing tests for org fan-out**

Create `apps/backend/tests/unit/core/test_connection_pool_org.py`:

```python
"""Tests for org-aware gateway connection pool."""

import os
os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import MagicMock
from core.gateway.connection_pool import GatewayConnectionPool


class TestOrgFanOut:
    """Multiple org members share one pool entry under the same owner_id."""

    def test_multiple_members_share_owner_key(self):
        pool = GatewayConnectionPool(management_api=MagicMock())
        # Two org members with different user_ids but same owner_id (org_id)
        pool.add_frontend_connection("org_456", "conn_alice")
        pool.add_frontend_connection("org_456", "conn_bob")

        assert pool._frontend_connections["org_456"] == {"conn_alice", "conn_bob"}

    def test_remove_one_member_keeps_other(self):
        pool = GatewayConnectionPool(management_api=MagicMock())
        pool.add_frontend_connection("org_456", "conn_alice")
        pool.add_frontend_connection("org_456", "conn_bob")

        pool.remove_frontend_connection("org_456", "conn_alice")
        assert pool._frontend_connections["org_456"] == {"conn_bob"}

    def test_personal_connections_unchanged(self):
        pool = GatewayConnectionPool(management_api=MagicMock())
        pool.add_frontend_connection("user_123", "conn_1")
        pool.add_frontend_connection("user_456", "conn_2")

        assert pool._frontend_connections["user_123"] == {"conn_1"}
        assert pool._frontend_connections["user_456"] == {"conn_2"}
```

- [ ] **Step 2: Run tests — should pass since pool already works with any string key**

Run: `cd apps/backend && uv run pytest tests/unit/core/test_connection_pool_org.py -v`
Expected: ALL PASS — pool is already parameterized by string key.

- [ ] **Step 3: Fix stale `_device_identities` reference in `close_user`**

In `apps/backend/core/gateway/connection_pool.py`, line 518 references `self._device_identities` which does not exist (leftover from device-pairing removal). Remove this line:

```python
        self._device_identities.pop(user_id, None)  # DELETE THIS LINE
```

- [ ] **Step 4: Run existing pool tests to verify no regression**

Run: `cd apps/backend && uv run pytest tests/unit/core/test_connection_pool.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/backend/tests/unit/core/test_connection_pool_org.py
git commit -m "test(pool): add org fan-out contract tests for gateway pool"
```

---

## Task 6: WebSocket Router — Org-Aware Routing

The critical integration task. When an org member connects, route to the org's container.

**Files:**
- Modify: `apps/backend/routers/websocket_chat.py:87-117, 167-264, 272-362, 370-449`
- Test: `apps/backend/tests/unit/routers/test_websocket_chat.py`

- [ ] **Step 1: Write failing tests for org routing**

Create `apps/backend/tests/unit/routers/test_websocket_org_routing.py`:

```python
"""Tests for org-aware WebSocket routing."""

import os
os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.auth import resolve_owner_id, AuthContext


class TestOwnerResolution:
    """WebSocket routing resolves owner_id from connection context."""

    def test_personal_connection_uses_user_id(self):
        connection = {"user_id": "user_123", "org_id": None}
        owner_id = connection.get("org_id") or connection["user_id"]
        assert owner_id == "user_123"

    def test_org_connection_uses_org_id(self):
        connection = {"user_id": "user_123", "org_id": "org_456"}
        owner_id = connection.get("org_id") or connection["user_id"]
        assert owner_id == "org_456"


class TestSessionKeyIsolation:
    """Chat session keys include user_id for conversation isolation."""

    def test_personal_session_key(self):
        session_key = f"agent:agent_1:user_123"
        assert "user_123" in session_key

    def test_org_members_get_different_session_keys(self):
        alice_key = f"agent:agent_1:user_alice"
        bob_key = f"agent:agent_1:user_bob"
        assert alice_key != bob_key

    def test_same_agent_same_user_same_key(self):
        key1 = f"agent:agent_1:user_alice"
        key2 = f"agent:agent_1:user_alice"
        assert key1 == key2
```

- [ ] **Step 2: Run tests to verify they pass (pure logic tests)**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_websocket_org_routing.py -v`
Expected: ALL PASS

- [ ] **Step 3: Modify `ws_connect` to register by `owner_id`**

In `apps/backend/routers/websocket_chat.py`, change `ws_connect` (lines 107-111):

```python
    try:
        pool = get_gateway_pool()
        # Route by owner_id: org_id for org members, user_id for personal
        owner_id = x_org_id or x_user_id
        pool.add_frontend_connection(owner_id, x_connection_id)
    except Exception as e:
        logger.warning("Failed to register frontend connection with pool: %s", e)
```

- [ ] **Step 4: Modify `ws_disconnect` to unregister by `owner_id`**

In `ws_disconnect` (lines 136-143):

```python
    try:
        connection_service = await get_connection_service()
        connection = connection_service.get_connection(x_connection_id)
        if connection:
            pool = get_gateway_pool()
            owner_id = connection.get("org_id") or connection["user_id"]
            pool.remove_frontend_connection(owner_id, x_connection_id)
    except Exception as e:
        logger.warning("Failed to unregister frontend connection from pool: %s", e)
```

- [ ] **Step 5: Modify `ws_message` to resolve `owner_id` from connection**

In `ws_message` (line 181), add after retrieving the connection:

```python
    user_id = connection["user_id"]
    owner_id = connection.get("org_id") or user_id
    msg_type = body.get("type")
```

Then update `_process_rpc_background` calls (line 228) to pass `owner_id`:

```python
        background_tasks.add_task(
            _process_rpc_background,
            connection_id=x_connection_id,
            user_id=user_id,
            owner_id=owner_id,
            req_id=req_id,
            method=method,
            params=params,
        )
```

And `_process_agent_chat_background` calls (line 249) to pass both:

```python
        background_tasks.add_task(
            _process_agent_chat_background,
            connection_id=x_connection_id,
            user_id=user_id,
            owner_id=owner_id,
            agent_id=agent_id,
            message=message,
        )
```

- [ ] **Step 6: Update `_process_rpc_background` to use `owner_id`**

Change signature (line 272):

```python
async def _process_rpc_background(
    connection_id: str,
    user_id: str,
    owner_id: str,
    req_id: str,
    method: str,
    params: dict,
) -> None:
```

Change container resolution (line 284):

```python
        container, ip = await ecs_manager.resolve_running_container(owner_id)
```

Change pool.send_rpc (line 311):

```python
        result = await pool.send_rpc(
            user_id=owner_id,  # Pool keys by owner
            req_id=req_id,
            method=method,
            params=params,
            ip=ip,
            token=container["gateway_token"],
        )
```

- [ ] **Step 7: Update `_process_agent_chat_background` for owner_id + session isolation**

Change signature (line 370):

```python
async def _process_agent_chat_background(
    connection_id: str,
    user_id: str,
    owner_id: str,
    agent_id: str,
    message: str,
) -> None:
```

Change container resolution (line 396):

```python
        container, ip = await ecs_manager.resolve_running_container(owner_id)
```

Change session key (line 423) — org contexts use user_id for isolation, personal keeps `:main`:

```python
        # Org members get per-user sessions; personal users keep :main (no history breakage)
        is_org = owner_id != user_id
        session_key = f"agent:{agent_id}:{user_id}" if is_org else f"agent:{agent_id}:main"
```

Change pool.send_rpc (line 425):

```python
        result = await pool.send_rpc(
            user_id=owner_id,  # Pool keys by owner
            req_id=req_id,
            method="chat.send",
            params={
                "sessionKey": session_key,
                "message": message,
                "idempotencyKey": str(uuid4()),
            },
            ip=ip,
            token=container["gateway_token"],
        )
```

- [ ] **Step 8: Run full backend tests**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/backend/routers/websocket_chat.py apps/backend/tests/unit/routers/test_websocket_org_routing.py
git commit -m "feat(ws): org-aware routing — resolve owner_id, silo sessions by user_id"
```

---

## Task 7: Container RPC Router — Org-Aware Resolution

The REST RPC endpoint also needs to resolve containers by `owner_id`.

**Files:**
- Modify: `apps/backend/routers/container_rpc.py`

- [ ] **Step 1: Read current container_rpc.py to find all `user_id` container lookups**

Read: `apps/backend/routers/container_rpc.py`

- [ ] **Step 2: Update container resolution to use `resolve_owner_id`**

At the top of the file, add import:

```python
from core.auth import resolve_owner_id
```

In every route handler that calls `ecs_manager.resolve_running_container(auth.user_id)`, change to:

```python
owner_id = resolve_owner_id(auth)
container, ip = await ecs_manager.resolve_running_container(owner_id)
```

Similarly update `pool.send_rpc(user_id=auth.user_id, ...)` to `pool.send_rpc(user_id=owner_id, ...)`.

- [ ] **Step 3: Run backend tests**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/backend/routers/container_rpc.py
git commit -m "feat(rpc): resolve container by owner_id for org support"
```

---

## Task 8: All Remaining Routers — Org-Aware Resolution

**CRITICAL:** Every router that resolves a container or accesses EFS must use `resolve_owner_id(auth)`. Missing even one causes 404s for org members.

**Files:**
- Modify: `apps/backend/routers/debug.py`
- Modify: `apps/backend/routers/container.py` (status polling, retry)
- Modify: `apps/backend/routers/channels.py`
- Modify: `apps/backend/routers/integrations.py`
- Modify: `apps/backend/routers/control_ui_proxy.py`
- Modify: `apps/backend/routers/settings_keys.py`

- [ ] **Step 1: Read all six routers**

Read each file and identify every occurrence of `auth.user_id` used for container resolution or EFS access.

- [ ] **Step 2: Update `debug.py`**

Add imports:

```python
from core.auth import resolve_owner_id, get_owner_type, require_org_admin
```

In the POST provision endpoint:

```python
owner_id = resolve_owner_id(auth)
otype = get_owner_type(auth)
service_name = await ecs_manager.provision_user_container(owner_id, owner_type=otype)
```

In the DELETE endpoint, gate by admin role for org contexts:

```python
if auth.is_org_context:
    require_org_admin(auth)
owner_id = resolve_owner_id(auth)
await ecs_manager.delete_user_service(owner_id)
```

- [ ] **Step 3: Update `container.py` (status/retry)**

This is the **most critical** — the frontend polls `GET /container/status` to detect containers. Replace all `auth.user_id` with `resolve_owner_id(auth)` in:
- Status endpoint
- Retry endpoint
- `_user_has_subscription()` helper
- `_background_provision()` helper

- [ ] **Step 4: Update `channels.py`**

Replace `auth.user_id` with `resolve_owner_id(auth)` in `_send_channel_rpc` and all channel endpoints.

- [ ] **Step 5: Update `integrations.py`**

Replace `auth.user_id` with `resolve_owner_id(auth)` for all MCP server CRUD. Gate write operations (add/remove/update MCP servers) with `require_org_admin(auth)` when in org context.

- [ ] **Step 6: Update `control_ui_proxy.py`**

Replace `user_id` with `resolve_owner_id(auth)` in `_resolve_user_container` helper.

- [ ] **Step 7: Update `settings_keys.py`**

Replace `auth.user_id` with `resolve_owner_id(auth)` for API key lookups. Gate key creation/deletion with `require_org_admin(auth)` when in org context.

- [ ] **Step 8: Run full backend tests**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/backend/routers/debug.py apps/backend/routers/container.py apps/backend/routers/channels.py apps/backend/routers/integrations.py apps/backend/routers/control_ui_proxy.py apps/backend/routers/settings_keys.py
git commit -m "feat(routers): org-aware resolution across all container/EFS routers"
```

---

## Task 9: Frontend — Clerk Organization Integration

Add Clerk org support to the frontend so users can create/join/switch orgs.

**Files:**
- Modify: `apps/frontend/src/components/chat/ChatLayout.tsx`
- Modify: `apps/frontend/src/components/control/ControlSidebar.tsx`

- [ ] **Step 1: Read current ChatLayout.tsx and ControlSidebar.tsx**

Read both files to understand current structure.

- [ ] **Step 2: Add OrganizationSwitcher to ChatLayout header**

In `ChatLayout.tsx`, import Clerk's org components:

```typescript
import { OrganizationSwitcher } from "@clerk/nextjs";
```

Add the switcher next to the existing `UserButton` in the header area. The exact location depends on the current layout — place it in the header bar.

```tsx
<OrganizationSwitcher
  hidePersonal={false}
  afterSelectOrganizationUrl="/chat"
  afterSelectPersonalUrl="/chat"
/>
```

- [ ] **Step 3: Gate admin-only panels in ControlSidebar**

Import Clerk's org hook:

```typescript
import { useOrganization } from "@clerk/nextjs";
```

In the component, get the current membership:

```typescript
const { membership } = useOrganization();
const isAdmin = !membership || membership.role === "org:admin";
```

Hide admin-only sidebar items (Channels, Config, Settings/Keys) when `!isAdmin`:

```tsx
{isAdmin && <SidebarItem icon={Settings} label="Config" panel="config" />}
{isAdmin && <SidebarItem icon={Key} label="API Keys" panel="keys" />}
```

- [ ] **Step 4: Run frontend lint**

Run: `cd apps/frontend && pnpm run lint`
Expected: No new errors

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/frontend/src/components/chat/ChatLayout.tsx apps/frontend/src/components/control/ControlSidebar.tsx
git commit -m "feat(frontend): add Clerk OrganizationSwitcher, gate admin panels by role"
```

---

## Task 10: Frontend — Org-Aware Provisioning Stepper

When a user is in org context, the provisioning flow provisions the org container.

**Files:**
- Modify: `apps/frontend/src/components/chat/ProvisioningStepper.tsx`
- Modify: `apps/frontend/src/hooks/useContainerStatus.ts`

- [ ] **Step 1: Read current ProvisioningStepper.tsx and useContainerStatus.ts**

Read both files to understand the provisioning flow.

- [ ] **Step 2: Update useContainerStatus to handle org context**

The status polling endpoint (`GET /container/health`) already resolves auth from the JWT. Since the JWT carries org claims, the backend will resolve the correct owner_id. **No frontend change needed for status polling** — the Clerk token already carries the org context.

Verify this by checking the health endpoint in `container_rpc.py` uses `auth.user_id` — update it to use `resolve_owner_id(auth)` if not already done in Task 7.

- [ ] **Step 3: Update ProvisioningStepper for org context**

Import Clerk hook:

```typescript
import { useOrganization } from "@clerk/nextjs";
```

In the component, detect org context:

```typescript
const { organization } = useOrganization();
const isOrg = !!organization;
```

Update the UI text to reflect org vs personal:

```tsx
{isOrg ? (
  <p>Setting up workspace for {organization.name}...</p>
) : (
  <p>Setting up your personal workspace...</p>
)}
```

- [ ] **Step 4: Run frontend lint**

Run: `cd apps/frontend && pnpm run lint`
Expected: No new errors

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git add apps/frontend/src/components/chat/ProvisioningStepper.tsx apps/frontend/src/hooks/useContainerStatus.ts
git commit -m "feat(frontend): org-aware provisioning stepper UI"
```

---

## Task 11: Integration Verification

End-to-end smoke test to verify the full flow works.

- [ ] **Step 1: Run full backend test suite**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Run frontend build**

Run: `cd apps/frontend && pnpm run build`
Expected: Build succeeds

- [ ] **Step 3: Run CDK synth**

Run: `cd apps/infra && npx cdk synth --quiet 2>&1 | head -5`
Expected: No errors

- [ ] **Step 4: Run turbo lint across monorepo**

Run: `turbo run lint`
Expected: ALL PASS

- [ ] **Step 5: Final commit with integration notes**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/org-support
git log --oneline feature/org-support ^main
```

Verify all commits are present and the branch is ready for PR.

---

## Summary of Changes

| Layer | Change | Backwards Compatible |
|-------|--------|---------------------|
| Auth | `resolve_owner_id()`, `get_owner_type()`, `require_org_admin()` | Yes — new functions, nothing changed |
| Container Repo | `get_by_owner_id` alias, `owner_type` field | Yes — additive |
| CDK | `owner-type-index` GSI | Yes — additive |
| ECS Manager | `owner_type` param, tags updated | Yes — defaults to `"personal"`, EFS stays at `/users/` |
| Gateway Pool | Key by `owner_id`, fix `_device_identities` bug | Yes — string key is transparent |
| WebSocket Router | Resolve `owner_id` from connection | Yes — personal falls back to `user_id` |
| Container RPC | Resolve by `owner_id` | Yes — personal falls back to `user_id` |
| All Other Routers | `resolve_owner_id` + admin gating | Yes — personal falls back to `user_id` |
| Frontend | `OrganizationSwitcher`, admin gating | Yes — personal flow unchanged |
| Session Keys | Org: `agent:{id}:{user_id}`, Personal: `agent:{id}:main` | Yes — personal sessions unchanged |

### What's NOT In This Plan (Future Work)

- **Org billing model** — billing is being reworked by another agent. This plan does not change billing/payment flows.
- **Per-member usage breakdowns** — usage is attributed to `owner_id` (org). Per-member tracking is future.
- **Org container resource scaling** — org containers use the same task definition as personal. Higher CPU/memory for orgs is future.
- **Migration of existing personal containers into orgs** — users must provision fresh when creating an org.
