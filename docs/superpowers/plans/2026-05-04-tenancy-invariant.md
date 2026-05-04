# Tenancy Invariant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Test execution policy:** Per `feedback_write_tests_run_at_end.md`, write test files at each task but SKIP pytest/vitest invocations during the per-task workflow. Run `pnpm tsc --noEmit` (fast) per task to catch type errors. Final Task 9 runs the complete backend + frontend test suites.

**Goal:** Enforce the invariant "one Clerk user, one tenancy" via a backend invite-creation gate, a backend trial-checkout pending-invite gate, a frontend custom-invite dialog replacing Clerk's built-in modal, and a relaxed `ChatLayout` routing condition that honours pending invites regardless of `unsafeMetadata.onboarded`.

**Architecture:** Two gates (Gate A at invite creation, Gate B at personal trial-checkout), both validating against existing Clerk + DDB state — no new metadata flag, no DDB tenancy column. One frontend custom dialog replaces Clerk's `<CreateOrganization>`-bundled invite step. One observability-only webhook check logs invariant violations without blocking.

**Tech Stack:** Python 3.13 / FastAPI / pytest (backend), TypeScript / Next.js 16 / React 19 / vitest / @clerk/nextjs (frontend), Clerk Backend API for user/invitation lookup.

**Spec:** `docs/superpowers/specs/2026-05-04-tenancy-invariant-design.md`

---

## File Structure

**Backend — new:**
- `apps/backend/routers/orgs.py` — Gate A endpoint (`POST /api/v1/orgs/{org_id}/invitations`)
- `apps/backend/schemas/orgs.py` — request/response Pydantic models
- `apps/backend/tests/unit/routers/test_orgs_invitations.py` — Gate A coverage

**Backend — modified:**
- `apps/backend/core/services/clerk_admin.py` — add three Clerk API helpers (find user by email, create org invitation, list pending invitations for user)
- `apps/backend/main.py` — mount the new orgs router
- `apps/backend/routers/billing.py` — add Gate B to `/trial-checkout`
- `apps/backend/routers/webhooks.py` — add invariant-violation log to `_handle_organization_membership_created`
- `apps/backend/tests/unit/routers/test_billing_trial_checkout_guard.py` — extend with pending-invite cases
- `apps/backend/tests/unit/routers/test_webhooks.py` — extend with invariant-violation case

**Frontend — new:**
- `apps/frontend/src/components/onboarding/InviteTeammatesStep.tsx` — custom invite form
- `apps/frontend/src/components/onboarding/__tests__/InviteTeammatesStep.test.tsx`
- `apps/frontend/src/app/onboarding/__tests__/page.test.tsx`
- `apps/frontend/src/components/chat/__tests__/ChatLayout.test.tsx`

**Frontend — modified:**
- `apps/frontend/src/app/onboarding/page.tsx` — `skipInvitationScreen={true}` + render `<InviteTeammatesStep>` after org creation; remove "Skip invitations" escape hatch
- `apps/frontend/src/components/chat/ChatLayout.tsx` — drop `!isOnboarded` from `needsInvitationFlow`

---

## Task 1: Clerk admin API helpers (find user, create invitation, list pending invitations)

**Files:**
- Modify: `apps/backend/core/services/clerk_admin.py` (append three new functions)

**Context:** `clerk_admin.py` already wraps the Clerk Backend API for admin reads (`list_users`, `get_user`, `list_user_organizations`, etc.) and follows a consistent pattern: stub gracefully when `CLERK_SECRET_KEY` is unset, swallow network errors into a structured response, log warnings on HTTP failures. Add three new helpers in the same style.

- [ ] **Step 1: Add `find_user_by_email`** at the end of `apps/backend/core/services/clerk_admin.py`:

```python
async def find_user_by_email(email: str) -> dict | None:
    """Return the first Clerk user matching `email`, or None.

    Used by the invite-creation gate to detect "is this email already a
    Clerk user?" before forwarding to Clerk's createInvitation API.
    Stubs to None when CLERK_SECRET_KEY is unset.
    """
    if not settings.CLERK_SECRET_KEY:
        return None

    headers = {"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"}
    params = {"email_address": email, "limit": 1}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(
                f"{_CLERK_API_BASE}/users", headers=headers, params=params
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("clerk_admin.find_user_by_email network error: %s", e)
        return None

    if response.status_code >= 400:
        logger.warning(
            "clerk_admin.find_user_by_email HTTP %s for %s",
            response.status_code,
            email,
        )
        return None

    users = response.json() or []
    return users[0] if users else None
```

- [ ] **Step 2: Add `create_organization_invitation`** in the same file:

```python
async def create_organization_invitation(
    *,
    org_id: str,
    email: str,
    role: str,
    inviter_user_id: str,
) -> dict:
    """Create a Clerk org invitation. Returns the invitation dict on success.

    Raises HTTPException via the caller for non-201 responses — we want
    Clerk's error to surface to the org admin, not a silent no-op.
    `role` is a Clerk role key (e.g. "org:admin", "org:member").
    """
    if not settings.CLERK_SECRET_KEY:
        # Local-dev stub: return a fake invitation so the test path works.
        return {"id": f"orginv_stub_{email}", "stubbed": True}

    headers = {
        "Authorization": f"Bearer {settings.CLERK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "email_address": email,
        "role": role,
        "inviter_user_id": inviter_user_id,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        response = await client.post(
            f"{_CLERK_API_BASE}/organizations/{org_id}/invitations",
            headers=headers,
            json=body,
        )

    if response.status_code >= 400:
        logger.warning(
            "clerk_admin.create_organization_invitation HTTP %s org=%s email=%s body=%s",
            response.status_code,
            org_id,
            email,
            response.text,
        )
        # Surface Clerk's error verbatim so the admin sees real causes
        # (duplicate invitation, invalid role, etc.). Caller wraps in
        # HTTPException with the same status code.
        from fastapi import HTTPException
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()
```

