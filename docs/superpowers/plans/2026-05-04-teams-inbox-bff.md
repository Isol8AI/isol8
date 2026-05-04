# Teams Inbox BFF (PR #3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land all backend BFF endpoints needed to support the Inbox deep port (sub-project #3) — pure backend, no UI changes. After this PR merges, the new endpoints exist but aren't called yet; PR #3b/c/d will wire the frontend.

**Architecture:** Each new route follows the existing teams BFF pattern: `Depends(_ctx)` resolves Clerk auth → per-user Paperclip session cookie via `paperclip_user_session`; routes call `_agents._admin().method_name(...)` to forward to upstream Paperclip. Response bodies pass through verbatim except where existing endpoints already do light reshaping (kept unchanged).

**Tech Stack:** Python 3.12 / FastAPI / pydantic v2 / httpx / pytest + AsyncMock + TestClient.

**Spec:** [`docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md`](../specs/2026-05-04-teams-inbox-deep-port-design.md) (sub-project #3a section).

---

## File structure

| File | Action | Responsibility |
|---|---|---|
| `apps/backend/core/services/paperclip_admin_client.py` | Modify | Add 12 new methods for the upstream routes Inbox + IssueDetail need |
| `apps/backend/routers/teams/schemas.py` | Modify | Add `AddCommentBody`, `PatchInboxFiltersQuery` (no body schemas needed for the no-body mutations like archive/mark-read) |
| `apps/backend/routers/teams/inbox.py` | Modify | Expand `GET /inbox` to accept query params; add `/inbox/runs`, `/inbox/live-runs` |
| `apps/backend/routers/teams/issues.py` | Modify | Add archive/unarchive/mark-read/mark-unread + comments routes |
| `apps/backend/routers/teams/approvals.py` | Modify | Add `GET /approvals/{id}` for detail |
| `apps/backend/routers/teams/runs.py` | Create | NEW: `GET /runs/{id}` — agent run detail |
| `apps/backend/routers/teams/projects.py` | Create | NEW: `GET /projects` — list company projects (filter dropdown source) |
| `apps/backend/routers/teams/__init__.py` | Modify | Mount new `runs` and `projects` routers |
| `apps/backend/tests/unit/services/test_paperclip_admin_client_inbox.py` | Create | Admin-client method unit tests for the 12 new methods |
| `apps/backend/tests/unit/routers/teams/test_inbox.py` | Modify | Tests for expanded `/inbox` query params + `/inbox/runs` + `/inbox/live-runs` |
| `apps/backend/tests/unit/routers/teams/test_issues.py` | Modify | Tests for archive/unarchive/mark-read/mark-unread + comments |
| `apps/backend/tests/unit/routers/teams/test_approvals.py` | Modify | Test for `GET /approvals/{id}` |
| `apps/backend/tests/unit/routers/teams/test_runs.py` | Create | Tests for `/runs/{id}` |
| `apps/backend/tests/unit/routers/teams/test_projects.py` | Create | Tests for `/projects` |

---

## Task 1: Admin-client methods for new upstream endpoints

**Files:**
- Modify: `apps/backend/core/services/paperclip_admin_client.py`
- Test: `apps/backend/tests/unit/services/test_paperclip_admin_client_inbox.py`

The existing `PaperclipAdminClient` already has methods for inbox-lite, dismiss, list/get/create/patch issues, list_approvals, approve, reject, list_members. We add 12 new methods to cover the routes the Inbox deep port needs.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/services/test_paperclip_admin_client_inbox.py`:

```python
"""Unit tests for the new admin-client methods used by Inbox deep port (PR #3a).

Verify each method calls the right upstream URL with the right HTTP verb,
forwards the session cookie via headers, and returns the parsed JSON body.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def admin_client_with_fake_http():
    """Build a PaperclipAdminClient with a fake httpx-like http object."""
    from core.services.paperclip_admin_client import PaperclipAdminClient

    fake_http = MagicMock()
    # Default: succeed with empty JSON body. Tests override per-call.
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"{}"
    resp.json.return_value = {}
    resp.text = "{}"
    fake_http.get = AsyncMock(return_value=resp)
    fake_http.post = AsyncMock(return_value=resp)
    fake_http.delete = AsyncMock(return_value=resp)
    fake_http.patch = AsyncMock(return_value=resp)

    client = PaperclipAdminClient(http_client=fake_http)
    return client, fake_http


@pytest.mark.asyncio
async def test_list_company_heartbeat_runs(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.list_company_heartbeat_runs(
        company_id="co_x", session_cookie="c=1", status="failed"
    )
    http.get.assert_awaited_once()
    call = http.get.call_args
    assert call.args[0] == "/api/companies/co_x/heartbeat-runs"
    assert call.kwargs.get("params", {}).get("status") == "failed"


@pytest.mark.asyncio
async def test_list_company_live_runs(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.list_company_live_runs(company_id="co_x", session_cookie="c=1")
    http.get.assert_awaited_once()
    assert http.get.call_args.args[0] == "/api/companies/co_x/live-runs"


@pytest.mark.asyncio
async def test_get_heartbeat_run(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.get_heartbeat_run(run_id="run_42", session_cookie="c=1")
    http.get.assert_awaited_once()
    assert http.get.call_args.args[0] == "/api/heartbeat-runs/run_42"


@pytest.mark.asyncio
async def test_archive_issue(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.archive_issue(issue_id="iss_7", session_cookie="c=1")
    http.post.assert_awaited_once()
    call = http.post.call_args
    assert call.args[0] == "/api/issues/iss_7/inbox-archive"


@pytest.mark.asyncio
async def test_unarchive_issue(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.unarchive_issue(issue_id="iss_7", session_cookie="c=1")
    http.delete.assert_awaited_once()
    assert http.delete.call_args.args[0] == "/api/issues/iss_7/inbox-archive"


@pytest.mark.asyncio
async def test_mark_issue_read(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.mark_issue_read(issue_id="iss_7", session_cookie="c=1")
    http.post.assert_awaited_once()
    assert http.post.call_args.args[0] == "/api/issues/iss_7/read"


@pytest.mark.asyncio
async def test_mark_issue_unread(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.mark_issue_unread(issue_id="iss_7", session_cookie="c=1")
    http.delete.assert_awaited_once()
    assert http.delete.call_args.args[0] == "/api/issues/iss_7/read"


@pytest.mark.asyncio
async def test_list_issue_comments(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.list_issue_comments(issue_id="iss_7", session_cookie="c=1")
    http.get.assert_awaited_once()
    assert http.get.call_args.args[0] == "/api/issues/iss_7/comments"


@pytest.mark.asyncio
async def test_add_issue_comment(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.add_issue_comment(
        issue_id="iss_7", body={"body": "hello"}, session_cookie="c=1"
    )
    http.post.assert_awaited_once()
    call = http.post.call_args
    assert call.args[0] == "/api/issues/iss_7/comments"
    assert call.kwargs.get("json") == {"body": "hello"}


@pytest.mark.asyncio
async def test_get_approval_detail(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.get_approval(approval_id="apv_1", session_cookie="c=1")
    http.get.assert_awaited_once()
    assert http.get.call_args.args[0] == "/api/approvals/apv_1"


@pytest.mark.asyncio
async def test_list_company_projects(admin_client_with_fake_http):
    client, http = admin_client_with_fake_http
    await client.list_company_projects(company_id="co_x", session_cookie="c=1")
    http.get.assert_awaited_once()
    assert http.get.call_args.args[0] == "/api/companies/co_x/projects"


@pytest.mark.asyncio
async def test_list_inbox_with_filters(admin_client_with_fake_http):
    """The expanded inbox listing accepts filter params and forwards them
    on the inbox-lite endpoint."""
    client, http = admin_client_with_fake_http
    await client.list_inbox_for_session_user(
        session_cookie="c=1",
        params={"tab": "mine", "status": "todo", "search": "fix"},
    )
    http.get.assert_awaited_once()
    call = http.get.call_args
    assert call.args[0] == "/api/agents/me/inbox-lite"
    assert call.kwargs.get("params") == {
        "tab": "mine", "status": "todo", "search": "fix",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd apps/backend && uv run pytest tests/unit/services/test_paperclip_admin_client_inbox.py -v --no-cov
```

Expected: 12 FAILS, all with `AttributeError: 'PaperclipAdminClient' object has no attribute '<method>'` (or, for the existing `list_inbox_for_session_user` test: signature mismatch).

- [ ] **Step 3: Implement the new admin-client methods**

In `apps/backend/core/services/paperclip_admin_client.py`, find the existing `list_inbox_for_session_user` method (currently around line 730) and modify its signature to accept optional `params`:

```python
    async def list_inbox_for_session_user(
        self,
        *,
        session_cookie: str,
        params: Optional[dict[str, Any]] = None,
    ) -> list:
        """List the signed-in agent's inbox-lite issue rows.

        Maps to ``GET /api/agents/me/inbox-lite``. The optional ``params``
        dict is forwarded as query string so the BFF can pass through
        filter selections (tab, status, project, assignee, creator, search,
        limit) verbatim. Empty/None params is allowed for back-compat with
        the existing tier-1 caller.
        """
        return await self._get(
            "/api/agents/me/inbox-lite",
            session_cookie=session_cookie,
            params=params,
        )
```

Update `_get` to accept an optional `params` kwarg (currently it doesn't pass query params). Find `_get` (around line 266) and modify:

```python
    async def _get(
        self,
        path: str,
        session_cookie: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict:
        resp = await self._http.get(
            path,
            params=params,
            headers=self._headers(session_cookie),
        )
        if resp.status_code >= 400:
            raise PaperclipApiError(
                f"GET {path} -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json() if resp.content else {}
```

Then ADD these 11 new methods. Insert them in logical groups — keep "Inbox" block, "Approvals" block, "Issues" block intact. Add new groups for "Heartbeat runs" and "Projects":

```python
    # ------------------------------------------------------------------
    # Heartbeat runs (NEW for #3a — Inbox deep port)
    # ------------------------------------------------------------------

    async def list_company_heartbeat_runs(
        self,
        *,
        session_cookie: str,
        company_id: str,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> dict:
        """List heartbeat runs for the company.

        Maps to ``GET /api/companies/{companyId}/heartbeat-runs``. The
        ``status`` filter (e.g. "failed") is forwarded as a query param
        so the BFF's Inbox "Runs" tab can show only failed runs.
        """
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if limit is not None:
            params["limit"] = str(limit)
        return await self._get(
            f"/api/companies/{company_id}/heartbeat-runs",
            session_cookie=session_cookie,
            params=params or None,
        )

    async def list_company_live_runs(
        self,
        *,
        session_cookie: str,
        company_id: str,
    ) -> dict:
        """List currently-running heartbeat runs for the company.

        Maps to ``GET /api/companies/{companyId}/live-runs``. Used by the
        Inbox UI to show a pulsing "Live" badge on issues with active runs.
        """
        return await self._get(
            f"/api/companies/{company_id}/live-runs",
            session_cookie=session_cookie,
        )

    async def get_heartbeat_run(
        self,
        *,
        session_cookie: str,
        run_id: str,
    ) -> dict:
        """Fetch a single heartbeat run by id.

        Maps to ``GET /api/heartbeat-runs/{runId}``. Used by the agent-run
        detail page that Inbox failed-run rows link into.
        """
        return await self._get(
            f"/api/heartbeat-runs/{run_id}",
            session_cookie=session_cookie,
        )

    # ------------------------------------------------------------------
    # Issue inbox state (NEW for #3a)
    # ------------------------------------------------------------------

    async def archive_issue(
        self,
        *,
        session_cookie: str,
        issue_id: str,
    ) -> dict:
        """Archive an issue from the inbox.

        Maps to ``POST /api/issues/{id}/inbox-archive``. The 49-line BFF
        stub previously had a ``dismiss`` endpoint that mapped to
        ``/api/inbox/{itemId}/dismiss`` — that's a different upstream
        concept (inbox dismissals table) and we keep it. ``archive_issue``
        is the modern Paperclip flow that flips an issue's
        ``inbox_archived_at`` column.
        """
        return await self._post(
            f"/api/issues/{issue_id}/inbox-archive",
            json={},
            session_cookie=session_cookie,
        )

    async def unarchive_issue(
        self,
        *,
        session_cookie: str,
        issue_id: str,
    ) -> dict:
        """Restore an archived issue back to the inbox.

        Maps to ``DELETE /api/issues/{id}/inbox-archive``. Drives the
        Inbox UI's undo-archive toast.
        """
        return await self._delete(
            f"/api/issues/{issue_id}/inbox-archive",
            session_cookie=session_cookie,
        )

    async def mark_issue_read(
        self,
        *,
        session_cookie: str,
        issue_id: str,
    ) -> dict:
        """Mark an issue as read for the signed-in user.

        Maps to ``POST /api/issues/{id}/read``.
        """
        return await self._post(
            f"/api/issues/{issue_id}/read",
            json={},
            session_cookie=session_cookie,
        )

    async def mark_issue_unread(
        self,
        *,
        session_cookie: str,
        issue_id: str,
    ) -> dict:
        """Mark an issue as unread for the signed-in user.

        Maps to ``DELETE /api/issues/{id}/read``.
        """
        return await self._delete(
            f"/api/issues/{issue_id}/read",
            session_cookie=session_cookie,
        )

    # ------------------------------------------------------------------
    # Issue comments (NEW for #3a)
    # ------------------------------------------------------------------

    async def list_issue_comments(
        self,
        *,
        session_cookie: str,
        issue_id: str,
    ) -> dict:
        """List comments on an issue.

        Maps to ``GET /api/issues/{id}/comments``.
        """
        return await self._get(
            f"/api/issues/{issue_id}/comments",
            session_cookie=session_cookie,
        )

    async def add_issue_comment(
        self,
        *,
        session_cookie: str,
        issue_id: str,
        body: dict,
    ) -> dict:
        """Add a comment to an issue. Body is whitelisted by the BFF.

        Maps to ``POST /api/issues/{id}/comments``.
        """
        return await self._post(
            f"/api/issues/{issue_id}/comments",
            json=body,
            session_cookie=session_cookie,
        )

    # ------------------------------------------------------------------
    # Approvals (NEW for #3a — detail endpoint)
    # ------------------------------------------------------------------

    async def get_approval(
        self,
        *,
        session_cookie: str,
        approval_id: str,
    ) -> dict:
        """Fetch a single approval by id.

        Maps to ``GET /api/approvals/{id}``. Used by the approval detail
        page that Inbox approval rows link into.
        """
        return await self._get(
            f"/api/approvals/{approval_id}",
            session_cookie=session_cookie,
        )

    # ------------------------------------------------------------------
    # Projects (NEW for #3a — filter dropdown source)
    # ------------------------------------------------------------------

    async def list_company_projects(
        self,
        *,
        session_cookie: str,
        company_id: str,
    ) -> dict:
        """List projects for the company.

        Maps to ``GET /api/companies/{companyId}/projects``. Used by the
        Inbox project-filter dropdown.
        """
        return await self._get(
            f"/api/companies/{company_id}/projects",
            session_cookie=session_cookie,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd apps/backend && uv run pytest tests/unit/services/test_paperclip_admin_client_inbox.py -v --no-cov
```

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/paperclip_admin_client.py apps/backend/tests/unit/services/test_paperclip_admin_client_inbox.py
git commit -m "feat(teams): admin-client methods for inbox deep port"
```

---

## Task 2: Expand `GET /teams/inbox` for filter query params + add `/inbox/runs` and `/inbox/live-runs`

**Files:**
- Modify: `apps/backend/routers/teams/inbox.py`
- Test: `apps/backend/tests/unit/routers/teams/test_inbox.py`

- [ ] **Step 1: Write the failing tests**

Append these tests to `apps/backend/tests/unit/routers/teams/test_inbox.py` (after the existing tests):

```python
def test_list_inbox_forwards_filter_params(client, monkeypatch):
    """The expanded /inbox accepts query params (tab, status, project,
    assignee, creator, search, limit) and forwards them verbatim to the
    upstream inbox-lite endpoint."""
    admin = MagicMock()
    admin.list_inbox_for_session_user = AsyncMock(return_value=[])
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/inbox",
        params={
            "tab": "mine",
            "status": "todo",
            "project": "proj_1",
            "assignee": "agent_2",
            "creator": "user_3",
            "search": "fix bug",
            "limit": 250,
        },
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.list_inbox_for_session_user.assert_awaited_once()
    call = admin.list_inbox_for_session_user.call_args
    assert call.kwargs["session_cookie"] == "cookie"
    assert call.kwargs["params"] == {
        "tab": "mine",
        "status": "todo",
        "project": "proj_1",
        "assignee": "agent_2",
        "creator": "user_3",
        "search": "fix bug",
        "limit": "250",
    }


def test_list_inbox_omits_unset_filter_params(client, monkeypatch):
    """Filter params that are not provided must NOT be forwarded as
    empty strings to upstream — empty params dict (or None) instead."""
    admin = MagicMock()
    admin.list_inbox_for_session_user = AsyncMock(return_value=[])
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get("/api/v1/teams/inbox", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    call = admin.list_inbox_for_session_user.call_args
    # No filter params -> params should be None or {}.
    assert call.kwargs.get("params") in (None, {})


def test_list_inbox_runs_returns_failed_runs(client, monkeypatch):
    """`GET /teams/inbox/runs` lists failed heartbeat runs (the ones the
    Inbox 'Runs' tab needs)."""
    admin = MagicMock()
    admin.list_company_heartbeat_runs = AsyncMock(
        return_value={"runs": [{"id": "run_1", "status": "failed"}]}
    )
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get("/api/v1/teams/inbox/runs", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"runs": [{"id": "run_1", "status": "failed"}]}
    admin.list_company_heartbeat_runs.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
        status="failed",
    )


def test_list_inbox_live_runs(client, monkeypatch):
    """`GET /teams/inbox/live-runs` returns currently-running runs for the
    'Live' badge on Inbox rows."""
    admin = MagicMock()
    admin.list_company_live_runs = AsyncMock(
        return_value={"runs": [{"id": "run_live"}]}
    )
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/inbox/live-runs",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.list_company_live_runs.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_inbox.py -v --no-cov
```

Expected: 4 new tests FAIL (the 3 existing tests still pass).

- [ ] **Step 3: Implement**

Replace the contents of `apps/backend/routers/teams/inbox.py` with:

```python
"""Teams BFF — Inbox.

Read-mostly resource. Reuses the shared ``_ctx`` Depends helper and
shared ``_admin()`` singleton from ``routers.teams.agents`` so we
don't duplicate the auth chain or leak a fresh httpx client per
request. ``_admin`` is referenced via the imported module (rather
than imported by name) so unit tests can monkeypatch
``agents._admin`` once and have every Teams router pick it up.

PR #3a expands this from the 49-line tier-1 stub to a full Inbox
surface: filter-aware listing + heartbeat-run + live-run sub-routes.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from . import agents as _agents
from .deps import TeamsContext

router = APIRouter()
_ctx = _agents._ctx


@router.get("/inbox")
async def list_inbox(
    ctx: TeamsContext = Depends(_ctx),
    tab: Optional[str] = Query(default=None, pattern=r"^(mine|recent|all|unread)$"),
    status: Optional[str] = Query(default=None, max_length=40),
    project: Optional[str] = Query(default=None, max_length=80),
    assignee: Optional[str] = Query(default=None, max_length=80),
    creator: Optional[str] = Query(default=None, max_length=80),
    search: Optional[str] = Query(default=None, max_length=200),
    limit: Optional[int] = Query(default=None, ge=1, le=500),
):
    """List inbox items for the signed-in user, filter-aware.

    Calls ``GET /api/agents/me/inbox-lite`` upstream. Filter params are
    forwarded verbatim. Response is reshaped from the raw issue array
    into the ``{items: [...]}`` envelope the InboxPanel expects (kept
    from the tier-1 stub for back-compat — PR #3c will switch the panel
    to consume the full upstream Issue shape).
    """
    params: dict[str, str] = {}
    if tab is not None:
        params["tab"] = tab
    if status is not None:
        params["status"] = status
    if project is not None:
        params["project"] = project
    if assignee is not None:
        params["assignee"] = assignee
    if creator is not None:
        params["creator"] = creator
    if search is not None:
        params["search"] = search
    if limit is not None:
        params["limit"] = str(limit)

    rows = await _agents._admin().list_inbox_for_session_user(
        session_cookie=ctx.session_cookie,
        params=params or None,
    )
    if not isinstance(rows, list):
        rows = []
    items = [
        {
            "id": row.get("id"),
            "type": row.get("status") or "issue",
            "title": row.get("title") or row.get("identifier") or "(untitled)",
            "createdAt": row.get("updatedAt"),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    return {"items": items}


@router.post("/inbox/{item_id}/dismiss")
async def dismiss_inbox(item_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Dismiss an inbox item by id."""
    return await _agents._admin().dismiss_inbox_item(
        item_id=item_id,
        session_cookie=ctx.session_cookie,
    )


@router.get("/inbox/runs")
async def list_inbox_runs(ctx: TeamsContext = Depends(_ctx)):
    """List failed heartbeat runs — the source for the Inbox 'Runs' tab.

    Forwards ``status="failed"`` to upstream so we only surface runs
    that actually need user attention.
    """
    return await _agents._admin().list_company_heartbeat_runs(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
        status="failed",
    )


@router.get("/inbox/live-runs")
async def list_inbox_live_runs(ctx: TeamsContext = Depends(_ctx)):
    """List currently-running heartbeat runs for the 'Live' badge."""
    return await _agents._admin().list_company_live_runs(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_inbox.py -v --no-cov
```

Expected: 7 passed (3 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/teams/inbox.py apps/backend/tests/unit/routers/teams/test_inbox.py
git commit -m "feat(teams): inbox listing accepts filter params + runs/live-runs sub-routes"
```

---

## Task 3: Issue archive/unarchive/mark-read/mark-unread mutations

**Files:**
- Modify: `apps/backend/routers/teams/issues.py`
- Test: `apps/backend/tests/unit/routers/teams/test_issues.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/unit/routers/teams/test_issues.py`:

```python
def test_archive_issue(client, monkeypatch):
    """`POST /teams/issues/{id}/archive` archives the issue from the inbox."""
    admin = MagicMock()
    admin.archive_issue = AsyncMock(return_value={"ok": True})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.post(
        "/api/v1/teams/issues/iss_1/archive",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.archive_issue.assert_awaited_once_with(
        issue_id="iss_1", session_cookie="cookie",
    )


def test_unarchive_issue(client, monkeypatch):
    """`POST /teams/issues/{id}/unarchive` (undo) restores the issue."""
    admin = MagicMock()
    admin.unarchive_issue = AsyncMock(return_value={"ok": True})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.post(
        "/api/v1/teams/issues/iss_1/unarchive",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.unarchive_issue.assert_awaited_once_with(
        issue_id="iss_1", session_cookie="cookie",
    )


def test_mark_issue_read(client, monkeypatch):
    admin = MagicMock()
    admin.mark_issue_read = AsyncMock(return_value={"ok": True})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.post(
        "/api/v1/teams/issues/iss_1/mark-read",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.mark_issue_read.assert_awaited_once_with(
        issue_id="iss_1", session_cookie="cookie",
    )


def test_mark_issue_unread(client, monkeypatch):
    admin = MagicMock()
    admin.mark_issue_unread = AsyncMock(return_value={"ok": True})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.post(
        "/api/v1/teams/issues/iss_1/mark-unread",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.mark_issue_unread.assert_awaited_once_with(
        issue_id="iss_1", session_cookie="cookie",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_issues.py -v --no-cov
```

Expected: 4 new tests FAIL with 404 (routes don't exist yet).

- [ ] **Step 3: Implement**

Add these 4 routes to `apps/backend/routers/teams/issues.py` (immediately after the existing `patch_issue`):

```python
@router.post("/issues/{issue_id}/archive")
async def archive_issue(issue_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Archive an issue from the inbox.

    Maps to upstream ``POST /api/issues/{id}/inbox-archive``. The Inbox
    UI fades the row out + shows an undo toast for ~8s.
    """
    return await _agents._admin().archive_issue(
        issue_id=issue_id,
        session_cookie=ctx.session_cookie,
    )


@router.post("/issues/{issue_id}/unarchive")
async def unarchive_issue(issue_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Restore an archived issue back to the inbox.

    Maps to upstream ``DELETE /api/issues/{id}/inbox-archive``. Drives the
    undo-archive toast.
    """
    return await _agents._admin().unarchive_issue(
        issue_id=issue_id,
        session_cookie=ctx.session_cookie,
    )


@router.post("/issues/{issue_id}/mark-read")
async def mark_issue_read(issue_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Mark an issue as read for the signed-in user.

    Maps to upstream ``POST /api/issues/{id}/read``.
    """
    return await _agents._admin().mark_issue_read(
        issue_id=issue_id,
        session_cookie=ctx.session_cookie,
    )


@router.post("/issues/{issue_id}/mark-unread")
async def mark_issue_unread(issue_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Mark an issue as unread for the signed-in user.

    Maps to upstream ``DELETE /api/issues/{id}/read``.
    """
    return await _agents._admin().mark_issue_unread(
        issue_id=issue_id,
        session_cookie=ctx.session_cookie,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_issues.py -v --no-cov
```

Expected: existing tests + 4 new = all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/teams/issues.py apps/backend/tests/unit/routers/teams/test_issues.py
git commit -m "feat(teams): issue archive/unarchive/mark-read/mark-unread routes"
```

---

## Task 4: Issue comments (list + post)

**Files:**
- Modify: `apps/backend/routers/teams/schemas.py`
- Modify: `apps/backend/routers/teams/issues.py`
- Test: `apps/backend/tests/unit/routers/teams/test_issues.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/unit/routers/teams/test_issues.py`:

```python
def test_list_issue_comments(client, monkeypatch):
    admin = MagicMock()
    admin.list_issue_comments = AsyncMock(
        return_value={"comments": [{"id": "cmt_1", "body": "hi"}]}
    )
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/issues/iss_1/comments",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    assert r.json() == {"comments": [{"id": "cmt_1", "body": "hi"}]}
    admin.list_issue_comments.assert_awaited_once_with(
        issue_id="iss_1", session_cookie="cookie",
    )


def test_add_issue_comment(client, monkeypatch):
    """POST `/teams/issues/{id}/comments` with whitelisted body."""
    admin = MagicMock()
    admin.add_issue_comment = AsyncMock(
        return_value={"id": "cmt_new", "body": "hello"}
    )
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.post(
        "/api/v1/teams/issues/iss_1/comments",
        json={"body": "hello"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.add_issue_comment.assert_awaited_once_with(
        issue_id="iss_1",
        body={"body": "hello"},
        session_cookie="cookie",
    )


def test_add_issue_comment_rejects_extra_fields(client):
    """Body schema is strict — extras (esp. adapterType) must 422."""
    r = client.post(
        "/api/v1/teams/issues/iss_1/comments",
        json={"body": "hello", "adapterType": "evil"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 422


def test_add_issue_comment_requires_body_field(client):
    """Empty body field is invalid."""
    r = client.post(
        "/api/v1/teams/issues/iss_1/comments",
        json={},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_issues.py -v --no-cov
```

Expected: 4 new tests FAIL.

- [ ] **Step 3: Add the schema**

In `apps/backend/routers/teams/schemas.py`, add this class at the end of the file:

```python
class AddCommentBody(_Strict):
    """Body for ``POST /teams/issues/{id}/comments``.

    Whitelisted to ``body`` (the comment text) only — same defense-in-depth
    as ``CreateIssueBody`` to prevent ``adapterType``/``adapterConfig``
    smuggling through the comment payload.
    """

    body: str = Field(min_length=1, max_length=20000)
```

- [ ] **Step 4: Implement the routes**

In `apps/backend/routers/teams/issues.py`, modify the import line:

```python
from .schemas import AddCommentBody, CreateIssueBody, PatchIssueBody
```

Then add these 2 routes (after the mutations from Task 3):

```python
@router.get("/issues/{issue_id}/comments")
async def list_issue_comments(
    issue_id: str, ctx: TeamsContext = Depends(_ctx)
):
    """List comments on an issue.

    Maps to upstream ``GET /api/issues/{id}/comments``.
    """
    return await _agents._admin().list_issue_comments(
        issue_id=issue_id,
        session_cookie=ctx.session_cookie,
    )


@router.post("/issues/{issue_id}/comments")
async def add_issue_comment(
    issue_id: str,
    body: AddCommentBody,
    ctx: TeamsContext = Depends(_ctx),
):
    """Post a comment on an issue. Body is whitelisted to ``{body: str}``."""
    return await _agents._admin().add_issue_comment(
        issue_id=issue_id,
        body=body.model_dump(),
        session_cookie=ctx.session_cookie,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_issues.py -v --no-cov
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/routers/teams/schemas.py apps/backend/routers/teams/issues.py apps/backend/tests/unit/routers/teams/test_issues.py
git commit -m "feat(teams): issue comments (list + post) with strict body schema"
```

---

## Task 5: Approval detail (`GET /approvals/{id}`)

**Files:**
- Modify: `apps/backend/routers/teams/approvals.py`
- Test: `apps/backend/tests/unit/routers/teams/test_approvals.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/unit/routers/teams/test_approvals.py`:

```python
def test_get_approval_detail(client, monkeypatch):
    """`GET /teams/approvals/{id}` returns upstream's full approval detail
    shape verbatim."""
    admin = MagicMock()
    admin.get_approval = AsyncMock(
        return_value={
            "id": "apv_1",
            "status": "pending",
            "type": "tool_call",
            "payload": {"tool": "shell", "args": "ls -la"},
            "createdAt": "2026-05-04T01:00:00Z",
        }
    )
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/approvals/apv_1",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "apv_1"
    assert body["status"] == "pending"
    admin.get_approval.assert_awaited_once_with(
        approval_id="apv_1", session_cookie="cookie",
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_approvals.py -v --no-cov
```

Expected: 1 new test FAILS with 404.

- [ ] **Step 3: Implement**

Add this route to `apps/backend/routers/teams/approvals.py` (after the existing `reject` route):

```python
@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Fetch a single approval by id.

    Maps to upstream ``GET /api/approvals/{id}``. Used by the approval
    detail page that Inbox approval rows link into.
    """
    return await _agents._admin().get_approval(
        approval_id=approval_id,
        session_cookie=ctx.session_cookie,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_approvals.py -v --no-cov
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/teams/approvals.py apps/backend/tests/unit/routers/teams/test_approvals.py
git commit -m "feat(teams): approval detail endpoint"
```

---

## Task 6: New `runs.py` router — `GET /runs/{id}`

**Files:**
- Create: `apps/backend/routers/teams/runs.py`
- Modify: `apps/backend/routers/teams/__init__.py`
- Test: `apps/backend/tests/unit/routers/teams/test_runs.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/routers/teams/test_runs.py`:

```python
"""Tests for the Teams Runs BFF (Task 6 of #3a)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from routers.teams.deps import TeamsContext


@pytest.fixture
def teams_ctx():
    return TeamsContext(
        user_id="u1",
        org_id="o1",
        owner_id="o1",
        company_id="co_abc",
        paperclip_user_id="pcu_xyz",
        session_cookie="cookie",
    )


@pytest.fixture
def client(teams_ctx):
    from routers.teams import agents as agents_mod

    async def fake_ctx():
        return teams_ctx

    app.dependency_overrides[agents_mod._ctx] = fake_ctx
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(agents_mod._ctx, None)


def test_get_run_detail(client, monkeypatch):
    """`GET /teams/runs/{id}` returns upstream's heartbeat-run detail."""
    admin = MagicMock()
    admin.get_heartbeat_run = AsyncMock(
        return_value={
            "id": "run_1",
            "agentId": "agt_1",
            "status": "failed",
            "startedAt": "2026-05-04T01:00:00Z",
            "stderrExcerpt": "boom",
        }
    )
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/runs/run_1",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "run_1"
    assert body["status"] == "failed"
    admin.get_heartbeat_run.assert_awaited_once_with(
        run_id="run_1", session_cookie="cookie",
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_runs.py -v --no-cov
```

Expected: FAIL — `404 Not Found` (router not registered yet).

- [ ] **Step 3: Implement the router**

Create `apps/backend/routers/teams/runs.py`:

```python
"""Teams BFF — Heartbeat Runs.

Read-only resource that surfaces upstream Paperclip's heartbeat-run
detail. Used by the agent-run page that Inbox failed-run rows link into.
Reuses the shared ``_ctx`` Depends helper so auth + session cookie
plumbing is consistent across the Teams BFF.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from . import agents as _agents
from .deps import TeamsContext

router = APIRouter()
_ctx = _agents._ctx


@router.get("/runs/{run_id}")
async def get_run(run_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Fetch a single heartbeat run by id.

    Maps to upstream ``GET /api/heartbeat-runs/{runId}``.
    """
    return await _agents._admin().get_heartbeat_run(
        run_id=run_id,
        session_cookie=ctx.session_cookie,
    )
```

- [ ] **Step 4: Mount the router**

Modify `apps/backend/routers/teams/__init__.py`:

```python
"""Teams BFF — native UI for Paperclip. See spec 2026-05-02."""

from fastapi import APIRouter

from . import agents as _agents
from . import approvals as _approvals
from . import feed as _feed
from . import inbox as _inbox
from . import issues as _issues
from . import members as _members
from . import runs as _runs
from . import settings as _settings_r
from . import skills as _skills
from . import work as _work

router = APIRouter(prefix="/teams", tags=["teams"])
router.include_router(_agents.router)
router.include_router(_inbox.router)
router.include_router(_approvals.router)
router.include_router(_issues.router)
router.include_router(_runs.router)
router.include_router(_work.router)
router.include_router(_feed.router)
router.include_router(_skills.router)
router.include_router(_members.router)
router.include_router(_settings_r.router)
```

- [ ] **Step 5: Run test to verify it passes**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_runs.py -v --no-cov
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/routers/teams/runs.py apps/backend/routers/teams/__init__.py apps/backend/tests/unit/routers/teams/test_runs.py
git commit -m "feat(teams): runs router (heartbeat-run detail endpoint)"
```

---

## Task 7: New `projects.py` router — `GET /projects`

**Files:**
- Create: `apps/backend/routers/teams/projects.py`
- Modify: `apps/backend/routers/teams/__init__.py`
- Test: `apps/backend/tests/unit/routers/teams/test_projects.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/routers/teams/test_projects.py`:

```python
"""Tests for the Teams Projects BFF (Task 7 of #3a)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from routers.teams.deps import TeamsContext


@pytest.fixture
def teams_ctx():
    return TeamsContext(
        user_id="u1",
        org_id="o1",
        owner_id="o1",
        company_id="co_abc",
        paperclip_user_id="pcu_xyz",
        session_cookie="cookie",
    )


@pytest.fixture
def client(teams_ctx):
    from routers.teams import agents as agents_mod

    async def fake_ctx():
        return teams_ctx

    app.dependency_overrides[agents_mod._ctx] = fake_ctx
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(agents_mod._ctx, None)


def test_list_projects(client, monkeypatch):
    """`GET /teams/projects` lists projects in the caller's company."""
    admin = MagicMock()
    admin.list_company_projects = AsyncMock(
        return_value={"projects": [{"id": "proj_1", "name": "Q3 launch"}]}
    )
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/projects",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["projects"][0]["id"] == "proj_1"
    admin.list_company_projects.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_projects.py -v --no-cov
```

Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Implement**

Create `apps/backend/routers/teams/projects.py`:

```python
"""Teams BFF — Projects.

Read-only listing used by the Inbox project-filter dropdown and (later
phases) the project workspace surfaces.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from . import agents as _agents
from .deps import TeamsContext

router = APIRouter()
_ctx = _agents._ctx


@router.get("/projects")
async def list_projects(ctx: TeamsContext = Depends(_ctx)):
    """List projects in the caller's company.

    Maps to upstream ``GET /api/companies/{companyId}/projects``.
    """
    return await _agents._admin().list_company_projects(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )
```

- [ ] **Step 4: Mount the router**

Modify `apps/backend/routers/teams/__init__.py` to add the import and include line for `projects`:

```python
"""Teams BFF — native UI for Paperclip. See spec 2026-05-02."""

from fastapi import APIRouter

from . import agents as _agents
from . import approvals as _approvals
from . import feed as _feed
from . import inbox as _inbox
from . import issues as _issues
from . import members as _members
from . import projects as _projects
from . import runs as _runs
from . import settings as _settings_r
from . import skills as _skills
from . import work as _work

router = APIRouter(prefix="/teams", tags=["teams"])
router.include_router(_agents.router)
router.include_router(_inbox.router)
router.include_router(_approvals.router)
router.include_router(_issues.router)
router.include_router(_runs.router)
router.include_router(_projects.router)
router.include_router(_work.router)
router.include_router(_feed.router)
router.include_router(_skills.router)
router.include_router(_members.router)
router.include_router(_settings_r.router)
```

- [ ] **Step 5: Run test to verify it passes**

```
cd apps/backend && uv run pytest tests/unit/routers/teams/test_projects.py -v --no-cov
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/routers/teams/projects.py apps/backend/routers/teams/__init__.py apps/backend/tests/unit/routers/teams/test_projects.py
git commit -m "feat(teams): projects router (list endpoint for filter dropdown)"
```

---

## Task 8: Final verification — full backend suite + push + open PR

This is the only place the full backend pytest suite runs. Per project memory, individual tasks only run their own targeted tests during implementation; the final task verifies nothing leaked.

- [ ] **Step 1: Full backend test suite**

```
cd apps/backend && uv run pytest -q
```

Expected: all tests pass. The new tests added across tasks 1-7 should appear in the count. If any unrelated test fails, fix the regression — the BFF additions shouldn't have changed any existing surface, but the test runner is the authoritative answer.

- [ ] **Step 2: OpenAPI surface sanity-check**

```
cd apps/backend && uv run python -c "
from main import app
paths = sorted(p for p in app.openapi().get('paths', {}) if '/teams/' in p)
expected = [
    '/api/v1/teams/inbox',
    '/api/v1/teams/inbox/{item_id}/dismiss',
    '/api/v1/teams/inbox/runs',
    '/api/v1/teams/inbox/live-runs',
    '/api/v1/teams/issues/{issue_id}/archive',
    '/api/v1/teams/issues/{issue_id}/unarchive',
    '/api/v1/teams/issues/{issue_id}/mark-read',
    '/api/v1/teams/issues/{issue_id}/mark-unread',
    '/api/v1/teams/issues/{issue_id}/comments',
    '/api/v1/teams/approvals/{approval_id}',
    '/api/v1/teams/runs/{run_id}',
    '/api/v1/teams/projects',
]
missing = [p for p in expected if p not in paths]
extra_teams = [p for p in paths if p not in expected and not any(p.startswith(e.split('{')[0].rstrip('/')) for e in expected)]
print('missing:', missing)
print('total /teams/ paths:', len(paths))
"
```

Expected output: `missing: []` and a total path count >= 12. Existing /teams/* paths from prior PRs will also be in the list — the check just confirms our new additions registered.

- [ ] **Step 3: Push branch**

```bash
git push -u origin feat/teams-inbox-bff
```

- [ ] **Step 4: Open the PR**

```bash
gh pr create --title "feat(teams): backend BFF endpoints for inbox + detail surfaces (#3a)" --body "$(cat <<'PRBODY'
## Summary

PR #3a of the [Teams Inbox deep port](docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md). Pure backend — adds the BFF routes that the Inbox + IssueDetail + ApprovalDetail + AgentRun pages need. No frontend changes; new endpoints are unused until #3b/c/d wires them.

## What's new

**Inbox** (\`apps/backend/routers/teams/inbox.py\`)
- \`GET /teams/inbox\` accepts query params: \`tab\`, \`status\`, \`project\`, \`assignee\`, \`creator\`, \`search\`, \`limit\` — forwarded verbatim to upstream
- \`GET /teams/inbox/runs\` — failed heartbeat runs (Inbox 'Runs' tab data)
- \`GET /teams/inbox/live-runs\` — currently-running heartbeat runs (Live badge)

**Issues** (\`apps/backend/routers/teams/issues.py\`)
- \`POST /teams/issues/{id}/archive\` / \`/unarchive\`
- \`POST /teams/issues/{id}/mark-read\` / \`/mark-unread\`
- \`GET /teams/issues/{id}/comments\` / \`POST /teams/issues/{id}/comments\` (strict body schema)

**Approvals** (\`apps/backend/routers/teams/approvals.py\`)
- \`GET /teams/approvals/{id}\` — detail endpoint

**New routers**
- \`apps/backend/routers/teams/runs.py\` — \`GET /teams/runs/{id}\`
- \`apps/backend/routers/teams/projects.py\` — \`GET /teams/projects\`

**Admin client** (\`apps/backend/core/services/paperclip_admin_client.py\`)
- 12 new methods: \`list_company_heartbeat_runs\`, \`list_company_live_runs\`, \`get_heartbeat_run\`, \`archive_issue\`, \`unarchive_issue\`, \`mark_issue_read\`, \`mark_issue_unread\`, \`list_issue_comments\`, \`add_issue_comment\`, \`get_approval\`, \`list_company_projects\`, plus \`list_inbox_for_session_user\` extended with optional \`params\`
- \`_get\` helper accepts optional \`params\` query-string dict

## Test plan

- [x] Admin-client unit tests: 12 new method tests
- [x] Inbox router: 4 new tests (filter forwarding, runs, live-runs)
- [x] Issues router: 8 new tests (archive/unarchive/mark-read/mark-unread + comments + body strictness)
- [x] Approvals router: 1 new test (detail)
- [x] Runs router: 1 new test (detail)
- [x] Projects router: 1 new test (listing)
- [x] Full backend pytest passes
- [x] OpenAPI surface includes all 12 expected paths
- [ ] Manual smoke on dev: hit a few endpoints with curl + Clerk JWT

## Out of scope

This PR is backend-only. Frontend changes live in PR #3b/c/d.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PRBODY
)"
```

Expected: prints the PR URL.

---

## Implementation notes for subagents

**Per-task execution model** (per project memory: subagent-driven-development):
1. Read your task section in full + the relevant section of the spec.
2. Write the failing tests FIRST, run them red.
3. Implement, run them green.
4. Commit with the suggested message.
5. Report DONE; the controller will dispatch reviewers.
6. Targeted tests only — never run the full suite from inside a task.

**Use opus for every subagent** (per project memory `feedback_always_best_model.md`).

**Branch:** all tasks land on `feat/teams-inbox-bff`. Branch off `origin/main`. Setup via `using-git-worktrees` skill before Task 1.

**Final task (Task 8) is the gate:** after all per-task subagents finish + reviews are clean, Task 8 runs the full backend suite, the OpenAPI surface check, and opens the PR.

## Out-of-scope reminders (DO NOT IMPLEMENT in this plan)

These are explicitly deferred per the spec:

- **No frontend changes.** The plan is backend-only. Any `apps/frontend/` edit is out of scope.
- **No realtime integration changes.** PR #3c will extend `TeamsEventsProvider`'s `EVENT_KEY_MAP` to include the new endpoints' SWR keys; this PR does not.
- **No new auth code.** Every route uses the existing `_ctx` Depends helper; no exceptions.
- **No aggregation, no caching at the BFF.** Each route is a thin forward.
- **No new pyproject.toml dependencies.**
- **No retry endpoint for runs.** Upstream Paperclip doesn't expose a single "retry" endpoint for heartbeat-runs in a clean way (the closest are `/cancel` + creating new runs via agent invocation). The retry button on Inbox failed-run rows ships as a no-op in #3c with a clear "TODO: requires upstream retry semantics" comment, OR is wired to whatever upstream pattern PR #3c discovers (workaround acceptable: hide the button in v1). Not a backend concern for this PR.
- **No issue children/work-products endpoints.** The Inbox UI uses these for nested issue rendering, but the nesting is rendered client-side from the existing `parentId` field; no new backend route needed.
- **No `/teams/workspaces` route in this PR.** The spec listed it as a placeholder; the IssueRow's workspace pill renders no-op in v1 per the spec's "Out of scope" note. Defer until the workspace sub-project lands.
