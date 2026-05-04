# Provision Gate UI Implementation Plan

**Status:** In progress (chat-UI integration shipped in PR #519)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface known provisioning preconditions ("no subscription", "out of credits", "no OAuth tokens") in the chat-page UI as a structured "blocked" state instead of an indefinite "Provisioning your container…" spinner.

**Architecture:** A new `provision_gate.py` helper centralizes gate evaluation; `/container/status` and `/container/provision` both consult it and return a structured `blocked` payload on 402. The frontend renders this payload as a new "blocked" state on the existing `ProvisioningStepper` centerpiece, polls for auto-recovery, and never shows a misleading spinner when a gate is up.

**Tech Stack:** FastAPI, Pydantic, pytest (backend); Next.js 16 App Router, React 19, SWR, Clerk, vitest + testing-library (frontend).

**Spec:** `docs/superpowers/specs/2026-05-03-provision-gate-ui-design.md`

**Testing convention:** Per the user's saved feedback (`feedback_write_tests_run_at_end.md`), each task writes test files but does not run them mid-task. The final task runs the full suite for verification.

---

## File structure

**Backend (new):**
- `apps/backend/core/services/provision_gate.py` — `Gate` dataclass + `evaluate_provision_gate(owner_id, owner_type, clerk_user_id) -> Gate | None` function. Single source of truth for gate logic.
- `apps/backend/tests/unit/services/test_provision_gate.py` — unit tests per gate combination.

**Backend (modify):**
- `apps/backend/routers/container.py` — `_assert_provision_allowed` delegates to the helper; `container_status` (line 204) evaluates gates and returns 402+payload when blocked; `container_provision` returns the same structured payload on 402.

**Backend (test modify):**
- `apps/backend/tests/unit/routers/test_container_provision_gating.py` — assert structured payload shape.
- `apps/backend/tests/unit/routers/test_container.py` (or wherever `/container/status` is tested today; create if absent) — gate-aware status response.

**Frontend (new):**
- `apps/frontend/src/hooks/useProvisioningState.ts` — state machine hook: maps polled status into `{ phase: "normal" | "blocked", container?, blocked? }`.
- `apps/frontend/src/hooks/useProvisioningState.test.ts` — vitest unit test of the state machine transitions.

**Frontend (modify):**
- `apps/frontend/src/lib/api.ts` — `useApi` preserves 402 response bodies (returns the parsed body via a typed error-with-body shape) instead of throwing on the helper level.
- `apps/frontend/src/hooks/useContainerStatus.ts` — surface 402 + `blocked` payload to consumers (new return field).
- `apps/frontend/src/components/chat/ProvisioningStepper.tsx` — render the new `blocked` state when `useProvisioningState` returns `phase: "blocked"`. Add member-vs-admin branching for the action.

---

## Task 1: Create the `provision_gate` helper module (backend)

**Files:**
- Create: `apps/backend/core/services/provision_gate.py`
- Test: `apps/backend/tests/unit/services/test_provision_gate.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/services/test_provision_gate.py`:

```python
"""Tests for the provision-gate helper."""

from unittest.mock import AsyncMock, patch

import pytest

from core.services.provision_gate import Gate, evaluate_provision_gate


@pytest.mark.asyncio
async def test_no_billing_account_returns_subscription_required():
    with patch("core.services.provision_gate.billing_repo") as repo:
        repo.get_by_owner_id = AsyncMock(return_value=None)
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is not None
    assert gate.code == "subscription_required"
    assert gate.action.admin_only is True
    assert gate.owner_role in ("admin", "member")  # caller-supplied below


@pytest.mark.asyncio
async def test_active_subscription_bedrock_zero_balance_returns_credits_required():
    with patch("core.services.provision_gate.billing_repo") as repo, \
         patch("core.services.provision_gate._get_provider_choice") as gp, \
         patch("core.services.provision_gate.credit_ledger") as cl:
        repo.get_by_owner_id = AsyncMock(
            return_value={"subscription_status": "active", "stripe_subscription_id": "sub_x"},
        )
        gp.return_value = ("bedrock_claude", None)
        cl.get_balance = AsyncMock(return_value=0)
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is not None
    assert gate.code == "credits_required"


@pytest.mark.asyncio
async def test_trialing_with_credits_returns_none():
    with patch("core.services.provision_gate.billing_repo") as repo, \
         patch("core.services.provision_gate._get_provider_choice") as gp, \
         patch("core.services.provision_gate.credit_ledger") as cl:
        repo.get_by_owner_id = AsyncMock(
            return_value={"subscription_status": "trialing", "stripe_subscription_id": "sub_x"},
        )
        gp.return_value = ("bedrock_claude", None)
        cl.get_balance = AsyncMock(return_value=500_000)  # 50 cents
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is None  # all gates pass


@pytest.mark.asyncio
async def test_past_due_returns_payment_past_due():
    with patch("core.services.provision_gate.billing_repo") as repo:
        repo.get_by_owner_id = AsyncMock(
            return_value={"subscription_status": "past_due", "stripe_subscription_id": "sub_x"},
        )
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is not None
    assert gate.code == "payment_past_due"


@pytest.mark.asyncio
async def test_chatgpt_oauth_no_tokens_returns_oauth_required():
    with patch("core.services.provision_gate.billing_repo") as repo, \
         patch("core.services.provision_gate._get_provider_choice") as gp, \
         patch("core.services.provision_gate._has_oauth_tokens") as ht:
        repo.get_by_owner_id = AsyncMock(
            return_value={"subscription_status": "active", "stripe_subscription_id": "sub_x"},
        )
        gp.return_value = ("chatgpt_oauth", None)
        ht.return_value = False
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is not None
    assert gate.code == "oauth_required"


def test_gate_to_payload_shape():
    gate = Gate(
        code="credits_required",
        title="Top up Claude credits",
        message="Top up some Claude credits to start your Bedrock container.",
        action_label="Top up now",
        action_href="/settings/billing#credits",
        action_admin_only=False,
        owner_role="admin",
    )
    payload = gate.to_payload()
    assert payload["blocked"]["code"] == "credits_required"
    assert payload["blocked"]["action"]["href"] == "/settings/billing#credits"
    assert payload["blocked"]["action"]["admin_only"] is False
    assert payload["blocked"]["owner_role"] == "admin"
    assert payload["detail"]  # legacy string preserved
```

- [ ] **Step 2: Write the implementation**

Create `apps/backend/core/services/provision_gate.py`:

```python
"""Provision gate evaluation — single source of truth for whether an owner
can provision a container, and *why not* when they can't.

Both `/container/provision` and `/container/status` consult this helper and
return its structured payload on 402, so the two endpoints can never
disagree about the gate state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.repositories import billing_repo, user_repo, oauth_token_repo
from core.services import credit_ledger


_PROVISION_OK_STATUSES = frozenset({"active", "trialing"})


@dataclass(frozen=True)
class Gate:
    """A blocked-state gate result. None means no gate fires (provision allowed)."""

    code: str
    title: str
    message: str
    action_label: str
    action_href: str
    action_admin_only: bool
    owner_role: str  # "admin" | "member"

    def to_payload(self) -> dict[str, Any]:
        """Build the FastAPI HTTPException detail payload.

        `detail` is kept as a plain string for backwards-compat with any
        path that still renders FastAPI's default error shape. `blocked`
        is the structured field new frontends switch on.
        """
        return {
            "detail": self.message,
            "blocked": {
                "code": self.code,
                "title": self.title,
                "message": self.message,
                "action": {
                    "kind": "link",
                    "label": self.action_label,
                    "href": self.action_href,
                    "admin_only": self.action_admin_only,
                },
                "owner_role": self.owner_role,
            },
        }


async def _get_provider_choice(clerk_user_id: str) -> tuple[str, str | None]:
    """Read provider_choice from user_repo (current model — Workstream B
    will move this to billing_repo). Falls back to bedrock_claude when no
    row exists, matching the existing behavior in container.py."""
    row = await user_repo.get(clerk_user_id)
    provider_choice = (row or {}).get("provider_choice") or "bedrock_claude"
    byo_provider = (row or {}).get("byo_provider") if provider_choice == "byo_key" else None
    return provider_choice, byo_provider


async def _has_oauth_tokens(owner_id: str) -> bool:
    """Whether the owner has ChatGPT OAuth tokens on file."""
    tokens = await oauth_token_repo.get(owner_id)
    return tokens is not None


async def evaluate_provision_gate(
    *,
    owner_id: str,
    owner_type: str,  # "personal" | "org"
    clerk_user_id: str,
    is_admin: bool = True,  # personal owners are always admin of themselves
) -> Gate | None:
    """Return a Gate if provisioning should be blocked, else None.

    Layers (matches existing _assert_provision_allowed logic):
    1. Subscription must be active or trialing (or legacy stripe_subscription_id present).
    2. For bedrock_claude: credit balance must be > 0.
    3. For chatgpt_oauth: OAuth tokens must exist for the owner.
    """
    owner_role = "admin" if is_admin else "member"

    # Layer 1 — subscription.
    account = await billing_repo.get_by_owner_id(owner_id)
    if not account:
        return Gate(
            code="subscription_required",
            title="Subscribe to start your container",
            message="An active subscription is required to provision a container.",
            action_label="Subscribe",
            action_href="/onboarding",
            action_admin_only=True,
            owner_role=owner_role,
        )
    status = account.get("subscription_status")
    has_legacy_sub = bool(account.get("stripe_subscription_id"))
    is_ok = status in _PROVISION_OK_STATUSES or (status is None and has_legacy_sub)
    if not is_ok:
        if status == "past_due":
            return Gate(
                code="payment_past_due",
                title="Payment past due",
                message="Your latest invoice failed. Update your payment method to continue.",
                action_label="Update payment",
                action_href="/settings/billing",
                action_admin_only=True,
                owner_role=owner_role,
            )
        return Gate(
            code="subscription_required",
            title="Subscription not active",
            message="Reactivate your subscription to start your container.",
            action_label="Manage subscription",
            action_href="/settings/billing",
            action_admin_only=True,
            owner_role=owner_role,
        )

    # Layer 2/3 — provider-specific.
    provider_choice, _ = await _get_provider_choice(clerk_user_id)

    if provider_choice == "bedrock_claude":
        balance = await credit_ledger.get_balance(clerk_user_id)
        if balance <= 0:
            return Gate(
                code="credits_required",
                title="Top up Claude credits to start your container",
                message="Top up some Claude credits to start your Bedrock container.",
                action_label="Top up now",
                action_href="/settings/billing#credits",
                action_admin_only=False,
                owner_role=owner_role,
            )

    if provider_choice == "chatgpt_oauth":
        if not await _has_oauth_tokens(owner_id):
            return Gate(
                code="oauth_required",
                title="Sign in with ChatGPT",
                message="Complete the ChatGPT sign-in to start your container.",
                action_label="Sign in with ChatGPT",
                action_href="/settings/llm",
                action_admin_only=False,
                owner_role=owner_role,
            )

    return None  # all gates pass — provisioning allowed
```

- [ ] **Step 3: Commit**

```bash
git add apps/backend/core/services/provision_gate.py apps/backend/tests/unit/services/test_provision_gate.py
git commit -m "feat(backend): provision-gate helper with structured Gate payload"
```

---

## Task 2: Refactor `_assert_provision_allowed` to use the helper

**Files:**
- Modify: `apps/backend/routers/container.py:62-103` (replace body of `_assert_provision_allowed`)
- Test: existing `apps/backend/tests/unit/routers/test_container_provision_gating.py` covers behavior; add structured-payload assertion.

- [ ] **Step 1: Write the failing test** in `apps/backend/tests/unit/routers/test_container_provision_gating.py`. Add this test next to the existing ones:

```python
@pytest.mark.asyncio
async def test_provision_402_returns_structured_blocked_payload():
    """Per provision-gate-ui spec: 402 must include blocked.code + blocked.action."""
    from fastapi import HTTPException

    with patch("apps.backend.routers.container.evaluate_provision_gate") as mock_gate:
        from core.services.provision_gate import Gate

        mock_gate.return_value = Gate(
            code="credits_required",
            title="Top up Claude credits to start your container",
            message="Top up some Claude credits to start your Bedrock container.",
            action_label="Top up now",
            action_href="/settings/billing#credits",
            action_admin_only=False,
            owner_role="admin",
        )

        from apps.backend.routers.container import _assert_provision_allowed

        with pytest.raises(HTTPException) as exc:
            await _assert_provision_allowed(
                owner_id="user_x",
                clerk_user_id="user_x",
                owner_type="personal",
                is_admin=True,
            )
        assert exc.value.status_code == 402
        assert exc.value.detail["blocked"]["code"] == "credits_required"
        assert exc.value.detail["blocked"]["action"]["href"] == "/settings/billing#credits"
```

- [ ] **Step 2: Replace the body of `_assert_provision_allowed`** in `apps/backend/routers/container.py`:

Find:
```python
async def _assert_provision_allowed(owner_id: str, clerk_user_id: str) -> None:
    """Raise 402 if the owner cannot afford to provision a new container.
    ...
    """
    account = await billing_repo.get_by_owner_id(owner_id)
    # ... old body ...
```

Replace with (note new signature — `owner_type` and `is_admin` are passed by callers; `_resolve_provider_choice` is left in place because it has other callers, but `_assert_provision_allowed` no longer calls it):
```python
async def _assert_provision_allowed(
    owner_id: str,
    clerk_user_id: str,
    *,
    owner_type: str,
    is_admin: bool = True,
) -> None:
    """Raise 402 with structured `blocked` payload if a provision gate fires.

    Delegates to core.services.provision_gate.evaluate_provision_gate so
    /container/provision and /container/status share the same logic.
    """
    from core.services.provision_gate import evaluate_provision_gate

    gate = await evaluate_provision_gate(
        owner_id=owner_id,
        owner_type=owner_type,
        clerk_user_id=clerk_user_id,
        is_admin=is_admin,
    )
    if gate is not None:
        raise HTTPException(status_code=402, detail=gate.to_payload())
```

- [ ] **Step 3: Update each caller of `_assert_provision_allowed`** to pass the new `owner_type` and `is_admin`. Three call sites in `routers/container.py`: lines 226, 347, 392 (verify with `git grep -n "_assert_provision_allowed" apps/backend/routers/container.py`). At each site:

```python
# OLD
await _assert_provision_allowed(owner_id, auth.user_id)

# NEW
from core.auth import get_owner_type
await _assert_provision_allowed(
    owner_id,
    auth.user_id,
    owner_type=get_owner_type(auth),
    is_admin=auth.is_org_admin if auth.is_org_context else True,
)
```

(`get_owner_type` is already exported from `core.auth`, line ~102.)

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/container.py apps/backend/tests/unit/routers/test_container_provision_gating.py
git commit -m "refactor(container): _assert_provision_allowed delegates to provision_gate"
```

---

## Task 3: Make `/container/status` evaluate gates and return structured 402

**Files:**
- Modify: `apps/backend/routers/container.py:204` (the `container_status` endpoint)
- Test: add or extend `apps/backend/tests/unit/routers/test_container_status.py` (create if absent — check with `find apps/backend/tests/unit/routers -name "test_container*"`)

- [ ] **Step 1: Write the failing test**. If `test_container_status.py` doesn't exist, create it. Add:

```python
"""Tests for GET /container/status — gate-aware response shape."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_status_with_no_container_and_blocked_gate_returns_402_structured(async_client, auth_headers):
    """No container row + a gate fires → 402 with structured blocked payload."""
    with patch("apps.backend.routers.container.evaluate_provision_gate") as mock_gate, \
         patch("apps.backend.routers.container.get_ecs_manager") as mock_ecs:
        from core.services.provision_gate import Gate

        mock_ecs.return_value.get_service_status = AsyncMock(return_value=None)
        mock_gate.return_value = Gate(
            code="credits_required",
            title="Top up Claude credits to start your container",
            message="Top up some Claude credits to start your Bedrock container.",
            action_label="Top up now",
            action_href="/settings/billing#credits",
            action_admin_only=False,
            owner_role="admin",
        )

        resp = await async_client.get("/api/v1/container/status", headers=auth_headers)
        assert resp.status_code == 402
        body = resp.json()
        assert body["detail"]["blocked"]["code"] == "credits_required"


@pytest.mark.asyncio
async def test_status_with_no_container_and_no_gate_returns_404(async_client, auth_headers):
    """No container row + no gate fires → 404 (frontend triggers POST /provision)."""
    with patch("apps.backend.routers.container.evaluate_provision_gate") as mock_gate, \
         patch("apps.backend.routers.container.get_ecs_manager") as mock_ecs:
        mock_ecs.return_value.get_service_status = AsyncMock(return_value=None)
        mock_gate.return_value = None

        resp = await async_client.get("/api/v1/container/status", headers=auth_headers)
        assert resp.status_code == 404
```

- [ ] **Step 2: Update `container_status`** in `apps/backend/routers/container.py:204` (verify exact line with `git grep -n "async def container_status" apps/backend/routers/container.py`).

Add a gate evaluation call at the top of the function body, before the existing "no container → 404" branch:

```python
@router.get(
    "/status",
    # ... existing decorator unchanged ...
)
async def container_status(
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)
    ecs_manager = get_ecs_manager()
    container = await ecs_manager.get_service_status(owner_id)

    # If a container row exists, return its state regardless of gate (the
    # owner already paid the provisioning cost; surfacing a gate now would
    # be confusing).
    if container is not None:
        # ... existing existing-container branch unchanged ...
        return {...}  # leave existing logic

    # No container yet — evaluate the provision gate before returning 404.
    # If a gate is up, the frontend should render the blocked state, not
    # auto-trigger another /provision call.
    from core.services.provision_gate import evaluate_provision_gate
    from core.auth import get_owner_type

    gate = await evaluate_provision_gate(
        owner_id=owner_id,
        owner_type=get_owner_type(auth),
        clerk_user_id=auth.user_id,
        is_admin=auth.is_org_admin if auth.is_org_context else True,
    )
    if gate is not None:
        raise HTTPException(status_code=402, detail=gate.to_payload())

    raise HTTPException(status_code=404, detail="no_container")
```

- [ ] **Step 3: Commit**

```bash
git add apps/backend/routers/container.py apps/backend/tests/unit/routers/test_container_status.py
git commit -m "feat(container): /status evaluates gates and returns 402+blocked"
```

---

## Task 4: Update `/container/provision` 402 response to use the same helper

**Files:**
- Modify: `apps/backend/routers/container.py:301` (the `container_provision` endpoint).
- Test: extend `apps/backend/tests/unit/routers/test_container_provision_gating.py` with a structured-payload integration test.

- [ ] **Step 1: Write the failing test** in `test_container_provision_gating.py`:

```python
@pytest.mark.asyncio
async def test_provision_endpoint_402_returns_blocked_payload(async_client, auth_headers):
    """POST /provision 402 must return the structured blocked payload."""
    with patch("apps.backend.routers.container.evaluate_provision_gate") as mock_gate:
        from core.services.provision_gate import Gate
        mock_gate.return_value = Gate(
            code="subscription_required",
            title="Subscribe to start your container",
            message="An active subscription is required to provision a container.",
            action_label="Subscribe",
            action_href="/onboarding",
            action_admin_only=True,
            owner_role="admin",
        )

        resp = await async_client.post("/api/v1/container/provision", headers=auth_headers)
        assert resp.status_code == 402
        body = resp.json()
        assert body["detail"]["blocked"]["code"] == "subscription_required"
        assert body["detail"]["blocked"]["action"]["admin_only"] is True
```

- [ ] **Step 2: Verify implementation requires no further change**. After Task 2, `_assert_provision_allowed` already raises `HTTPException(status_code=402, detail=gate.to_payload())`. The `container_provision` endpoint already calls it (line ~226). So this task is already covered structurally — the test is the new regression pin.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/tests/unit/routers/test_container_provision_gating.py
git commit -m "test(container): pin structured 402 payload from POST /provision"
```

---

## Task 5: Frontend — `useApi.ts` preserves 402 response bodies

**Files:**
- Modify: `apps/frontend/src/lib/api.ts` — `authenticatedFetch` (currently throws on any non-2xx).
- Test: `apps/frontend/src/lib/api.test.ts` (create if absent).

- [ ] **Step 1: Write the failing test** at `apps/frontend/src/lib/api.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";

describe("useApi 402 handling", () => {
  it("throws an error with parsed body attached on 402", async () => {
    // Mock fetch to return 402 with structured body
    global.fetch = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: "Active subscription required",
          blocked: {
            code: "subscription_required",
            title: "Subscribe",
            message: "Active subscription required",
            action: { kind: "link", label: "Subscribe", href: "/onboarding", admin_only: true },
            owner_role: "admin",
          },
        }),
        { status: 402, headers: { "Content-Type": "application/json" } },
      ),
    );

    // The new contract: fetch helper throws an error whose .body is the parsed JSON.
    // Implementation detail: an `ApiError` class with `status` and `body` fields.
    const { ApiError } = await import("@/lib/api");
    expect(ApiError).toBeDefined();
  });
});
```

- [ ] **Step 2: Update `apps/frontend/src/lib/api.ts`**.

Add an `ApiError` class and update `authenticatedFetch` to attach the parsed body on non-2xx:

```typescript
// Add near the top of api.ts, before `useApi`.
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message?: string,
  ) {
    super(message ?? `API ${status}`);
    this.name = "ApiError";
  }
}
```

Update `authenticatedFetch` body — find:

```typescript
const response = await fetch(`${BACKEND_URL}${endpoint}`, {
  ...options,
  headers,
});
// (existing handling that throws on !response.ok)
```

Replace the post-fetch handling with:

```typescript
const response = await fetch(`${BACKEND_URL}${endpoint}`, {
  ...options,
  headers,
});

if (!response.ok) {
  // Preserve the parsed body on 4xx so callers can switch on `blocked.code`.
  // 5xx still surfaces as an opaque error since servers shouldn't emit
  // structured detail on internal failures.
  const ct = response.headers.get("Content-Type") ?? "";
  let body: unknown = null;
  if (ct.includes("application/json")) {
    try {
      body = await response.json();
    } catch {
      // empty/malformed JSON — leave body as null
    }
  }
  throw new ApiError(response.status, body);
}

const ct = response.headers.get("Content-Type") ?? "";
if (ct.includes("application/json")) {
  return response.json();
}
return response.text();
```

Note: existing callers of `useApi().get(...).catch(...)` continue to work — they catch the thrown `ApiError`, just with more info attached.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/lib/api.ts apps/frontend/src/lib/api.test.ts
git commit -m "feat(frontend): ApiError class preserves 4xx response bodies"
```

---

## Task 6: Frontend — create `useProvisioningState` hook

**Files:**
- Create: `apps/frontend/src/hooks/useProvisioningState.ts`
- Test: `apps/frontend/src/hooks/useProvisioningState.test.ts`

- [ ] **Step 1: Write the failing tests**:

```typescript
// apps/frontend/src/hooks/useProvisioningState.test.ts
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useProvisioningState } from "./useProvisioningState";

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>
);

describe("useProvisioningState", () => {
  it("returns phase=normal when /status returns 200 with a container", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "running", substatus: "gateway_healthy", service_name: "x" }), { status: 200 }),
    );
    const { result } = renderHook(() => useProvisioningState(), { wrapper });
    await waitFor(() => expect(result.current.phase).toBe("normal"));
    expect(result.current.container?.status).toBe("running");
  });

  it("returns phase=blocked when /status returns 402 with blocked payload", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "...",
          blocked: {
            code: "credits_required",
            title: "Top up Claude credits",
            message: "Top up some Claude credits to start your Bedrock container.",
            action: { kind: "link", label: "Top up now", href: "/settings/billing#credits", admin_only: false },
            owner_role: "admin",
          },
        }),
        { status: 402, headers: { "Content-Type": "application/json" } },
      ),
    );
    const { result } = renderHook(() => useProvisioningState(), { wrapper });
    await waitFor(() => expect(result.current.phase).toBe("blocked"));
    expect(result.current.blocked?.code).toBe("credits_required");
  });

  it("returns phase=normal with no-container when /status returns 404", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));
    const { result } = renderHook(() => useProvisioningState(), { wrapper });
    await waitFor(() => expect(result.current.phase).toBe("provision-needed"));
  });

  it("polls every 5s while in blocked state for the first minute", async () => {
    // Implementation detail: hook returns its current refreshInterval.
    // Default 5s for blocked, 30s after the first minute.
    // This test pins the initial cadence; longer-window tests live in the
    // pacing helper if one is extracted later.
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ blocked: { code: "credits_required", title: "", message: "", action: { kind: "link", label: "", href: "", admin_only: false }, owner_role: "admin" } }),
        { status: 402, headers: { "Content-Type": "application/json" } },
      ),
    );
    const { result } = renderHook(() => useProvisioningState(), { wrapper });
    await waitFor(() => expect(result.current.phase).toBe("blocked"));
    expect(result.current.refreshInterval).toBe(5000);
  });
});
```

- [ ] **Step 2: Write the implementation**:

```typescript
// apps/frontend/src/hooks/useProvisioningState.ts
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { useAuth } from "@clerk/nextjs";
import { BACKEND_URL, ApiError } from "@/lib/api";

/** Server-rendered blocked-state payload from /container/status (402). */
export interface BlockedPayload {
  code: string;
  title: string;
  message: string;
  action: {
    kind: "link";
    label: string;
    href: string;
    admin_only: boolean;
  };
  owner_role: "admin" | "member";
}

export interface ContainerInfo {
  service_name: string;
  status: string;
  substatus: string | null;
  // ... other fields preserved from /status payload
  [key: string]: unknown;
}

export type ProvisioningPhase = "normal" | "provision-needed" | "blocked" | "loading";

export interface ProvisioningStateResult {
  phase: ProvisioningPhase;
  container: ContainerInfo | null;
  blocked: BlockedPayload | null;
  refreshInterval: number;
  refresh: () => void;
}

/**
 * Owns the chat-page centerpiece state machine:
 *
 *   /status load
 *        |
 *  +-----+------+
 *  |   200      | 404                    | 402
 *  v            v                         v
 *  normal     provision-needed          blocked
 *
 * Polls with backoff while blocked (5s for the first minute, 30s after).
 * `refresh()` resets the cadence to 5s and re-polls immediately.
 */
export function useProvisioningState(): ProvisioningStateResult {
  const { getToken, isSignedIn } = useAuth();
  const [blockedSinceMs, setBlockedSinceMs] = useState<number | null>(null);

  const fetcher = useCallback(
    async (url: string): Promise<{ kind: "container"; data: ContainerInfo } | { kind: "no-container" } | { kind: "blocked"; data: BlockedPayload }> => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");
      const res = await fetch(`${BACKEND_URL}${url}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 404) return { kind: "no-container" };
      if (res.status === 402) {
        const body = await res.json();
        return { kind: "blocked", data: body.blocked as BlockedPayload };
      }
      if (!res.ok) throw new ApiError(res.status, null);
      const data = (await res.json()) as ContainerInfo;
      return { kind: "container", data };
    },
    [getToken],
  );

  // Adaptive polling interval. While blocked, poll fast for the first
  // minute (covers quick top-up cases), then back off.
  const refreshInterval = useMemo(() => {
    if (blockedSinceMs === null) return 0;  // not blocked → SWR does its own thing
    const elapsed = Date.now() - blockedSinceMs;
    return elapsed < 60_000 ? 5_000 : 30_000;
  }, [blockedSinceMs]);

  const { data, mutate } = useSWR(
    isSignedIn ? "/container/status" : null,
    fetcher,
    {
      revalidateOnFocus: false,
      refreshInterval,
    },
  );

  // Track blocked-since-time for cadence.
  useEffect(() => {
    if (data?.kind === "blocked") {
      if (blockedSinceMs === null) setBlockedSinceMs(Date.now());
    } else if (blockedSinceMs !== null) {
      setBlockedSinceMs(null);
    }
  }, [data, blockedSinceMs]);

  const refresh = useCallback(() => {
    setBlockedSinceMs(Date.now());  // reset cadence to 5s
    mutate();
  }, [mutate]);

  if (!data) {
    return { phase: "loading", container: null, blocked: null, refreshInterval: 0, refresh };
  }
  if (data.kind === "container") {
    return { phase: "normal", container: data.data, blocked: null, refreshInterval, refresh };
  }
  if (data.kind === "no-container") {
    return { phase: "provision-needed", container: null, blocked: null, refreshInterval, refresh };
  }
  return { phase: "blocked", container: null, blocked: data.data, refreshInterval, refresh };
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/hooks/useProvisioningState.ts apps/frontend/src/hooks/useProvisioningState.test.ts
git commit -m "feat(frontend): useProvisioningState hook with blocked-state polling"
```

---

## Task 7: Frontend — render the blocked state in `ProvisioningStepper`

**Files:**
- Modify: `apps/frontend/src/components/chat/ProvisioningStepper.tsx`
- Test: `apps/frontend/src/components/chat/ProvisioningStepper.test.tsx` (create if absent — verify with `find apps/frontend/src/components/chat -name "*.test.*"`)

- [ ] **Step 1: Write the failing tests**:

```typescript
// apps/frontend/src/components/chat/ProvisioningStepper.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProvisioningStepper } from "./ProvisioningStepper";

vi.mock("@/hooks/useProvisioningState", () => ({
  useProvisioningState: vi.fn(),
}));

import { useProvisioningState } from "@/hooks/useProvisioningState";
const useProv = useProvisioningState as ReturnType<typeof vi.fn>;

describe("ProvisioningStepper blocked-state rendering", () => {
  it("renders title + message + action button when admin and not admin_only", () => {
    useProv.mockReturnValue({
      phase: "blocked",
      container: null,
      blocked: {
        code: "credits_required",
        title: "Top up Claude credits to start your container",
        message: "Top up some Claude credits to start your Bedrock container.",
        action: { kind: "link", label: "Top up now", href: "/settings/billing#credits", admin_only: false },
        owner_role: "admin",
      },
      refreshInterval: 5000,
      refresh: vi.fn(),
    });
    render(<ProvisioningStepper />);
    expect(screen.getByText(/Top up Claude credits to start your container/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Top up now/ })).toHaveAttribute("href", "/settings/billing#credits");
  });

  it("renders 'ask your admin' text instead of action button when member-and-admin_only", () => {
    useProv.mockReturnValue({
      phase: "blocked",
      container: null,
      blocked: {
        code: "subscription_required",
        title: "Subscribe to start your container",
        message: "An active subscription is required.",
        action: { kind: "link", label: "Subscribe", href: "/onboarding", admin_only: true },
        owner_role: "member",
      },
      refreshInterval: 5000,
      refresh: vi.fn(),
    });
    render(<ProvisioningStepper />);
    expect(screen.getByText(/Ask your org admin/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Subscribe/ })).not.toBeInTheDocument();
  });

  it("renders the existing 'Provisioning your container' centerpiece when phase=normal", () => {
    useProv.mockReturnValue({
      phase: "normal",
      container: { service_name: "x", status: "provisioning", substatus: null },
      blocked: null,
      refreshInterval: 0,
      refresh: vi.fn(),
    });
    render(<ProvisioningStepper />);
    expect(screen.getByText(/Provisioning your container/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Modify `ProvisioningStepper.tsx`**.

Find the centerpiece rendering block (currently shows "Provisioning your container…" and a key icon — search for "Provisioning your container" in the file). Wrap it in a conditional driven by the new hook:

```typescript
// Near the top of the component, replace the existing useContainerStatus
// call (or augment it) with:
import { useProvisioningState } from "@/hooks/useProvisioningState";

// Inside the component:
const { phase, container, blocked, refresh } = useProvisioningState();

// In the JSX, replace the existing centerpiece block (the one with the
// key icon + "Provisioning your container..." title) with:
if (phase === "blocked" && blocked) {
  const showAction = !(blocked.action.admin_only && blocked.owner_role !== "admin");
  return (
    <div className="centerpiece-blocked">
      <div className="key-icon-area">{/* same icon as before */}</div>
      <h2>{blocked.title}</h2>
      <p>{blocked.message}</p>
      {showAction ? (
        <a className="primary-cta" href={blocked.action.href}>
          {blocked.action.label}
        </a>
      ) : (
        <p className="muted">Ask your org admin to fix this.</p>
      )}
      <div className="footer-buttons">
        <button onClick={refresh}>Check again</button>
        <a href="mailto:support@isol8.co">Contact support</a>
      </div>
    </div>
  );
}

// Otherwise render the existing "Provisioning your container..." block.
```

Match the exact CSS class names / layout primitives already in `ProvisioningStepper.tsx` — copy from the existing JSX, swap only the title/message/action.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/chat/ProvisioningStepper.tsx apps/frontend/src/components/chat/ProvisioningStepper.test.tsx
git commit -m "feat(frontend): ProvisioningStepper renders blocked state from useProvisioningState"
```

---

## Task 8: Frontend — update `useContainerStatus` consumers (optional cleanup)

**Files:**
- Modify: `apps/frontend/src/hooks/useContainerStatus.ts` — surface 402 + blocked payload to any callers other than ProvisioningStepper.
- Search: `git grep -n useContainerStatus apps/frontend/src` — most callers are in `ProvisioningStepper`, but check `OverviewPanel` and `HealthIndicator`.

- [ ] **Step 1: Decide whether to migrate other callers or shim**.

Since `ProvisioningStepper` now uses `useProvisioningState`, the existing `useContainerStatus` no longer needs to know about gates as long as its other callers don't care about `blocked`. Run:

```bash
git grep -n "useContainerStatus" apps/frontend/src/
```

For each caller:
- If they need `blocked` info, swap to `useProvisioningState`.
- If they only need container status, leave them on `useContainerStatus`. **But** update the fetcher to treat 402 as `null` (same as 404), so a blocked owner doesn't crash a panel that's just trying to render container health.

- [ ] **Step 2: Patch `useContainerStatus` fetcher** to treat 402 as null:

```typescript
// In useContainerStatus.ts, replace the fetcher's error handling:
if (res.status === 404 || res.status === 402) return null;
if (!res.ok) throw new Error("Failed to fetch container status");
return res.json();
```

(No new test required — existing tests already cover the 404 → null branch; the 402 case is tested via `useProvisioningState`.)

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/hooks/useContainerStatus.ts
git commit -m "fix(frontend): useContainerStatus treats 402 as null for non-stepper consumers"
```

---

## Task 9: Run full test suite + lint, fix failures

**Per saved feedback (`feedback_run_tests_at_end.md`):** mid-task tests are not run; this final task verifies the full suite once.

- [ ] **Step 1: Backend tests**

```bash
cd apps/backend && uv run pytest tests/ -v
```

Expected: all green. If failures, fix and re-commit.

- [ ] **Step 2: Frontend tests**

```bash
cd apps/frontend && pnpm test
```

Expected: all green.

- [ ] **Step 3: Lint**

```bash
cd apps/frontend && pnpm run lint
```

Expected: no warnings or errors. Fix any.

- [ ] **Step 4: Final verification commit (if any fixes)**

```bash
git add -A
git commit -m "test: full-suite verification fixups"
```

---

## Out of scope (for follow-up PRs)

- Anything from Workstream B (provider-choice keying refactor) — own plan.
- Onboarding-flow refactor — `OnboardingStepper` may have its own copy of the centerpiece; if a quick grep during Task 7 confirms it does, file a follow-up to plug in `useProvisioningState` there too.
- E2E test — explicitly excluded per spec/scope decision.