- [ ] **Step 3: Add `list_pending_invitations_for_user`** in the same file:

```python
async def list_pending_invitations_for_user(user_id: str) -> list[dict]:
    """List a Clerk user's pending org invitations. Empty list if none.

    Used by Gate B (personal trial-checkout) to refuse a personal
    subscription when the caller has unaccepted org invitations.
    Stubs to [] when CLERK_SECRET_KEY is unset.
    """
    if not settings.CLERK_SECRET_KEY:
        return []

    headers = {"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"}
    params = {"status": "pending", "limit": 100}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(
                f"{_CLERK_API_BASE}/users/{user_id}/organization_invitations",
                headers=headers,
                params=params,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "clerk_admin.list_pending_invitations_for_user network error: %s", e
        )
        return []

    if response.status_code >= 400:
        logger.warning(
            "clerk_admin.list_pending_invitations_for_user HTTP %s user=%s",
            response.status_code,
            user_id,
        )
        return []

    payload = response.json()
    # Clerk paginated responses have shape {data: [...], total_count: int}
    # for invitation listings — extract data list when present.
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"] or []
    return payload if isinstance(payload, list) else []
```

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/services/clerk_admin.py
git commit -m "$(cat <<'EOF'
feat(clerk-admin): helpers for tenancy invariant — find user, create invitation, list pending invitations

Adds find_user_by_email, create_organization_invitation, and
list_pending_invitations_for_user. All follow the existing stub-on-no-
secret pattern. create_organization_invitation raises HTTPException
on non-2xx so the calling endpoint surfaces Clerk's error verbatim.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Backend schemas for orgs router

**Files:**
- Create: `apps/backend/schemas/orgs.py`

- [ ] **Step 1: Create `apps/backend/schemas/orgs.py`** with the request and response models:

