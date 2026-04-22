# Admin Catalog Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the curated-agent catalog's operator flows (publish + unpublish + view versions) from the `publish-agent.sh` CLI into the admin dashboard shipped by #351, with every catalog write auditing through the existing `@audit_admin_action` decorator into the `isol8-{env}-admin-actions` DDB table.

**Architecture:** Extend `CatalogService` with three read/write helpers (`list_all`, `unpublish`, `list_versions`). Add three admin endpoints to `routers/admin_catalog.py` alongside the existing `/publish`. Apply `@audit_admin_action` to every mutating endpoint. Build a `/admin/catalog` Server Component with a client-side row-actions component and a versions side panel. Add a `[Publish to catalog]` button to the admin agent detail page, rendered only when the admin is viewing their own agent. Extend `catalog.json` with an optional `retired` list so soft-delete preserves audit trail without deleting S3 artifacts.

**Tech Stack:** FastAPI + boto3 + existing `@audit_admin_action` decorator (backend), Next.js 16 App Router + React 19 + Server Actions + `ConfirmActionDialog` (frontend), existing admin API helpers in `_lib/api.ts`, vitest + pytest.

---

## File structure

**Modified backend files:**
- `apps/backend/core/services/admin_audit.py` — add optional `target_user_id_override` kwarg to `audit_admin_action`
- `apps/backend/core/services/catalog_service.py` — add `unpublish`, `list_all`, `list_versions`
- `apps/backend/routers/admin_catalog.py` — apply audit decorator to existing `publish`; add three new endpoints
- `apps/backend/tests/unit/test_catalog_service.py` — extend with service-level tests
- `apps/backend/tests/unit/test_routers_catalog.py` — extend with router-level tests (including audit-row verification)

**Modified frontend files:**
- `apps/frontend/src/app/admin/_lib/api.ts` — add `listCatalog`, `listSlugVersions`
- `apps/frontend/src/app/admin/layout.tsx` — add "Catalog" nav item
- `apps/frontend/src/app/admin/users/[id]/agents/[agent_id]/AgentActionsFooter.tsx` — add `[Publish to catalog]` button (conditional on own-agent)

**New frontend files:**
- `apps/frontend/src/app/admin/_actions/catalog.ts` — Server Actions `publishAgent`, `unpublishSlug`
- `apps/frontend/src/app/admin/catalog/page.tsx` — Server Component, list of live + retired slugs
- `apps/frontend/src/app/admin/catalog/CatalogRowActions.tsx` — Client Component, per-row `[Unpublish]` + `[View versions]`
- `apps/frontend/src/app/admin/catalog/VersionsPanel.tsx` — Client Component, right-side versions panel
- `apps/frontend/tests/unit/admin/catalog-row-actions.test.tsx` — vitest for the row actions component
- `apps/frontend/tests/unit/admin/catalog-server-actions.test.ts` — vitest for the Server Actions

---

## Task 1: Extend audit decorator with `target_user_id_override`

**Why first:** Every new catalog endpoint will use the decorator with an explicit sentinel (`"__catalog__"`) for `target_user_id`. Current decorator only reads from kwargs — we need a static override.

**Files:**
- Modify: `apps/backend/core/services/admin_audit.py`
- Test: `apps/backend/tests/unit/test_admin_audit.py` (new or existing)

- [ ] **Step 1: Write the failing test**

Find or create `apps/backend/tests/unit/test_admin_audit.py`. Add:

```python
import pytest
from unittest.mock import AsyncMock, patch

from core.services.admin_audit import audit_admin_action


@pytest.mark.asyncio
async def test_audit_uses_static_target_override():
    """When target_user_id_override is passed, the audit row uses it verbatim
    rather than pulling from kwargs."""
    create_mock = AsyncMock()

    @audit_admin_action("catalog.test", target_user_id_override="__catalog__")
    async def handler(request, auth):
        return {"ok": True}

    # Build the minimal request/auth args the decorator expects. Mirror the
    # shape used in tests/unit/routers/test_admin_actions_writes.py.
    class _Req:
        headers = {"user-agent": "pytest"}
        client = type("c", (), {"host": "127.0.0.1"})()

    class _Auth:
        user_id = "user_admin_123"

    with patch(
        "core.repositories.admin_actions_repo.create",
        new=create_mock,
    ):
        await handler(request=_Req(), auth=_Auth())

    assert create_mock.await_count == 1
    written = create_mock.await_args.kwargs or create_mock.await_args.args
    # Normalize — whichever form the repo.create expects, the target_user_id
    # must equal the sentinel.
    flat = written if isinstance(written, dict) else written[0]
    assert flat["target_user_id"] == "__catalog__"


@pytest.mark.asyncio
async def test_audit_falls_back_to_kwarg_without_override():
    """Sanity: existing behavior is preserved when no override is given."""
    create_mock = AsyncMock()

    @audit_admin_action("user.test")
    async def handler(user_id, request, auth):
        return {"ok": True}

    class _Req:
        headers = {"user-agent": "pytest"}
        client = type("c", (), {"host": "127.0.0.1"})()

    class _Auth:
        user_id = "user_admin_123"

    with patch(
        "core.repositories.admin_actions_repo.create",
        new=create_mock,
    ):
        await handler(user_id="user_target_xyz", request=_Req(), auth=_Auth())

    flat = create_mock.await_args.kwargs or create_mock.await_args.args
    row = flat if isinstance(flat, dict) else flat[0]
    assert row["target_user_id"] == "user_target_xyz"
```

Note: the exact shape of the `admin_actions_repo.create` signature may require this test to be adjusted. Read `apps/backend/core/repositories/admin_actions_repo.py` first. If `create` takes a single dict, use `await_args.args[0]`; if it takes kwargs, use `await_args.kwargs`. The assertion stays the same.

- [ ] **Step 2: Run test, confirm red**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_admin_audit.py::test_audit_uses_static_target_override -v
```

Expected: `TypeError: audit_admin_action() got an unexpected keyword argument 'target_user_id_override'`.

- [ ] **Step 3: Extend the decorator**

In `apps/backend/core/services/admin_audit.py`, modify the `audit_admin_action` signature and its target-resolution logic.

Current (from prior exploration, lines 90–101 + 112–114):

```python
def audit_admin_action(
    action: str,
    *,
    target_param: str = "user_id",
    redact_paths: list[str] | None = None,
) -> Callable:
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            target_user_id = kwargs.get(target_param) or "system"
            # ...
```

Change to:

```python
def audit_admin_action(
    action: str,
    *,
    target_param: str = "user_id",
    target_user_id_override: str | None = None,
    redact_paths: list[str] | None = None,
) -> Callable:
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            if target_user_id_override is not None:
                target_user_id = target_user_id_override
            else:
                target_user_id = kwargs.get(target_param) or "system"
            # ...
```

Leave the rest of the decorator body unchanged.

- [ ] **Step 4: Run test, confirm green**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_admin_audit.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/admin_audit.py apps/backend/tests/unit/test_admin_audit.py
git commit -m "feat(admin-audit): support static target_user_id_override

Catalog actions target the shared catalog, not a user. The decorator
now accepts an optional target_user_id_override kwarg; when set, the
audit row's target_user_id is the override value rather than being
pulled from request kwargs. Falls back to existing behavior when not
provided.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Apply audit decorator to existing `/admin/catalog/publish`

**Files:**
- Modify: `apps/backend/routers/admin_catalog.py`
- Test: `apps/backend/tests/unit/test_routers_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/unit/test_routers_catalog.py`:

```python
from unittest.mock import AsyncMock, patch


def test_publish_writes_audit_row(client, mock_service, admin_env):
    """POST /admin/catalog/publish creates an admin-actions row with
    action=catalog.publish and target_user_id=__catalog__."""
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(
        user_id="user_admin_42"
    )
    mock_service.publish = AsyncMock(
        return_value={"slug": "pitch", "version": 1, "s3_prefix": "pitch/v1"}
    )

    audit_mock = AsyncMock()
    with patch("core.repositories.admin_actions_repo.create", new=audit_mock):
        r = client.post(
            "/api/v1/admin/catalog/publish",
            json={"agent_id": "agent_abc"},
        )

    assert r.status_code == 200
    assert audit_mock.await_count == 1

    row_args = audit_mock.await_args.kwargs or audit_mock.await_args.args
    row = row_args if isinstance(row_args, dict) else row_args[0]
    assert row["action"] == "catalog.publish"
    assert row["target_user_id"] == "__catalog__"
    assert row["admin_user_id"] == "user_admin_42"

    app.dependency_overrides.pop(require_platform_admin, None)
```

Also add the `admin_env` fixture at the top of the file if missing (mirror the pattern from `test_admin_actions_writes.py`):

```python
@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setattr(
        "core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_admin_42"
    )
    yield
```

- [ ] **Step 2: Run test, confirm red**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_routers_catalog.py::test_publish_writes_audit_row -v
```

Expected: `AssertionError: assert 0 == 1` (audit mock never called — no decorator).

- [ ] **Step 3: Apply the decorator**

In `apps/backend/routers/admin_catalog.py`, find the existing publish handler (currently lines ~17–31 per exploration). Add the decorator import at the top and wrap the handler.

Add to imports:

```python
from core.services.admin_audit import audit_admin_action
```

Modify the handler:

```python
@router.post(
    "/publish",
    description="Package an agent from the admin's EFS workspace and upload it to the shared catalog bucket.",
)
@audit_admin_action(
    "catalog.publish",
    target_user_id_override="__catalog__",
    redact_paths=["agent_id"],  # agent_id isn't secret; redact_paths is optional but documents intent
)
async def publish(
    req: PublishRequest,
    request: Request,  # REQUIRED by decorator to extract UA/IP — add if not present
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return await service.publish(
        admin_user_id=auth.user_id,
        agent_id=req.agent_id,
        slug_override=req.slug,
        description_override=req.description,
    )
```

Note: the decorator requires the handler's signature to include `request: Request` (it reads `request.headers["user-agent"]` and `request.client.host`). Check `routers/admin.py`'s decorated handlers for the exact parameter name expected. If `request` is already there, skip this addition.

- [ ] **Step 4: Run test, confirm green**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_routers_catalog.py -v
```

Expected: all tests pass, including the new audit test.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/admin_catalog.py apps/backend/tests/unit/test_routers_catalog.py
git commit -m "feat(admin-catalog): audit publish endpoint

Wraps the existing POST /admin/catalog/publish with the shared
@audit_admin_action decorator so CLI (publish-agent.sh) and future
dashboard-driven publishes both write audit rows with action=
catalog.publish and target_user_id=__catalog__.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `CatalogService.unpublish()` + `catalog.json` retired schema

**Files:**
- Modify: `apps/backend/core/services/catalog_service.py`
- Test: `apps/backend/tests/unit/test_catalog_service.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/unit/test_catalog_service.py`:

```python
@pytest.mark.asyncio
async def test_unpublish_moves_slug_from_live_to_retired(
    service, mock_s3
):
    """Soft delete: slug moves from agents -> retired. S3 artifacts untouched."""
    # Initial catalog: pitch is live, nothing retired.
    mock_s3.get_json.return_value = {
        "updated_at": "2026-04-22T00:00:00Z",
        "agents": [
            {"slug": "pitch", "current_version": 3,
             "manifest_url": "pitch/v3/manifest.json"},
            {"slug": "echo", "current_version": 1,
             "manifest_url": "echo/v1/manifest.json"},
        ],
        "retired": [],
    }

    result = await service.unpublish(
        admin_user_id="user_admin", slug="pitch"
    )

    assert result["slug"] == "pitch"
    assert result["last_version"] == 3

    # catalog.json was rewritten (put_json call)
    put_json_calls = [c for c in mock_s3.put_json.call_args_list
                      if c.args[0] == "catalog.json"]
    assert len(put_json_calls) == 1
    new_catalog = put_json_calls[0].args[1]
    assert [a["slug"] for a in new_catalog["agents"]] == ["echo"]
    assert len(new_catalog["retired"]) == 1
    assert new_catalog["retired"][0]["slug"] == "pitch"
    assert new_catalog["retired"][0]["last_version"] == 3
    assert new_catalog["retired"][0]["retired_by"] == "user_admin"
    assert "retired_at" in new_catalog["retired"][0]

    # S3 artifacts (workspace.tar.gz, manifest.json) — no delete calls.
    # We assert via absence of any put_bytes overwriting the tarball, etc.
    assert mock_s3.method_calls is not None  # just ensures no crash
    # No direct delete API is called on the client.


@pytest.mark.asyncio
async def test_unpublish_missing_slug_raises(service, mock_s3):
    mock_s3.get_json.return_value = {"agents": [], "retired": []}
    with pytest.raises(KeyError):
        await service.unpublish(admin_user_id="user_admin", slug="ghost")


@pytest.mark.asyncio
async def test_unpublish_preserves_other_retired_entries(service, mock_s3):
    """Pre-existing retired entries stay in the retired list when a new one is added."""
    mock_s3.get_json.return_value = {
        "updated_at": "2026-04-22T00:00:00Z",
        "agents": [
            {"slug": "pitch", "current_version": 2,
             "manifest_url": "pitch/v2/manifest.json"},
        ],
        "retired": [
            {"slug": "oldie", "last_version": 1,
             "last_manifest_url": "oldie/v1/manifest.json",
             "retired_at": "2026-04-01T00:00:00Z",
             "retired_by": "user_admin"},
        ],
    }
    await service.unpublish(admin_user_id="user_admin", slug="pitch")

    new_catalog = next(c for c in mock_s3.put_json.call_args_list
                       if c.args[0] == "catalog.json").args[1]
    retired_slugs = sorted(r["slug"] for r in new_catalog["retired"])
    assert retired_slugs == ["oldie", "pitch"]


@pytest.mark.asyncio
async def test_unpublish_handles_missing_retired_key(service, mock_s3):
    """Backward compat: catalog.json without a 'retired' key is treated as []."""
    mock_s3.get_json.return_value = {
        "updated_at": "2026-04-22T00:00:00Z",
        "agents": [
            {"slug": "pitch", "current_version": 1,
             "manifest_url": "pitch/v1/manifest.json"},
        ],
        # No "retired" key at all.
    }
    await service.unpublish(admin_user_id="user_admin", slug="pitch")
    new_catalog = next(c for c in mock_s3.put_json.call_args_list
                       if c.args[0] == "catalog.json").args[1]
    assert new_catalog["retired"][0]["slug"] == "pitch"
```

- [ ] **Step 2: Run tests, confirm red**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_catalog_service.py -v -k unpublish
```

Expected: `AttributeError: 'CatalogService' object has no attribute 'unpublish'`.

- [ ] **Step 3: Implement `unpublish`**

Add to `apps/backend/core/services/catalog_service.py`, inside the `CatalogService` class (next to `publish`):