```python
"""Pydantic schemas for the organizations API surface."""

from typing import Literal

from pydantic import BaseModel, EmailStr


class CreateInvitationRequest(BaseModel):
    """Body for POST /api/v1/orgs/{org_id}/invitations.

    `role` matches Clerk's role-key convention. Default org members get
    "org:member"; org admins get "org:admin". The frontend invite form
    surfaces a role select that maps to these two strings.
    """

    email: EmailStr
    role: Literal["org:admin", "org:member"] = "org:member"


class CreateInvitationResponse(BaseModel):
    invitation_id: str
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/schemas/orgs.py
git commit -m "$(cat <<'EOF'
feat(schemas): orgs invite request/response models

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Backend orgs router — Gate A invite-creation endpoint

**Files:**
- Create: `apps/backend/routers/orgs.py`
- Create: `apps/backend/tests/unit/routers/test_orgs_invitations.py`
- Modify: `apps/backend/main.py` (mount the router)

**Context:** Gate A enforces the tenancy invariant at invite-creation. The endpoint is org-admin-only, looks up the invitee in Clerk by email, refuses with 409 if the invitee has an active or trialing personal `billing_accounts` row, and otherwise forwards to Clerk's createInvitation API. `require_org_admin` already raises 403 for org members; we add a same-org check on top so an admin of org A can't invite into org B.

- [ ] **Step 1: Write the test file** `apps/backend/tests/unit/routers/test_orgs_invitations.py`:

```python
"""Tests for POST /api/v1/orgs/{org_id}/invitations — Gate A."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import AuthContext
from routers import orgs


@pytest.fixture
def app():
    """Mount the orgs router for isolated testing."""
    app = FastAPI()
    app.include_router(orgs.router, prefix="/api/v1/orgs")
    return app


@pytest.fixture
def admin_auth():
    """Auth context for an admin of org_test."""
    return AuthContext(
        user_id="user_admin",
        org_id="org_test",
        org_role="org:admin",
        org_slug="testorg",
        org_permissions=["org:sys_memberships:manage"],
        email="admin@example.com",
    )


@pytest.fixture
def member_auth():
    """Auth context for a basic member of org_test."""
    return AuthContext(
        user_id="user_member",
        org_id="org_test",
        org_role="org:member",
        org_slug="testorg",
        org_permissions=[],
        email="member@example.com",
    )


@pytest.fixture
def personal_auth():
    """Auth context for a personal user (no org)."""
    return AuthContext(user_id="user_personal", email="personal@example.com")


def _override_auth(app, ctx):
    """Override get_current_user dependency for the duration of one test."""
    from core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: ctx


def test_invite_to_email_with_no_clerk_user_succeeds(app, admin_auth):
    _override_auth(app, admin_auth)
    with patch("routers.orgs.clerk_admin") as mock_clerk, patch(
        "routers.orgs.billing_repo"
    ) as mock_billing:
        mock_clerk.find_user_by_email = AsyncMock(return_value=None)
        mock_clerk.create_organization_invitation = AsyncMock(
            return_value={"id": "orginv_abc"}
        )
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "newperson@example.com", "role": "org:member"},
        )
    assert resp.status_code == 201
    assert resp.json() == {"invitation_id": "orginv_abc"}
    mock_billing.get_by_owner_id.assert_not_called()
    mock_clerk.create_organization_invitation.assert_awaited_once()


def test_invite_to_email_with_clerk_user_no_billing_succeeds(app, admin_auth):
    _override_auth(app, admin_auth)
    with patch("routers.orgs.clerk_admin") as mock_clerk, patch(
        "routers.orgs.billing_repo"
    ) as mock_billing:
        mock_clerk.find_user_by_email = AsyncMock(
            return_value={"id": "user_existing"}
        )
        mock_billing.get_by_owner_id = AsyncMock(return_value=None)
        mock_clerk.create_organization_invitation = AsyncMock(
            return_value={"id": "orginv_def"}
        )
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "existing@example.com", "role": "org:member"},
        )
    assert resp.status_code == 201
    mock_clerk.create_organization_invitation.assert_awaited_once()


def test_invite_to_email_with_inactive_billing_succeeds(app, admin_auth):
    """Canceled or expired personal subs no longer count as active tenancies."""
    _override_auth(app, admin_auth)
    with patch("routers.orgs.clerk_admin") as mock_clerk, patch(
        "routers.orgs.billing_repo"
    ) as mock_billing:
        mock_clerk.find_user_by_email = AsyncMock(
            return_value={"id": "user_existing"}
        )
        mock_billing.get_by_owner_id = AsyncMock(
            return_value={"owner_id": "user_existing", "subscription_status": "canceled"}
        )
        mock_clerk.create_organization_invitation = AsyncMock(
            return_value={"id": "orginv_ghi"}
        )
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "ex-customer@example.com", "role": "org:member"},
        )
    assert resp.status_code == 201


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_invite_to_email_with_active_personal_returns_409(app, admin_auth, status):
    _override_auth(app, admin_auth)
    with patch("routers.orgs.clerk_admin") as mock_clerk, patch(
        "routers.orgs.billing_repo"
    ) as mock_billing:
        mock_clerk.find_user_by_email = AsyncMock(
            return_value={"id": "user_existing"}
        )
        mock_billing.get_by_owner_id = AsyncMock(
            return_value={"owner_id": "user_existing", "subscription_status": status}
        )
        mock_clerk.create_organization_invitation = AsyncMock()
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "subscriber@example.com", "role": "org:member"},
        )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "personal_user_exists"
    assert "subscriber@example.com" in body["detail"]["message"]
    mock_clerk.create_organization_invitation.assert_not_awaited()


def test_non_admin_caller_returns_403(app, member_auth):
    _override_auth(app, member_auth)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/orgs/org_test/invitations",
        json={"email": "nope@example.com", "role": "org:member"},
    )
    assert resp.status_code == 403


def test_personal_caller_returns_403(app, personal_auth):
    """Personal users have no org_id — require_org_admin must reject."""
    _override_auth(app, personal_auth)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/orgs/org_test/invitations",
        json={"email": "nope@example.com", "role": "org:member"},
    )
    # require_org_admin lets personal context pass-through; the org_id
    # mismatch check below handles this case → 403.
    assert resp.status_code == 403


def test_caller_in_different_org_returns_403(app, admin_auth):
    """Admin of org_test cannot invite to org_other."""
    _override_auth(app, admin_auth)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/orgs/org_other/invitations",
        json={"email": "x@example.com", "role": "org:member"},
    )
    assert resp.status_code == 403


def test_default_role_is_member(app, admin_auth):
    """Omitting role in the body defaults to org:member."""
    _override_auth(app, admin_auth)
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return {"id": "orginv_default"}

    with patch("routers.orgs.clerk_admin") as mock_clerk, patch(
        "routers.orgs.billing_repo"
    ):
        mock_clerk.find_user_by_email = AsyncMock(return_value=None)
        mock_clerk.create_organization_invitation = AsyncMock(side_effect=_capture)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "default@example.com"},
        )
    assert resp.status_code == 201
    assert captured["role"] == "org:member"
```

- [ ] **Step 2: Create the router** `apps/backend/routers/orgs.py`:

```python
"""Organization management endpoints — invite creation gate (Gate A)."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthContext, get_current_user, require_org_admin
from core.observability.metrics import put_metric
from core.repositories import billing_repo
from core.services import clerk_admin
from schemas.orgs import CreateInvitationRequest, CreateInvitationResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/{org_id}/invitations",
    response_model=CreateInvitationResponse,
    status_code=201,
    summary="Create an org invitation (Gate A — tenancy invariant)",
    description=(
        "Refuses with 409 if the invitee already has an active or trialing "
        "personal Isol8 subscription. Otherwise forwards to Clerk's "
        "createInvitation API."
    ),
    operation_id="create_org_invitation",
)
async def create_invitation(
    org_id: str,
    body: CreateInvitationRequest,
    auth: AuthContext = Depends(get_current_user),
) -> CreateInvitationResponse:
    # Caller must be an admin of THIS org. require_org_admin only checks
    # the role within the active org; the path-vs-token org_id match
    # closes the cross-org admin escalation gap.
    require_org_admin(auth)
    if auth.org_id != org_id:
        raise HTTPException(403, "Cannot invite to a different org")

    invitee_email = body.email.lower()

    # Tenancy invariant: refuse if invitee has an active personal sub.
    existing = await clerk_admin.find_user_by_email(invitee_email)
    if existing is not None:
        account = await billing_repo.get_by_owner_id(existing["id"])
        if account and account.get("subscription_status") in ("active", "trialing"):
            put_metric("orgs.invitation.blocked", dimensions={"reason": "personal_user_exists"})
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "personal_user_exists",
                    "message": (
                        f"{body.email} already has an active personal Isol8 "
                        "subscription. They must cancel it before they can "
                        "be invited to an organization."
                    ),
                },
            )

    invite = await clerk_admin.create_organization_invitation(
        org_id=org_id,
        email=invitee_email,
        role=body.role,
        inviter_user_id=auth.user_id,
    )
    put_metric("orgs.invitation.created", dimensions={"role": body.role})
    return CreateInvitationResponse(invitation_id=invite["id"])
```

- [ ] **Step 3: Mount the router in `apps/backend/main.py`.** Find the section where existing routers are registered (e.g. `app.include_router(billing.router, prefix="/api/v1/billing", ...)`) and add:

```python
from routers import orgs as orgs_router  # add to imports near the other router imports