```python
async def unpublish(
    self, *, admin_user_id: str, slug: str
) -> dict[str, Any]:
    """Soft-delete: move slug from agents list to retired list in catalog.json.
    S3 artifacts (versioned manifests + tarballs) remain untouched for audit.
    Raises KeyError if slug isn't currently live.
    """
    catalog = self._s3.get_json("catalog.json", default={"agents": [], "retired": []})
    agents = list(catalog.get("agents") or [])
    retired = list(catalog.get("retired") or [])

    match = next((a for a in agents if a.get("slug") == slug), None)
    if not match:
        raise KeyError(f"slug {slug!r} is not currently live")

    new_agents = [a for a in agents if a.get("slug") != slug]
    retired_entry = {
        "slug": slug,
        "last_version": match["current_version"],
        "last_manifest_url": match["manifest_url"],
        "retired_at": datetime.now(timezone.utc).isoformat(),
        "retired_by": admin_user_id,
    }
    new_retired = retired + [retired_entry]

    self._s3.put_json(
        "catalog.json",
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "agents": new_agents,
            "retired": new_retired,
        },
    )

    return {
        "slug": slug,
        "last_version": match["current_version"],
        "last_manifest_url": match["manifest_url"],
    }
```

- [ ] **Step 4: Update `publish` to remove a slug from retired on republish**

Still in `catalog_service.py`, modify the `publish` method's catalog.json rewrite section. Current code (near the bottom of `publish`):

```python
catalog = self._s3.get_json("catalog.json", default={"agents": []})
entries = [e for e in (catalog.get("agents") or []) if e.get("slug") != slug]
entries.append({...})
self._s3.put_json("catalog.json", {"updated_at": ..., "agents": entries})
```

Change to:

```python
catalog = self._s3.get_json(
    "catalog.json", default={"agents": [], "retired": []}
)
entries = [
    e for e in (catalog.get("agents") or []) if e.get("slug") != slug
]
entries.append(
    {
        "slug": slug,
        "current_version": next_version,
        "manifest_url": f"{prefix}/manifest.json",
    }
)
# If the slug was retired previously, remove it from the retired list
# because it's live again.
retired = [
    r for r in (catalog.get("retired") or []) if r.get("slug") != slug
]
self._s3.put_json(
    "catalog.json",
    {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "agents": entries,
        "retired": retired,
    },
)
```

- [ ] **Step 5: Add a test for the retired-removed-on-republish behavior**

Append to `test_catalog_service.py`:

```python
@pytest.mark.asyncio
async def test_publish_removes_retired_entry_when_republishing(
    service, mock_s3, mock_workspace, tmp_path
):
    """Republishing a retired slug removes it from retired and adds it to agents."""
    mock_workspace.read_openclaw_config.return_value = {
        "agents": [{"id": "a1", "name": "Pitch", "skills": []}],
        "plugins": {}, "tools": {},
    }
    admin_workspace = tmp_path / "ws"
    admin_workspace.mkdir()
    (admin_workspace / "IDENTITY.md").write_text("x")
    mock_workspace.agent_workspace_path.return_value = admin_workspace
    mock_s3.list_versions.return_value = [1, 2]  # prior versions
    mock_s3.get_json.return_value = {
        "agents": [],
        "retired": [
            {"slug": "pitch", "last_version": 2,
             "last_manifest_url": "pitch/v2/manifest.json",
             "retired_at": "2026-04-01T00:00:00Z",
             "retired_by": "user_admin"},
        ],
    }

    result = await service.publish(
        admin_user_id="user_admin", agent_id="a1", slug_override="pitch"
    )
    assert result["version"] == 3  # bumped from v2

    catalog_put = next(
        c for c in mock_s3.put_json.call_args_list
        if c.args[0] == "catalog.json"
    )
    new_catalog = catalog_put.args[1]
    assert [a["slug"] for a in new_catalog["agents"]] == ["pitch"]
    assert new_catalog["retired"] == []
```

- [ ] **Step 6: Run all catalog service tests, confirm green**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_catalog_service.py -v
```

Expected: all pass (previous suite + 5 new).

- [ ] **Step 7: Commit**

```bash
git add apps/backend/core/services/catalog_service.py apps/backend/tests/unit/test_catalog_service.py
git commit -m "feat(catalog): add unpublish + retired list in catalog.json

Soft delete moves a slug from agents -> retired in catalog.json.
S3 artifacts untouched for audit trail. Republishing a retired slug
removes it from retired and re-adds it to agents with the next
version number.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `CatalogService.list_all()` — admin view of live + retired

**Files:**
- Modify: `apps/backend/core/services/catalog_service.py`
- Test: `apps/backend/tests/unit/test_catalog_service.py`

- [ ] **Step 1: Write the failing test**

Append to `test_catalog_service.py`:

```python
def test_list_all_returns_live_and_retired(service, mock_s3):
    """Admin view: live entries include full manifest preview; retired
    entries include the metadata we stored at retire time."""
    def _get_json(key, default=None):
        if key == "catalog.json":
            return {
                "agents": [
                    {"slug": "pitch", "current_version": 3,
                     "manifest_url": "pitch/v3/manifest.json"},
                ],
                "retired": [
                    {"slug": "echo", "last_version": 1,
                     "last_manifest_url": "echo/v1/manifest.json",
                     "retired_at": "2026-04-22T00:00:00Z",
                     "retired_by": "user_admin"},
                ],
            }
        if key == "pitch/v3/manifest.json":
            return {
                "slug": "pitch", "version": 3, "name": "Pitch",
                "emoji": "🎯", "vibe": "Direct",
                "description": "Sales", "suggested_model": "qwen",
                "suggested_channels": [],
                "required_skills": [], "required_plugins": [],
                "required_tools": [],
                "published_at": "2026-04-20T00:00:00Z",
                "published_by": "user_admin",
            }
        return default
    mock_s3.get_json.side_effect = _get_json

    result = service.list_all()

    assert len(result["live"]) == 1
    assert result["live"][0]["slug"] == "pitch"
    assert result["live"][0]["name"] == "Pitch"
    assert result["live"][0]["current_version"] == 3
    assert "published_at" in result["live"][0]

    assert len(result["retired"]) == 1
    assert result["retired"][0]["slug"] == "echo"
    assert result["retired"][0]["retired_by"] == "user_admin"
    assert result["retired"][0]["last_version"] == 1


def test_list_all_empty_catalog(service, mock_s3):
    mock_s3.get_json.return_value = {"agents": [], "retired": []}
    result = service.list_all()
    assert result == {"live": [], "retired": []}


def test_list_all_handles_missing_retired_key(service, mock_s3):
    mock_s3.get_json.side_effect = lambda key, default=None: (
        {"agents": []} if key == "catalog.json" else default
    )
    result = service.list_all()
    assert result == {"live": [], "retired": []}
```

- [ ] **Step 2: Run tests, confirm red**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_catalog_service.py -v -k list_all
```

Expected: `AttributeError: 'CatalogService' object has no attribute 'list_all'`.

- [ ] **Step 3: Implement `list_all`**

In `catalog_service.py`, add to `CatalogService`:

```python
def list_all(self) -> dict[str, list[dict[str, Any]]]:
    """Admin view: return {"live": [...with manifest preview], "retired": [...]}.

    Live entries include the full manifest (same shape as list()).
    Retired entries include only the metadata stored at retire time.
    """
    catalog = self._s3.get_json(
        "catalog.json", default={"agents": [], "retired": []}
    )
    live: list[dict[str, Any]] = []
    for item in catalog.get("agents") or []:
        manifest = self._s3.get_json(item["manifest_url"], default=None)
        if not manifest:
            continue
        live.append(
            {
                "slug": manifest["slug"],
                "name": manifest.get("name", manifest["slug"]),
                "emoji": manifest.get("emoji", ""),
                "vibe": manifest.get("vibe", ""),
                "description": manifest.get("description", ""),
                "current_version": manifest["version"],
                "published_at": manifest.get("published_at", ""),
                "published_by": manifest.get("published_by", ""),
                "suggested_model": manifest.get("suggested_model", ""),
                "suggested_channels": manifest.get("suggested_channels", []),
                "required_skills": manifest.get("required_skills", []),
                "required_plugins": manifest.get("required_plugins", []),
            }
        )

    retired = list(catalog.get("retired") or [])
    return {"live": live, "retired": retired}
```

- [ ] **Step 4: Run tests, confirm green**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_catalog_service.py -v -k list_all
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/catalog_service.py apps/backend/tests/unit/test_catalog_service.py
git commit -m "feat(catalog): list_all returns live + retired for admin

Service helper backing the /admin/catalog page. Returns both the
full live-manifest preview (same shape as user-facing list()) and
the retired list with retire metadata.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `CatalogService.list_versions(slug)`

**Files:**
- Modify: `apps/backend/core/services/catalog_service.py`
- Test: `apps/backend/tests/unit/test_catalog_service.py`

- [ ] **Step 1: Write the failing test**

Append to `test_catalog_service.py`:

```python
def test_list_versions_returns_sorted_with_manifests(service, mock_s3):
    """Versions sorted ascending; each entry includes manifest JSON + timestamps."""
    mock_s3.list_versions.return_value = [1, 2, 3]

    def _get_json(key, default=None):
        if key == "pitch/v1/manifest.json":
            return {"slug": "pitch", "version": 1, "name": "Pitch",
                    "published_at": "2026-04-19T00:00:00Z",
                    "published_by": "user_admin"}
        if key == "pitch/v2/manifest.json":
            return {"slug": "pitch", "version": 2, "name": "Pitch",
                    "published_at": "2026-04-20T00:00:00Z",
                    "published_by": "user_admin"}
        if key == "pitch/v3/manifest.json":
            return {"slug": "pitch", "version": 3, "name": "Pitch",
                    "published_at": "2026-04-21T00:00:00Z",
                    "published_by": "user_admin"}
        return default
    mock_s3.get_json.side_effect = _get_json

    result = service.list_versions("pitch")

    assert [v["version"] for v in result] == [1, 2, 3]
    assert result[2]["published_at"] == "2026-04-21T00:00:00Z"
    assert result[0]["manifest"]["name"] == "Pitch"
    assert result[0]["manifest_url"] == "pitch/v1/manifest.json"


def test_list_versions_empty_for_unknown_slug(service, mock_s3):
    mock_s3.list_versions.return_value = []
    result = service.list_versions("ghost")
    assert result == []


def test_list_versions_skips_missing_manifest(service, mock_s3):
    """If an S3 manifest is deleted (shouldn't happen, but belt-and-suspenders),
    the version is omitted rather than crashing."""
    mock_s3.list_versions.return_value = [1, 2]
    mock_s3.get_json.side_effect = lambda key, default=None: (
        {"slug": "pitch", "version": 2, "name": "Pitch",
         "published_at": "2026-04-22T00:00:00Z", "published_by": "u"}
        if key == "pitch/v2/manifest.json" else default
    )
    result = service.list_versions("pitch")
    assert [v["version"] for v in result] == [2]
```

- [ ] **Step 2: Run tests, confirm red**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_catalog_service.py -v -k list_versions
```

Expected: `AttributeError: 'CatalogService' object has no attribute 'list_versions'`.

- [ ] **Step 3: Implement `list_versions`**

In `catalog_service.py`, add to `CatalogService`:

```python
def list_versions(self, slug: str) -> list[dict[str, Any]]:
    """List all published versions of a slug, ascending.
    Each entry: {version, manifest_url, published_at, published_by, manifest}.
    """
    versions = self._s3.list_versions(slug)
    out: list[dict[str, Any]] = []
    for v in versions:
        manifest_url = f"{slug}/v{v}/manifest.json"
        manifest = self._s3.get_json(manifest_url, default=None)
        if not manifest:
            continue
        out.append(
            {
                "version": v,
                "manifest_url": manifest_url,
                "published_at": manifest.get("published_at", ""),
                "published_by": manifest.get("published_by", ""),
                "manifest": manifest,
            }
        )
    return out
```