# ... in the router-registration block:
app.include_router(orgs_router.router, prefix="/api/v1/orgs", tags=["orgs"])
```

- [ ] **Step 4: Type-check and commit**

```bash
cd apps/backend && uv run ruff check routers/orgs.py schemas/orgs.py && cd -
git add apps/backend/routers/orgs.py apps/backend/schemas/orgs.py \
        apps/backend/tests/unit/routers/test_orgs_invitations.py \
        apps/backend/main.py
git commit -m "$(cat <<'EOF'
feat(orgs): Gate A — refuse invites to existing personal subscribers

POST /api/v1/orgs/{org_id}/invitations is org-admin-only and rejects
with 409 if the invitee already has a billing_accounts row with
subscription_status in (active, trialing). Otherwise forwards to
Clerk's createInvitation API.

Tenancy invariant Step 2a — see spec at
docs/superpowers/specs/2026-05-04-tenancy-invariant-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Backend Gate B — pending-invite check on `/trial-checkout`

**Files:**
- Modify: `apps/backend/routers/billing.py` (insert check around line 350, before `_get_billing_account`)
- Modify: `apps/backend/tests/unit/routers/test_billing_trial_checkout_guard.py` (extend existing file)

**Context:** Gate B refuses a personal trial-checkout when the caller has any pending org invitations. The check only runs when `auth.is_org_context` is false — an org-context call to `/trial-checkout` is creating an *org* subscription, not a personal one, so pending invites are irrelevant there.

- [ ] **Step 1: Add the test cases** to the existing `apps/backend/tests/unit/routers/test_billing_trial_checkout_guard.py`. The file already uses `async_client` (personal-mode default override) + `@patch("routers.billing.billing_repo")`. Reuse the same pattern for Gate B. Append to the bottom of the file:

```python
@pytest.mark.asyncio
@patch("routers.billing.clerk_admin")
@patch("routers.billing.billing_repo")
async def test_trial_checkout_with_pending_org_invitation_returns_409(
    mock_repo, mock_clerk, async_client
):
    """Caller in personal context with a pending invite must be redirected
    to /onboarding/invitations, not allowed to subscribe personally."""
    # No prior billing row — gate B fires before billing-row checks.
    mock_repo.get_by_owner_id = AsyncMock(return_value=None)
    mock_clerk.list_pending_invitations_for_user = AsyncMock(
        return_value=[
            {
                "id": "orginv_pending",
                "public_organization_data": {"name": "Acme Org"},
            }
        ]
    )

    resp = await async_client.post(
        "/api/v1/billing/trial-checkout",
        json={"provider_choice": "bedrock_claude"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "pending_org_invitation"
    assert "Acme Org" in body["detail"]["message"]
    assert body["detail"]["redirect_to"] == "/onboarding/invitations"


@pytest.mark.asyncio
@patch("routers.billing.clerk_admin")
@patch("routers.billing.billing_repo")
async def test_trial_checkout_with_no_pending_invitations_passes_gate_b(
    mock_repo, mock_clerk, async_client
):
    """Empty pending-invitations list passes Gate B; downstream checks
    still apply (here we expect a 4xx from a downstream stage, NOT a 409
    with code=pending_org_invitation)."""
    mock_repo.get_by_owner_id = AsyncMock(return_value=None)
    mock_clerk.list_pending_invitations_for_user = AsyncMock(return_value=[])

    resp = await async_client.post(
        "/api/v1/billing/trial-checkout",
        json={"provider_choice": "bedrock_claude"},
    )
    # If the response IS a 409, it must NOT be the pending-invite kind.
    if resp.status_code == 409:
        body = resp.json()
        detail = body.get("detail")
        # Gate B's detail is a dict with code; the older "already_subscribed:*"
        # guard returns a string. Either way, code != pending_org_invitation.
        if isinstance(detail, dict):
            assert detail.get("code") != "pending_org_invitation"
    mock_clerk.list_pending_invitations_for_user.assert_awaited_once()


@pytest.mark.asyncio
async def test_trial_checkout_in_org_context_skips_pending_invite_check(
    app, mock_org_admin_user
):
    """Org-context callers (org admins running org trial-checkout) must
    skip the pending-invite check — they're creating an org subscription,
    not a personal one."""
    from core.auth import get_current_user
    from httpx import AsyncClient, ASGITransport

    app.dependency_overrides[get_current_user] = mock_org_admin_user
    try:
        with patch("routers.billing.clerk_admin") as mock_clerk, patch(
            "routers.billing.billing_repo"
        ) as mock_repo:
            mock_clerk.list_pending_invitations_for_user = AsyncMock()
            mock_repo.get_by_owner_id = AsyncMock(
                return_value={
                    "owner_id": "org_test_456",
                    "stripe_subscription_id": "sub_existing",
                    "subscription_status": "active",  # forces a 409, but NOT from gate B
                }
            )
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                await ac.post(
                    "/api/v1/billing/trial-checkout",
                    json={"provider_choice": "bedrock_claude"},
                )
            # Critical assertion: gate B was NOT invoked for org context.
            mock_clerk.list_pending_invitations_for_user.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Add the gate to `apps/backend/routers/billing.py`.** Find the import block at the top and add `clerk_admin`:

```python
from core.services import clerk_admin
```

Then in `create_trial_checkout`, AFTER the existing `provider_choice` validation and the `chatgpt_oauth + is_org_context` 403 check (around line 343), and BEFORE `if auth.is_org_context: require_org_admin(auth)`:

```python
    # Tenancy invariant (Gate B): refuse a PERSONAL trial-checkout when
    # the caller has any pending org invitations. We only check the
    # personal path — an org-context call to /trial-checkout is the
    # admin subscribing the org, which can never have personal pending
    # invites by construction.
    if not auth.is_org_context:
        pending = await clerk_admin.list_pending_invitations_for_user(auth.user_id)
        if pending:
            org_name = (
                (pending[0].get("public_organization_data") or {}).get("name")
                or "an organization"
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "pending_org_invitation",
                    "message": (
                        f"You have a pending invitation to {org_name}. "
                        "Accept it before subscribing personally."
                    ),
                    "redirect_to": "/onboarding/invitations",
                },
            )