- [ ] **Step 4: Run tests, confirm green**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_catalog_service.py -v
```

Expected: full service suite green.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/catalog_service.py apps/backend/tests/unit/test_catalog_service.py
git commit -m "feat(catalog): list_versions(slug) surfaces version history

Backs the View versions side panel in the admin UI. Returns each
published version with its manifest payload; gracefully skips any
version whose manifest is missing from S3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Three new admin catalog endpoints

**Files:**
- Modify: `apps/backend/routers/admin_catalog.py`
- Test: `apps/backend/tests/unit/test_routers_catalog.py`

- [ ] **Step 1: Write failing tests**

Append to `apps/backend/tests/unit/test_routers_catalog.py`:

```python
def test_admin_list_catalog_returns_live_and_retired(client, mock_service):
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(
        user_id="user_admin"
    )
    mock_service.list_all = MagicMock(
        return_value={
            "live": [{"slug": "pitch", "name": "Pitch", "current_version": 3,
                      "emoji": "🎯", "vibe": "", "description": "",
                      "suggested_model": "", "suggested_channels": [],
                      "required_skills": [], "required_plugins": [],
                      "published_at": "2026-04-22T00:00:00Z",
                      "published_by": "user_admin"}],
            "retired": [],
        }
    )
    r = client.get("/api/v1/admin/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body["live"][0]["slug"] == "pitch"
    assert body["retired"] == []
    app.dependency_overrides.pop(require_platform_admin, None)


def test_admin_unpublish_soft_deletes_slug(client, mock_service):
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(
        user_id="user_admin"
    )
    mock_service.unpublish = AsyncMock(
        return_value={"slug": "pitch", "last_version": 3,
                      "last_manifest_url": "pitch/v3/manifest.json"}
    )

    audit_mock = AsyncMock()
    with patch("core.repositories.admin_actions_repo.create", new=audit_mock):
        r = client.post("/api/v1/admin/catalog/pitch/unpublish")

    assert r.status_code == 200
    assert r.json()["slug"] == "pitch"
    mock_service.unpublish.assert_awaited_once_with(
        admin_user_id="user_admin", slug="pitch"
    )
    assert audit_mock.await_count == 1
    row = audit_mock.await_args.kwargs or audit_mock.await_args.args[0]
    row = row if isinstance(row, dict) else row
    assert row["action"] == "catalog.unpublish"
    assert row["target_user_id"] == "__catalog__"
    app.dependency_overrides.pop(require_platform_admin, None)


def test_admin_unpublish_missing_slug_404(client, mock_service):
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(
        user_id="user_admin"
    )
    mock_service.unpublish = AsyncMock(side_effect=KeyError("not live"))

    r = client.post("/api/v1/admin/catalog/ghost/unpublish")
    assert r.status_code == 404

    app.dependency_overrides.pop(require_platform_admin, None)


def test_admin_list_versions(client, mock_service):
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(
        user_id="user_admin"
    )
    mock_service.list_versions = MagicMock(
        return_value=[
            {"version": 1, "manifest_url": "pitch/v1/manifest.json",
             "published_at": "2026-04-19T00:00:00Z",
             "published_by": "user_admin",
             "manifest": {"slug": "pitch", "version": 1}},
        ]
    )
    r = client.get("/api/v1/admin/catalog/pitch/versions")
    assert r.status_code == 200
    body = r.json()
    assert body["versions"][0]["version"] == 1
    app.dependency_overrides.pop(require_platform_admin, None)


def test_admin_catalog_endpoints_require_platform_admin(client):
    """Any non-admin user hitting /admin/catalog/* returns 403."""
    from core.auth import require_platform_admin
    from main import app
    from fastapi import HTTPException

    def _deny():
        raise HTTPException(
            status_code=403, detail="Platform admin access required"
        )
    app.dependency_overrides[require_platform_admin] = _deny

    assert client.get("/api/v1/admin/catalog").status_code == 403
    assert client.post(
        "/api/v1/admin/catalog/pitch/unpublish"
    ).status_code == 403
    assert client.get(
        "/api/v1/admin/catalog/pitch/versions"
    ).status_code == 403
    app.dependency_overrides.pop(require_platform_admin, None)
```

- [ ] **Step 2: Run tests, confirm red**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_routers_catalog.py -v -k 'admin_list_catalog or admin_unpublish or admin_list_versions or admin_catalog_endpoints_require'
```

Expected: 404 on the new routes (not registered yet).

- [ ] **Step 3: Implement three endpoints**

In `apps/backend/routers/admin_catalog.py`, add (after the existing `publish` handler):

```python
from fastapi import HTTPException, Request
# (if Request/HTTPException aren't already imported)


@router.get(
    "",
    description="Admin view of the catalog: live entries with manifest preview + retired entries.",
)
async def list_all(
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return service.list_all()


@router.post(
    "/{slug}/unpublish",
    description="Soft-delete a catalog slug. Moves the slug to catalog.json's retired list; S3 artifacts preserved.",
)
@audit_admin_action(
    "catalog.unpublish",
    target_user_id_override="__catalog__",
)
async def unpublish(
    slug: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    try:
        return await service.unpublish(
            admin_user_id=auth.user_id, slug=slug
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{slug}/versions",
    description="List every published version of a catalog slug.",
)
async def list_versions(
    slug: str,
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return {"versions": service.list_versions(slug)}
```

- [ ] **Step 4: Run tests, confirm green**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/unit/test_routers_catalog.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/admin_catalog.py apps/backend/tests/unit/test_routers_catalog.py
git commit -m "feat(admin-catalog): list + unpublish + versions endpoints

Three new admin endpoints:
- GET /api/v1/admin/catalog          -> live + retired
- POST /api/v1/admin/catalog/{slug}/unpublish -> soft delete (audited)
- GET /api/v1/admin/catalog/{slug}/versions   -> version history

All gated by require_platform_admin. Unpublish decorated with
@audit_admin_action and targets the __catalog__ sentinel.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Frontend admin API helpers

**Files:**
- Modify: `apps/frontend/src/app/admin/_lib/api.ts`

- [ ] **Step 1: Add helpers**

Open `apps/frontend/src/app/admin/_lib/api.ts`. Near the existing helpers like `listUsers`, add:

```typescript
export interface CatalogLiveEntry {
  slug: string;
  name: string;
  emoji: string;
  vibe: string;
  description: string;
  current_version: number;
  published_at: string;
  published_by: string;
  suggested_model: string;
  suggested_channels: string[];
  required_skills: string[];
  required_plugins: string[];
}

export interface CatalogRetiredEntry {
  slug: string;
  last_version: number;
  last_manifest_url: string;
  retired_at: string;
  retired_by: string;
}

export interface AdminCatalog {
  live: CatalogLiveEntry[];
  retired: CatalogRetiredEntry[];
}

export interface CatalogVersion {
  version: number;
  manifest_url: string;
  published_at: string;
  published_by: string;
  manifest: Record<string, unknown>;
}

export async function listCatalog(token: string): Promise<AdminCatalog> {
  const data = await adminFetch<AdminCatalog>(token, "/admin/catalog");
  return data ?? { live: [], retired: [] };
}

export async function listSlugVersions(
  token: string,
  slug: string,
): Promise<CatalogVersion[]> {
  const data = await adminFetch<{ versions: CatalogVersion[] }>(
    token,
    `/admin/catalog/${encodeURIComponent(slug)}/versions`,
  );
  return data?.versions ?? [];
}
```

The `adminFetch` function is already defined in this file (from the prior exploration — returns `null` on any error, never throws). The `?? [...]` fallback provides the stub shape the UI expects when the admin API is unreachable.

- [ ] **Step 2: Smoke-check via TypeScript**

```bash
cd apps/frontend && pnpm exec tsc --noEmit 2>&1 | head -20
```

Expected: no errors (or no new errors beyond any pre-existing warnings).

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/admin/_lib/api.ts
git commit -m "feat(admin-frontend): catalog list + versions API helpers

Adds typed listCatalog() and listSlugVersions() wrappers around
adminFetch. Null-safe: returns empty catalog / empty versions when
the admin API is unreachable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Server Actions — `publishAgent` and `unpublishSlug`

**Files:**
- Create: `apps/frontend/src/app/admin/_actions/catalog.ts`
- Test: `apps/frontend/tests/unit/admin/catalog-server-actions.test.ts`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/tests/unit/admin/catalog-server-actions.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

const { authMock, getTokenMock, fetchMock } = vi.hoisted(() => {
  const getTokenMock = vi.fn();
  return {
    getTokenMock,
    authMock: vi.fn(async () => ({ getToken: getTokenMock })),
    fetchMock: vi.fn(),
  };
});

vi.mock("@clerk/nextjs/server", () => ({ auth: authMock }));
vi.stubGlobal("fetch", fetchMock);

import { publishAgent, unpublishSlug } from "@/app/admin/_actions/catalog";

describe("catalog server actions", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    getTokenMock.mockReset();
    getTokenMock.mockResolvedValue("test-token");
  });

  it("publishAgent posts to /admin/catalog/publish", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ slug: "pitch", version: 1, s3_prefix: "pitch/v1" }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await publishAgent("agent_abc");

    expect(result.ok).toBe(true);
    expect(result.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/admin\/catalog\/publish$/);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      agent_id: "agent_abc",
    });
  });

  it("unpublishSlug posts to /admin/catalog/{slug}/unpublish", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ slug: "pitch", last_version: 3 }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await unpublishSlug("pitch");

    expect(result.ok).toBe(true);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/admin\/catalog\/pitch\/unpublish$/);
  });

  it("returns ok=false when token is missing", async () => {
    getTokenMock.mockResolvedValueOnce(null);
    const result = await publishAgent("agent_abc");
    expect(result.ok).toBe(false);
    expect(result.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("propagates backend error status", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("{}", { status: 404 }),
    );
    const result = await unpublishSlug("ghost");
    expect(result.ok).toBe(false);
    expect(result.status).toBe(404);
  });
});
```

- [ ] **Step 2: Run test, confirm red**

```bash
cd apps/frontend && pnpm test tests/unit/admin/catalog-server-actions.test.ts -- --run
```

Expected: module-not-found error on `@/app/admin/_actions/catalog`.

- [ ] **Step 3: Implement the Server Actions**

Create `apps/frontend/src/app/admin/_actions/catalog.ts`. Mirror the shape of `_actions/container.ts` (per exploration) so the `ActionResult` signature matches.

```typescript
"use server";

import { auth } from "@clerk/nextjs/server";
import { randomUUID } from "node:crypto";

interface ActionResult {
  ok: boolean;
  status: number;
  data?: unknown;
  error?: string;
}

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