```

- [ ] **Step 3: Type-check and commit**

```bash
cd apps/backend && uv run ruff check routers/billing.py && cd -
git add apps/backend/routers/billing.py \
        apps/backend/tests/unit/routers/test_billing_trial_checkout_guard.py
git commit -m "$(cat <<'EOF'
feat(billing): Gate B — refuse personal trial-checkout when pending org invites exist

Adds the second tenancy-invariant gate. /trial-checkout in personal
context queries clerk_admin.list_pending_invitations_for_user; any
non-empty result returns 409 with redirect_to=/onboarding/invitations.

Tenancy invariant Step 2b.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Webhook invariant-violation observer

**Files:**
- Modify: `apps/backend/routers/webhooks.py` (add a check at the top of `_handle_organization_membership_created` around line 381)
- Modify: `apps/backend/tests/unit/routers/test_webhooks.py` (extend with the new case)

**Context:** Defense-in-depth observability ONLY. If Gates A+B both leak somehow, the `organizationMembership.created` webhook is the last place to see the dual state. We log + emit a metric — we DO NOT block, since Clerk has already accepted the membership and refusing here would just orphan the ECS provisioning.

- [ ] **Step 1: Add the test case** to `apps/backend/tests/unit/routers/test_webhooks.py`:

```python
async def test_membership_created_with_active_personal_logs_violation(caplog):
    """If a new org member already has an active personal billing row,
    we log loudly + emit a metric, but provisioning still proceeds."""
    import logging
    from unittest.mock import AsyncMock, patch

    payload = {
        "type": "organizationMembership.created",
        "data": {
            "organization": {"id": "org_xyz", "created_by": "user_admin"},
            "public_user_data": {"user_id": "user_member_dirty"},
            "email_addresses": [{"email_address": "member@example.com"}],
        },
    }
    with patch("routers.webhooks.billing_repo") as mock_billing, patch(
        "routers.webhooks._get_paperclip_provisioning"
    ) as mock_prov, patch("routers.webhooks.put_metric") as mock_metric:
        mock_billing.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_member_dirty",
                "owner_type": "personal",
                "subscription_status": "active",
            }
        )
        mock_prov.return_value.provision_member = AsyncMock()

        with caplog.at_level(logging.ERROR, logger="routers.webhooks"):
            from routers.webhooks import _handle_organization_membership_created
            await _handle_organization_membership_created(payload["data"])

    # Loud log
    assert any(
        "tenancy_invariant.violated" in rec.message for rec in caplog.records
    )
    # Metric emitted
    metric_names = [call.args[0] for call in mock_metric.call_args_list]
    assert "tenancy_invariant.violation" in metric_names
    # Provisioning still proceeded
    mock_prov.return_value.provision_member.assert_awaited_once()
```