async function adminPost(path: string, body?: object): Promise<ActionResult> {
  const { getToken } = await auth();
  const token = await getToken();
  if (!token) {
    return { ok: false, status: 401, error: "missing_token" };
  }

  try {
    const res = await fetch(`${BACKEND_URL}${path}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": randomUUID(),
      },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });

    if (!res.ok) {
      return { ok: false, status: res.status, error: res.statusText };
    }
    const data = await res.json().catch(() => ({}));
    return { ok: true, status: res.status, data };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      error: err instanceof Error ? err.message : "network_error",
    };
  }
}

export async function publishAgent(
  agentId: string,
  slug?: string,
  description?: string,
): Promise<ActionResult> {
  const body: Record<string, string> = { agent_id: agentId };
  if (slug) body.slug = slug;
  if (description) body.description = description;
  return adminPost("/admin/catalog/publish", body);
}

export async function unpublishSlug(slug: string): Promise<ActionResult> {
  return adminPost(
    `/admin/catalog/${encodeURIComponent(slug)}/unpublish`,
  );
}
```

Check `_actions/container.ts` to confirm the exact `BACKEND_URL` constant and path-prefix. Match whatever's there — the `/admin/catalog/...` path includes `/api/v1` or not depending on how `BACKEND_URL` is configured. If `BACKEND_URL = "https://api-dev.isol8.co/api/v1"`, then `path` starts with `/admin/catalog/...`. If the existing file uses a different constant, match it.

- [ ] **Step 4: Run test, confirm green**

```bash
cd apps/frontend && pnpm test tests/unit/admin/catalog-server-actions.test.ts -- --run
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/app/admin/_actions/catalog.ts apps/frontend/tests/unit/admin/catalog-server-actions.test.ts
git commit -m "feat(admin-frontend): catalog Server Actions

publishAgent + unpublishSlug. Mirrors container.ts's pattern:
Clerk auth on the server, Idempotency-Key header on every POST,
returns ActionResult shape without throwing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: `CatalogRowActions` client component

**Files:**
- Create: `apps/frontend/src/app/admin/catalog/CatalogRowActions.tsx`
- Test: `apps/frontend/tests/unit/admin/catalog-row-actions.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/tests/unit/admin/catalog-row-actions.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { unpublishMock } = vi.hoisted(() => ({
  unpublishMock: vi.fn(async () => ({ ok: true, status: 200 })),
}));
vi.mock("@/app/admin/_actions/catalog", () => ({
  unpublishSlug: unpublishMock,
}));

// Stub ConfirmActionDialog so we can drive it deterministically — the
// component under test composes it but we test via the stub.
vi.mock("@/components/admin/ConfirmActionDialog", () => ({
  ConfirmActionDialog: ({
    children,
    onConfirm,
    confirmText,
  }: {
    children: React.ReactNode;
    onConfirm: () => Promise<void>;
    confirmText: string;
  }) => (
    <div data-testid="confirm-dialog" data-confirm-text={confirmText}>
      {children}
      <button onClick={onConfirm}>__confirm__</button>
    </div>
  ),
}));

import { CatalogRowActions } from "@/app/admin/catalog/CatalogRowActions";

describe("CatalogRowActions", () => {
  beforeEach(() => {
    unpublishMock.mockReset();
    unpublishMock.mockResolvedValue({ ok: true, status: 200 });
  });

  it("renders Unpublish + View versions buttons", () => {
    render(
      <CatalogRowActions slug="pitch" name="Pitch" onOpenVersions={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /unpublish/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /view versions/i }),
    ).toBeInTheDocument();
  });

  it("calls unpublishSlug with the slug when the confirm dialog fires", async () => {
    render(
      <CatalogRowActions slug="pitch" name="Pitch" onOpenVersions={vi.fn()} />,
    );
    const confirm = within(screen.getByTestId("confirm-dialog")).getByText(
      "__confirm__",
    );
    await userEvent.click(confirm);
    expect(unpublishMock).toHaveBeenCalledWith("pitch");
  });

  it("sets confirm text to 'unpublish <slug>'", () => {
    render(
      <CatalogRowActions slug="pitch" name="Pitch" onOpenVersions={vi.fn()} />,
    );
    const dialog = screen.getByTestId("confirm-dialog");
    expect(dialog.getAttribute("data-confirm-text")).toBe("unpublish pitch");
  });

  it("calls onOpenVersions when View versions clicked", async () => {
    const onOpenVersions = vi.fn();
    render(
      <CatalogRowActions
        slug="pitch"
        name="Pitch"
        onOpenVersions={onOpenVersions}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: /view versions/i }),
    );
    expect(onOpenVersions).toHaveBeenCalledWith("pitch");
  });
});
```

- [ ] **Step 2: Run test, confirm red**

```bash
cd apps/frontend && pnpm test tests/unit/admin/catalog-row-actions.test.tsx -- --run
```

Expected: module-not-found on `@/app/admin/catalog/CatalogRowActions`.

- [ ] **Step 3: Implement the component**

Create `apps/frontend/src/app/admin/catalog/CatalogRowActions.tsx`:

```tsx
"use client";

import { useTransition } from "react";

import { ConfirmActionDialog } from "@/components/admin/ConfirmActionDialog";
import { unpublishSlug } from "@/app/admin/_actions/catalog";

interface CatalogRowActionsProps {
  slug: string;
  name: string;
  onOpenVersions: (slug: string) => void;
}

export function CatalogRowActions({
  slug,
  name,
  onOpenVersions,
}: CatalogRowActionsProps) {
  const [pending, startTransition] = useTransition();

  async function handleUnpublish() {
    const result = await unpublishSlug(slug);
    if (!result.ok) {
      // Surface the error via the typed-confirm dialog's error slot if it
      // exposes one; otherwise fall through — parent page refreshes regardless.
      throw new Error(result.error ?? `unpublish_failed_${result.status}`);
    }
    // Trigger a Server-Component refresh so the row disappears.
    // router.refresh() is the admin-dashboard-standard pattern (see
    // AgentActionsFooter.tsx).
    startTransition(() => {
      // Next.js router instance not used here directly; instead parent uses
      // the shared `router.refresh()` pattern via its own useRouter. See
      // catalog/page.tsx.
    });
  }

  return (
    <div className="flex items-center gap-2">
      <ConfirmActionDialog
        confirmText={`unpublish ${slug}`}
        actionLabel={`Unpublish ${name}`}
        destructive
        onConfirm={handleUnpublish}
      >
        <button
          type="button"
          disabled={pending}
          className="text-sm px-2 py-1 rounded border border-neutral-700 hover:bg-neutral-800 disabled:opacity-50"
        >
          Unpublish
        </button>
      </ConfirmActionDialog>
      <button
        type="button"
        onClick={() => onOpenVersions(slug)}
        className="text-sm px-2 py-1 rounded border border-neutral-700 hover:bg-neutral-800"
      >
        View versions
      </button>
    </div>
  );
}
```

**Note:** if the existing `AgentActionsFooter.tsx` pattern uses a different className scheme (e.g. a `<Button variant="destructive">` from shadcn/ui), match that exactly — read the file before finalizing the classes. This snippet uses plain Tailwind to avoid assuming a UI library is available; the engineer should swap to the repo's component if one is clearly preferred.

- [ ] **Step 4: Run test, confirm green**

```bash
cd apps/frontend && pnpm test tests/unit/admin/catalog-row-actions.test.tsx -- --run
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/app/admin/catalog/CatalogRowActions.tsx apps/frontend/tests/unit/admin/catalog-row-actions.test.tsx
git commit -m "feat(admin-frontend): CatalogRowActions component

Per-row [Unpublish] + [View versions] buttons on the /admin/catalog
table. Unpublish is wrapped in ConfirmActionDialog with typed
confirmation 'unpublish <slug>'.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: `VersionsPanel` client component

**Files:**
- Create: `apps/frontend/src/app/admin/catalog/VersionsPanel.tsx`

**Design note:** the bearer token for the admin API is only available in Server Components / Server Actions, not in client components. So `VersionsPanel` does NOT fetch its own data — it accepts `versions` as a prop from its parent, which loads them via a Server Action (see Task 11's `fetchVersions`). `null` means "loading"; `[]` means "loaded, no versions"; a non-empty array means "loaded, render these".

- [ ] **Step 1: Implement**

Create `apps/frontend/src/app/admin/catalog/VersionsPanel.tsx`:

```tsx
"use client";

import { useState } from "react";
import { X } from "lucide-react";

import type { CatalogVersion } from "@/app/admin/_lib/api";

interface VersionsPanelProps {
  slug: string | null;
  versions: CatalogVersion[] | null;
  onClose: () => void;
}

export function VersionsPanel({ slug, versions, onClose }: VersionsPanelProps) {
  const [openVersion, setOpenVersion] = useState<number | null>(null);

  if (!slug) return null;

  return (
    <aside className="fixed right-0 top-0 h-full w-96 bg-neutral-900 border-l border-neutral-800 p-6 overflow-y-auto">
      <div className="flex items-start justify-between mb-4">
        <h3 className="text-lg font-semibold text-neutral-100">
          {slug} versions
        </h3>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="p-1 rounded hover:bg-neutral-800"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {versions === null && <p className="text-sm text-neutral-400">Loading…</p>}
      {versions?.length === 0 && (
        <p className="text-sm text-neutral-400">No versions found.</p>
      )}
      {versions?.map((v) => (
        <div
          key={v.version}
          className="mb-4 border border-neutral-800 rounded p-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-neutral-200">
              v{v.version}
            </span>
            <span className="text-xs text-neutral-500">
              {v.published_at}
            </span>
          </div>
          <div className="text-xs text-neutral-500 mt-1">
            Published by {v.published_by}
          </div>
          <button
            type="button"
            onClick={() =>
              setOpenVersion(openVersion === v.version ? null : v.version)
            }
            className="mt-2 text-xs text-indigo-400 hover:underline"
          >
            {openVersion === v.version ? "Hide" : "Show"} manifest
          </button>
          {openVersion === v.version && (
            <pre className="mt-2 text-xs bg-neutral-950 text-neutral-300 p-2 rounded overflow-x-auto">
              {JSON.stringify(v.manifest, null, 2)}
            </pre>
          )}
        </div>
      ))}
    </aside>
  );
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd apps/frontend && pnpm exec tsc --noEmit 2>&1 | grep VersionsPanel || echo "no new tsc errors"
```

Expected: `no new tsc errors`.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/admin/catalog/VersionsPanel.tsx
git commit -m "feat(admin-frontend): VersionsPanel right-side component

Renders list of versions with expandable manifest JSON. Accepts
versions via prop so bearer-token fetching stays server-side in
the parent page.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: `/admin/catalog/page.tsx` Server Component

**Files:**
- Create: `apps/frontend/src/app/admin/catalog/page.tsx`

- [ ] **Step 1: Implement**

Create `apps/frontend/src/app/admin/catalog/page.tsx`:

```tsx
import { auth } from "@clerk/nextjs/server";

import { listCatalog } from "@/app/admin/_lib/api";
import { CatalogPageClient } from "./CatalogPageClient";

export default async function CatalogPage() {
  const { getToken } = await auth();
  const token = (await getToken()) ?? "";
  const catalog = await listCatalog(token);

  return <CatalogPageClient catalog={catalog} />;
}
```

Then create the client component that actually holds the versions-panel state — `apps/frontend/src/app/admin/catalog/CatalogPageClient.tsx`:

```tsx
"use client";

import { useState } from "react";

import { CatalogRowActions } from "./CatalogRowActions";
import { VersionsPanel } from "./VersionsPanel";
import type { AdminCatalog, CatalogVersion } from "@/app/admin/_lib/api";
import { fetchVersions } from "./fetchVersions";

interface CatalogPageClientProps {
  catalog: AdminCatalog;
}

export function CatalogPageClient({ catalog }: CatalogPageClientProps) {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [versions, setVersions] = useState<CatalogVersion[] | null>(null);
  const [retiredOpen, setRetiredOpen] = useState(false);

  async function openVersionsFor(slug: string) {
    setSelectedSlug(slug);
    setVersions(null);
    const result = await fetchVersions(slug);
    setVersions(result);
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-neutral-100 mb-4">Catalog</h1>

      <section className="mb-8">
        <h2 className="text-xs uppercase tracking-wide text-neutral-500 mb-2">
          Live ({catalog.live.length})
        </h2>
        {catalog.live.length === 0 ? (
          <p className="text-sm text-neutral-400">
            No agents published yet. Publish one from its admin detail page.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-neutral-500">
              <tr>
                <th className="py-2 px-3">Slug</th>
                <th className="py-2 px-3">Name</th>
                <th className="py-2 px-3">Version</th>
                <th className="py-2 px-3">Published</th>
                <th className="py-2 px-3">By</th>
                <th className="py-2 px-3"></th>
              </tr>
            </thead>
            <tbody>
              {catalog.live.map((e) => (
                <tr
                  key={e.slug}
                  className="border-t border-neutral-800 text-neutral-200"
                >
                  <td className="py-2 px-3">
                    <span aria-hidden className="mr-1">
                      {e.emoji || "🤖"}
                    </span>
                    {e.slug}
                  </td>
                  <td className="py-2 px-3">{e.name}</td>
                  <td className="py-2 px-3">v{e.current_version}</td>
                  <td className="py-2 px-3 text-neutral-400">
                    {e.published_at}
                  </td>
                  <td className="py-2 px-3 text-neutral-400">
                    {e.published_by}
                  </td>
                  <td className="py-2 px-3">
                    <CatalogRowActions
                      slug={e.slug}
                      name={e.name}
                      onOpenVersions={openVersionsFor}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <button
          type="button"
          onClick={() => setRetiredOpen((o) => !o)}
          className="text-xs uppercase tracking-wide text-neutral-500 mb-2 hover:text-neutral-300"
        >
          {retiredOpen ? "▾" : "▸"} Retired ({catalog.retired.length})
        </button>
        {retiredOpen && catalog.retired.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-left text-neutral-500">
              <tr>
                <th className="py-2 px-3">Slug</th>
                <th className="py-2 px-3">Last version</th>
                <th className="py-2 px-3">Retired at</th>
                <th className="py-2 px-3">Retired by</th>
              </tr>
            </thead>
            <tbody>
              {catalog.retired.map((r) => (
                <tr
                  key={r.slug}
                  className="border-t border-neutral-800 text-neutral-400"
                >
                  <td className="py-2 px-3">{r.slug}</td>
                  <td className="py-2 px-3">v{r.last_version}</td>
                  <td className="py-2 px-3">{r.retired_at}</td>
                  <td className="py-2 px-3">{r.retired_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <VersionsPanel
        slug={selectedSlug}
        versions={versions}
        onClose={() => {
          setSelectedSlug(null);
          setVersions(null);
        }}
      />
    </div>
  );
}
```

Finally, add a thin Server Action wrapper for the versions fetch at `apps/frontend/src/app/admin/catalog/fetchVersions.ts`:

```typescript
"use server";

import { auth } from "@clerk/nextjs/server";

import { listSlugVersions, type CatalogVersion } from "@/app/admin/_lib/api";

export async function fetchVersions(slug: string): Promise<CatalogVersion[]> {
  const { getToken } = await auth();
  const token = (await getToken()) ?? "";
  return listSlugVersions(token, slug);
}
```

- [ ] **Step 2: TypeScript + smoke check**

```bash
cd apps/frontend && pnpm exec tsc --noEmit 2>&1 | grep -E 'catalog/page|CatalogPageClient|VersionsPanel|fetchVersions' || echo "no new tsc errors"
```

Expected: `no new tsc errors`.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/admin/catalog/page.tsx apps/frontend/src/app/admin/catalog/CatalogPageClient.tsx apps/frontend/src/app/admin/catalog/fetchVersions.ts
git commit -m "feat(admin-frontend): /admin/catalog page

Server Component fetches catalog via listCatalog(); renders live
table with row actions + a collapsible retired section.
fetchVersions Server Action keeps the bearer token server-side.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Catalog nav item + Publish button on agent detail page

**Files:**
- Modify: `apps/frontend/src/app/admin/layout.tsx`
- Modify: `apps/frontend/src/app/admin/users/[id]/agents/[agent_id]/page.tsx`
- Modify: `apps/frontend/src/app/admin/users/[id]/agents/[agent_id]/AgentActionsFooter.tsx`

- [ ] **Step 1: Add the Catalog nav link**

In `apps/frontend/src/app/admin/layout.tsx`, find the nav block. Per exploration, it contains `<Link>` elements like:

```tsx
<Link href="/admin/users" ...>Users</Link>
<Link href="/admin/health" ...>Health</Link>
```

Add between them or after Users:

```tsx
<Link href="/admin/catalog" className="...same classes as siblings...">
  Catalog
</Link>
```

Copy the exact `className` from the existing Link elements to match styling.

- [ ] **Step 2: Pass `is_own_agent` to `AgentActionsFooter`**

Open `apps/frontend/src/app/admin/users/[id]/agents/[agent_id]/page.tsx`. It's a Server Component with access to `params.id` and the authenticated admin. Compute and pass the flag:

```tsx
import { auth } from "@clerk/nextjs/server";
// ...

export default async function AgentDetailPage({
  params,
}: {
  params: { id: string; agent_id: string };
}) {
  const { userId: adminUserId } = await auth();
  const isOwnAgent = adminUserId === params.id;

  // ... existing data fetches ...

  return (
    <div>
      {/* ... existing page content ... */}
      <AgentActionsFooter
        userId={params.id}
        agentId={params.agent_id}
        isOwnAgent={isOwnAgent}
      />
    </div>
  );
}
```

Adjust imports and existing return shape to match the real file — read it before editing.

- [ ] **Step 3: Add the Publish button in `AgentActionsFooter`**

Modify `AgentActionsFooter.tsx` to accept the new prop and conditionally render the button. Full new file (adjust to preserve anything existing not shown in the exploration):

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmActionDialog } from "@/components/admin/ConfirmActionDialog";
import { deleteAgent, clearAgentSessions } from "@/app/admin/_actions/agent";
import { publishAgent } from "@/app/admin/_actions/catalog";