- [ ] **Step 2: Add the observer to `_handle_organization_membership_created`** in `apps/backend/routers/webhooks.py`. After the existing input-validation block (after line 397's `return`), and BEFORE the owner-email lookup (line 399), insert:

```python
    # Defense-in-depth: Gates A+B should have prevented dual-tenancy.
    # If a new org member somehow has an active personal billing row,
    # log loudly and emit a metric — but don't block, because Clerk
    # has already accepted the membership and refusing here would just
    # orphan the org provisioning.
    try:
        from core.repositories import billing_repo  # local import keeps cold-start lean

        personal_account = await billing_repo.get_by_owner_id(user_id)
        if personal_account and personal_account.get("subscription_status") in (
            "active",
            "trialing",
        ):
            logger.error(
                "tenancy_invariant.violated user=%s org=%s personal_status=%s",
                user_id,
                org_id,
                personal_account.get("subscription_status"),
            )
            put_metric(
                "tenancy_invariant.violation", dimensions={"path": "membership_created"}
            )
    except Exception:  # noqa: BLE001
        # Never let an observability check break a real provisioning path.
        logger.exception("tenancy invariant probe failed for user=%s org=%s", user_id, org_id)
```

(Verify the existing imports at the top of webhooks.py already have `put_metric` — if not, add `from core.observability.metrics import put_metric`.)

- [ ] **Step 3: Type-check and commit**

```bash
cd apps/backend && uv run ruff check routers/webhooks.py && cd -
git add apps/backend/routers/webhooks.py apps/backend/tests/unit/routers/test_webhooks.py
git commit -m "$(cat <<'EOF'
feat(webhooks): observe tenancy-invariant violations on member.created

Defense-in-depth observer. If both gates leak (which shouldn't
happen), the org-membership-created webhook is the last place to
see the dual state. Logs error + emits metric; does NOT block
provisioning.

Tenancy invariant Step 2e.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Frontend `<InviteTeammatesStep>` custom invite component

**Files:**
- Create: `apps/frontend/src/components/onboarding/InviteTeammatesStep.tsx`
- Create: `apps/frontend/src/components/onboarding/__tests__/InviteTeammatesStep.test.tsx`

**Context:** Replaces Clerk's bundled invite step. Renders a form (email + role select) that posts to `/api/v1/orgs/{org_id}/invitations` via `useApi()`. Renders the 409 error message inline from `detail.message`. Includes a "Skip for now" link that just calls `onComplete()`.

- [ ] **Step 1: Write the test file** `apps/frontend/src/components/onboarding/__tests__/InviteTeammatesStep.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { InviteTeammatesStep } from "../InviteTeammatesStep";

const mockPost = vi.fn();
vi.mock("@/lib/api", () => ({
  useApi: () => ({ post: mockPost }),
}));

describe("InviteTeammatesStep", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("posts to /orgs/{org_id}/invitations with email and role", async () => {
    mockPost.mockResolvedValueOnce({ invitation_id: "orginv_1" });
    const onComplete = vi.fn();
    render(<InviteTeammatesStep orgId="org_test" onComplete={onComplete} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "teammate@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send invite/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/orgs/org_test/invitations",
        expect.objectContaining({ email: "teammate@example.com", role: "org:member" }),
      );
    });
  });

  it("renders the 409 personal_user_exists message inline", async () => {
    mockPost.mockRejectedValueOnce({
      status: 409,
      body: {
        detail: {
          code: "personal_user_exists",
          message:
            "subscriber@example.com already has an active personal Isol8 subscription. They must cancel it before they can be invited to an organization.",
        },
      },
    });
    render(<InviteTeammatesStep orgId="org_test" onComplete={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "subscriber@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send invite/i }));

    expect(
      await screen.findByText(/already has an active personal Isol8 subscription/i),
    ).toBeInTheDocument();
  });

  it("calls onComplete when 'Done' is clicked", () => {
    const onComplete = vi.fn();
    render(<InviteTeammatesStep orgId="org_test" onComplete={onComplete} />);
    fireEvent.click(screen.getByRole("button", { name: /done/i }));
    expect(onComplete).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Create the component** `apps/frontend/src/components/onboarding/InviteTeammatesStep.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Mail, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/api";

type Role = "org:admin" | "org:member";

interface SentInvite {
  email: string;
  role: Role;
  invitation_id: string;
}

export function InviteTeammatesStep({
  orgId,
  onComplete,
}: {
  orgId: string;
  onComplete: () => void;
}) {
  const api = useApi();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("org:member");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<SentInvite[]>([]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.post<{ invitation_id: string }>(
        `/orgs/${orgId}/invitations`,
        { email: email.trim(), role },
      );
      setSent((prev) => [
        ...prev,
        { email: email.trim(), role, invitation_id: result.invitation_id },
      ]);
      setEmail("");
    } catch (err: unknown) {
      // useApi's post rejects with { status, body } shape.
      const e = err as { status?: number; body?: { detail?: { message?: string } } };
      const msg = e.body?.detail?.message ?? "Failed to send invitation. Please try again.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-6 bg-background">
      <div className="text-center">
        <Mail className="h-10 w-10 mx-auto mb-3 text-primary" />
        <h1 className="text-2xl font-bold">Invite your teammates</h1>
        <p className="text-muted-foreground mt-2">
          They&apos;ll get an email to join your organization on Isol8.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-3 w-full max-w-md px-4"
      >
        <div>
          <label htmlFor="invite-email" className="block text-sm font-medium mb-1">
            Email
          </label>
          <Input
            id="invite-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="teammate@example.com"
            disabled={submitting}
          />
        </div>
        <div>
          <label htmlFor="invite-role" className="block text-sm font-medium mb-1">
            Role
          </label>
          <select
            id="invite-role"
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            disabled={submitting}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="org:member">Member</option>
            <option value="org:admin">Admin</option>
          </select>
        </div>
        {error && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}
        <Button type="submit" disabled={submitting || !email.trim()}>
          <Plus className="mr-1 h-4 w-4" />
          {submitting ? "Sending..." : "Send invite"}
        </Button>
      </form>

      {sent.length > 0 && (
        <ul className="w-full max-w-md px-4 space-y-2">
          {sent.map((s) => (
            <li
              key={s.invitation_id}
              className="rounded-md border border-border bg-card px-3 py-2 text-sm"
            >
              ✓ Invited <strong>{s.email}</strong>{" "}
              <span className="text-muted-foreground">({s.role.replace("org:", "")})</span>
            </li>
          ))}
        </ul>
      )}

      <Button variant="ghost" onClick={onComplete}>
        Done
      </Button>
    </div>
  );
}
```

- [ ] **Step 3: Type-check and commit**

```bash
cd apps/frontend && pnpm tsc --noEmit && cd -
git add apps/frontend/src/components/onboarding/InviteTeammatesStep.tsx \
        apps/frontend/src/components/onboarding/__tests__/InviteTeammatesStep.test.tsx
git commit -m "$(cat <<'EOF'
feat(onboarding): InviteTeammatesStep — custom invite form

Replaces Clerk's bundled invite step in <CreateOrganization>.
POSTs to /api/v1/orgs/{org_id}/invitations and renders the 409
personal_user_exists message inline.

Tenancy invariant Step 2c (component).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Frontend `/onboarding` page — wire the custom step + remove escape hatch

**Files:**
- Modify: `apps/frontend/src/app/onboarding/page.tsx`
- Create: `apps/frontend/src/app/onboarding/__tests__/page.test.tsx`

**Context:** Two changes:
1. `<CreateOrganization skipInvitationScreen={false}>` → `skipInvitationScreen={true}`. Mount `<InviteTeammatesStep>` AFTER Clerk creates the org (signaled by `organization` becoming non-null while `mode === "org"`).
2. When `pendingInvitations.length > 0`, the `mode = "invitations"` derivation must NOT be overridable to `"choose"`. Remove the "Skip invitations" button.

- [ ] **Step 1: Write the test file** `apps/frontend/src/app/onboarding/__tests__/page.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import OnboardingPage from "../page";

// Minimal Clerk mocks — pending invitations + no memberships + no org.
const buildClerkMocks = (overrides: { invitations?: unknown[]; memberships?: unknown[] } = {}) => ({
  useAuth: () => ({ isLoaded: true }),
  useUser: () => ({ user: { update: vi.fn() } }),
  useOrganization: () => ({ organization: null, isLoaded: true }),
  useOrganizationList: () => ({
    userMemberships: { data: overrides.memberships ?? [] },
    userInvitations: {
      data: overrides.invitations ?? [],
      revalidate: vi.fn(),
    },
    isLoaded: true,
    setActive: vi.fn(),
  }),
  CreateOrganization: () => <div>CreateOrganization mock</div>,
});

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ useApi: () => ({ syncUser: vi.fn() }) }));
vi.mock("posthog-js/react", () => ({ usePostHog: () => null }));

describe("OnboardingPage", () => {
  it("forces invitation mode when pending invitations exist — no Skip button", async () => {
    vi.doMock("@clerk/nextjs", () =>
      buildClerkMocks({
        invitations: [
          {
            id: "orginv_1",
            publicOrganizationData: { name: "Acme Org" },
            accept: vi.fn(),
          },
        ],
      }),
    );
    const { default: Page } = await import("../page");
    render(<Page />);
    // Invitation card is shown
    expect(screen.getByText(/Acme Org|Pending invitation/i)).toBeInTheDocument();
    // No "Skip invitations" escape hatch
    expect(screen.queryByRole("button", { name: /skip invitations/i })).toBeNull();
  });

  it("renders the personal/org chooser when no pending invitations", async () => {
    vi.doMock("@clerk/nextjs", () => buildClerkMocks());
    const { default: Page } = await import("../page");
    render(<Page />);
    expect(screen.getByRole("button", { name: /personal/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /organization/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Modify `apps/frontend/src/app/onboarding/page.tsx`.** Replace the `mode` derivation (line 36-38) to remove the override-when-invitations-exist escape:

```tsx
  // Derive mode. When the user has pending invitations, force the
  // invitations screen — there's no escape hatch to personal because
  // the tenancy invariant says they shouldn't be both. The user can
  // still choose which invitation to accept (if multiple), but cannot
  // route around them into personal onboarding.
  const [explicitMode, setExplicitMode] = useState<"choose" | "personal" | "org" | "invitations" | null>(null);
  const forcedInvitations = isLoaded && orgsLoaded && pendingInvitations.length > 0;
  const mode = forcedInvitations
    ? "invitations"
    : (explicitMode ?? "choose");
  const setMode = setExplicitMode;
```

- [ ] **Step 3: Remove the "Skip invitations" button** from the invitations-mode block. Delete the surrounding `<div>` (lines 169-174 in the original):

```tsx
        // DELETE this block:
        // <div className="flex flex-col items-center gap-2 mt-4">
        //   <p className="text-sm text-muted-foreground">Or set up your own workspace instead</p>
        //   <Button variant="ghost" onClick={() => setMode("choose")}>
        //     Skip invitations
        //   </Button>
        // </div>
```

- [ ] **Step 4: Switch `<CreateOrganization>` to skip Clerk's invite step + add the post-create `<InviteTeammatesStep>`.** Replace the `mode === "org"` block (around line 179) with:

```tsx
  if (mode === "org") {
    // After Clerk creates the org, `organization` becomes non-null.
    // We still need to mount our custom invite step before redirecting,
    // so we render <InviteTeammatesStep> on top of `mode === "org"` once
    // the org exists.
    if (organization) {
      return (
        <InviteTeammatesStep
          orgId={organization.id}
          onComplete={async () => {
            try {
              await user?.update({ unsafeMetadata: { onboarded: true } });
            } catch {
              // best-effort; ChatLayout's auto-activate fallback covers this
            }
            router.push("/chat");
          }}
        />
      );
    }
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-6 bg-background">
        <div className="text-center mb-4">
          <h1 className="text-2xl font-bold">Create your organization</h1>
          <p className="text-muted-foreground mt-2">
            Your team will share agents, workspace, and billing.
          </p>
        </div>
        <CreateOrganization
          // skipInvitationScreen={true} → Clerk creates the org and stops.
          // Our <InviteTeammatesStep> takes over (rendered above once
          // `organization` resolves) so all invites route through our
          // backend's Gate A.
          afterCreateOrganizationUrl="/onboarding"
          skipInvitationScreen={true}
        />
        <Button variant="ghost" onClick={() => setMode("choose")}>
          Back
        </Button>
      </div>
    );
  }
```

Add the import at the top of the file:

```tsx
import { InviteTeammatesStep } from "@/components/onboarding/InviteTeammatesStep";
```

- [ ] **Step 5: Update the org-active redirect effect** (around line 63). Today, when `organization` becomes non-null AND `mode === "org"`, the effect short-circuits via `if (mode === "org") return;` so the old in-Clerk invite screen could render. Now we keep the same short-circuit because `<InviteTeammatesStep>` lives inside the `mode === "org"` branch and DOES the redirect itself via `onComplete`. No change needed to this effect — it's already correct under the new flow. (Just verify that the comment block about "let CreateOrganization handle its flow" is still accurate; if not, update to "let CreateOrganization + InviteTeammatesStep handle the flow".)

- [ ] **Step 6: Type-check and commit**

```bash
cd apps/frontend && pnpm tsc --noEmit && cd -
git add apps/frontend/src/app/onboarding/page.tsx \
        apps/frontend/src/app/onboarding/__tests__/page.test.tsx
git commit -m "$(cat <<'EOF'
feat(onboarding): route invites through Gate A + remove skip-invitations escape

Switches <CreateOrganization> to skipInvitationScreen=true and renders
our custom <InviteTeammatesStep> after the org is created. Removes the
"Skip invitations" button so a user with a pending invite cannot bypass
into personal onboarding.

Tenancy invariant Step 2c (page wiring) + 2d (escape removed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Frontend `ChatLayout` — relax `needsInvitationFlow`

**Files:**
- Modify: `apps/frontend/src/components/chat/ChatLayout.tsx` (line 138)
- Create: `apps/frontend/src/components/chat/__tests__/ChatLayout.test.tsx`

**Context:** Removing `!isOnboarded` from `needsInvitationFlow` is the load-bearing fix for users like aden who completed personal onboarding earlier and were later invited to an org. The `unsafeMetadata.onboarded=true` flag should mean "user has chosen *some* tenancy at some point" — not "user is done forever." Pending invites override it because the invariant says they shouldn't be in a different tenancy yet.

- [ ] **Step 1: Write the test file** `apps/frontend/src/components/chat/__tests__/ChatLayout.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

// We test the routing behavior by asserting router.replace is called
// with /onboarding under specific Clerk states. ChatLayout has a lot of
// peripheral state (gateway, file-tree, etc.) — we mock the heavy parts
// and focus on the router gate.

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

let clerkState: {
  isSignedIn: boolean;
  user: { unsafeMetadata?: Record<string, unknown> } | null;
  organization: { id: string } | null;
  memberships: unknown[];
  invitations: unknown[];
};

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isSignedIn: clerkState.isSignedIn, isLoaded: true }),
  useUser: () => ({ user: clerkState.user, isLoaded: true }),
  useOrganization: () => ({ organization: clerkState.organization, isLoaded: true }),
  useOrganizationList: () => ({
    userMemberships: { data: clerkState.memberships },
    userInvitations: { data: clerkState.invitations },
    isLoaded: true,
    setActive: vi.fn(),
  }),
  UserButton: () => null,
}));

// Stub the heavy hooks ChatLayout pulls in — they're not relevant to the test.
vi.mock("@/hooks/useGateway", () => ({ useGateway: () => ({}) }));
vi.mock("@/hooks/useAgentChat", () => ({ useAgentChat: () => ({}) }));
vi.mock("@/hooks/useAgents", () => ({ useAgents: () => ({ agents: [], refresh: vi.fn() }) }));
vi.mock("@/hooks/useWorkspaceFiles", () => ({ useWorkspaceFiles: () => ({}) }));
vi.mock("@/lib/api", () => ({ useApi: () => ({ syncUser: vi.fn() }) }));

describe("ChatLayout — needsInvitationFlow", () => {
  beforeEach(() => {
    replaceMock.mockReset();
  });

  it("redirects an already-onboarded user with a pending invite to /onboarding", async () => {
    clerkState = {
      isSignedIn: true,
      user: { unsafeMetadata: { onboarded: true } }, // ← would have blocked the redirect under the old logic
      organization: null,
      memberships: [],
      invitations: [{ id: "orginv_1" }],
    };
    const { default: ChatLayout } = await import("../ChatLayout");
    render(<ChatLayout />);
    expect(replaceMock).toHaveBeenCalledWith("/onboarding");
  });

  it("does NOT redirect when user has memberships (already in an org)", async () => {
    clerkState = {
      isSignedIn: true,
      user: { unsafeMetadata: { onboarded: true } },
      organization: { id: "org_a" }, // active org → not "needs invitation flow"
      memberships: [{ organization: { id: "org_a" } }],
      invitations: [],
    };
    const { default: ChatLayout } = await import("../ChatLayout");
    render(<ChatLayout />);
    expect(replaceMock).not.toHaveBeenCalledWith("/onboarding");
  });
});
```

- [ ] **Step 2: Update `ChatLayout.tsx` line 138.** Old:

```tsx
  const needsInvitationFlow = clerkLoaded && isSignedIn === true && !isOnboarded && !hasMemberships && hasPendingInvitations && !organization;
```

New:

```tsx
  // Tenancy invariant: pending invitations beat the unsafeMetadata.onboarded
  // flag. A user who completed personal onboarding earlier and was later
  // invited to an org MUST be routed to /onboarding/invitations to accept,
  // because the invariant forbids personal-tenancy + pending-org-invite
  // coexisting.
  const needsInvitationFlow = clerkLoaded && isSignedIn === true && !hasMemberships && hasPendingInvitations && !organization;
```

- [ ] **Step 3: Type-check and commit**

```bash
cd apps/frontend && pnpm tsc --noEmit && cd -
git add apps/frontend/src/components/chat/ChatLayout.tsx \
        apps/frontend/src/components/chat/__tests__/ChatLayout.test.tsx
git commit -m "$(cat <<'EOF'
fix(chat-layout): pending invitations override unsafeMetadata.onboarded

Drops `!isOnboarded` from needsInvitationFlow. An already-onboarded
user with a pending org invite was silently bypassing /onboarding,
landing on /chat in personal context, and re-triggering the
ProviderPicker — the cofounder bug. Pending invites now force the
invitation flow regardless of the onboarded flag.

Tenancy invariant Step 2d.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Final verification — run all tests

**Files:** None modified. Runs the full backend + frontend test suites and frontend type-check.

- [ ] **Step 1: Backend test suite**

```bash
cd apps/backend && uv run pytest tests/ -v 2>&1 | tail -60
```

Expected: zero failures. New tests from Tasks 3, 4, 5 pass; existing tests remain green.

- [ ] **Step 2: Frontend test suite**

```bash
cd apps/frontend && pnpm test --run 2>&1 | tail -60
```

Expected: zero failures. New tests from Tasks 6, 7, 8 pass.

- [ ] **Step 3: Frontend type-check**

```bash
cd apps/frontend && pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Lint pass (Turbo)**

```bash
turbo run lint 2>&1 | tail -30
```

Expected: clean.

- [ ] **Step 5: If all four steps pass, the implementation is complete.** No commit at this step (verification only). Open the PR.