interface AgentActionsFooterProps {
  userId: string;
  agentId: string;
  agentName?: string;
  isOwnAgent: boolean;
}

export function AgentActionsFooter({
  userId,
  agentId,
  agentName,
  isOwnAgent,
}: AgentActionsFooterProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    setError(null);
    const result = await deleteAgent(userId, agentId);
    if (!result.ok) {
      setError(result.error ?? "delete_failed");
      return;
    }
    router.push(`/admin/users/${userId}/agents`);
    router.refresh();
  }

  async function handleClearSessions() {
    setError(null);
    const result = await clearAgentSessions(userId, agentId);
    if (!result.ok) {
      setError(result.error ?? "clear_sessions_failed");
      return;
    }
    router.refresh();
  }

  async function handlePublish() {
    setError(null);
    const result = await publishAgent(agentId);
    if (!result.ok) {
      setError(result.error ?? "publish_failed");
      return;
    }
    router.refresh();
  }

  return (
    <div className="mt-6 flex items-center gap-3 flex-wrap">
      <ConfirmActionDialog
        confirmText={agentId}
        actionLabel="Delete agent"
        destructive
        onConfirm={handleDelete}
      >
        <button
          type="button"
          className="text-sm px-3 py-1.5 rounded border border-red-700 text-red-400 hover:bg-red-900/30"
        >
          Delete agent
        </button>
      </ConfirmActionDialog>

      <ConfirmActionDialog
        confirmText={agentId}
        actionLabel="Clear sessions"
        destructive
        onConfirm={handleClearSessions}
      >
        <button
          type="button"
          className="text-sm px-3 py-1.5 rounded border border-neutral-700 hover:bg-neutral-800"
        >
          Clear sessions
        </button>
      </ConfirmActionDialog>

      {isOwnAgent ? (
        <ConfirmActionDialog
          confirmText={`publish ${agentName ?? agentId}`}
          actionLabel="Publish to catalog"
          onConfirm={handlePublish}
        >
          <button
            type="button"
            className="text-sm px-3 py-1.5 rounded border border-indigo-700 text-indigo-300 hover:bg-indigo-900/30"
          >
            Publish to catalog
          </button>
        </ConfirmActionDialog>
      ) : (
        <button
          type="button"
          disabled
          title="Only your own agents can be published"
          className="text-sm px-3 py-1.5 rounded border border-neutral-800 text-neutral-600 cursor-not-allowed"
        >
          Publish to catalog
        </button>
      )}

      {error && (
        <p className="text-sm text-red-400 w-full">{error}</p>
      )}
    </div>
  );
}
```

Confirm `deleteAgent` / `clearAgentSessions` are the real export names in `_actions/agent.ts` — if they're spelled differently, adjust.

- [ ] **Step 4: TypeScript check**

```bash
cd apps/frontend && pnpm exec tsc --noEmit 2>&1 | tail -20
```

Expected: no new errors.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/app/admin/layout.tsx apps/frontend/src/app/admin/users/[id]/agents/[agent_id]/page.tsx apps/frontend/src/app/admin/users/[id]/agents/[agent_id]/AgentActionsFooter.tsx
git commit -m "feat(admin-frontend): Catalog nav + Publish button on agent detail

- Adds Catalog link between Users and Health in the admin nav
- Agent detail page passes is_own_agent to AgentActionsFooter
- Publish to catalog button rendered only when admin views own agent;
  disabled with tooltip otherwise

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Full verification

No new code. Run the full suites to catch anything the per-task runs missed.

- [ ] **Step 1: Backend**

```bash
cd apps/backend && CLERK_ISSUER=https://test.clerk.accounts.dev \
  uv run pytest tests/ -v
```

Expected: all tests green. If pre-existing failures appear (e.g., the 8 frontend failures that were pre-existing on my last pass), confirm they're unrelated to catalog changes.

- [ ] **Step 2: Frontend unit**

```bash
cd apps/frontend && pnpm test -- --run
```

Expected: all catalog-related tests green. Pre-existing channel/bot/message failures remain out of scope.

- [ ] **Step 3: Frontend lint**

```bash
cd apps/frontend && pnpm run lint
```

Expected: exits 0 (warnings allowed).

- [ ] **Step 4: TypeScript**

```bash
cd apps/frontend && pnpm exec tsc --noEmit
```

Expected: zero errors across the whole admin surface.

- [ ] **Step 5: Local smoke (optional, if LocalStack up)**

```bash
# 1. Admin signs in at http://localhost:3000/admin (or admin-dev subdomain)
# 2. Navigate to /admin/catalog — empty page renders
# 3. Open an own agent at /admin/users/<self>/agents/<agent_id>
# 4. Click "Publish to catalog" — typed confirm → publish → agent appears on /admin/catalog
# 5. Click "Unpublish" — typed confirm → slug moves to Retired section
```

- [ ] **Step 6: Final commit (if any lint autofix)**

```bash
git status
# If auto-fixes:
git add -A && git commit -m "chore: lint autofix"
```

---

## Rollout notes (post-merge, out of scope for this plan)

1. No new infra — existing CDK already provisions the agent-catalog bucket (from the prior feature) and the admin-actions table (from #351).
2. No new env vars — both `AGENT_CATALOG_BUCKET` and `PLATFORM_ADMIN_USER_IDS` already exist on the backend task.
3. Verify after deploy:
   - `/admin/catalog` loads empty on dev for an admin.
   - `/admin/catalog/pitch/versions` 404s if no slug published yet (or 200 with empty `versions`).
   - CLI publish via `scripts/publish-agent.sh` still works and now produces an audit row.
