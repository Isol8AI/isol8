from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from core.auth import AuthContext, get_current_user, require_platform_admin
from core.services.catalog_service import get_catalog_service


def _override_user(user_id: str):
    def _dep() -> AuthContext:
        return AuthContext(user_id=user_id)

    return _dep


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_service():
    svc = MagicMock()
    app.dependency_overrides[get_catalog_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_catalog_service, None)


@pytest.fixture
def admin_env():
    """Safety net so require_platform_admin admits user_admin_42.

    Most tests in this file ALSO override require_platform_admin directly,
    which bypasses the email gate entirely — this fixture is decorative in
    that case. For tests that only rely on the email-domain gate, we bind
    get_current_user so the downstream `require_platform_admin` sees an
    AuthContext with an @isol8.co email.
    """
    app.dependency_overrides[get_current_user] = lambda: AuthContext(user_id="user_admin_42", email="admin@isol8.co")
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_list_returns_catalog_entries(client, mock_service):
    app.dependency_overrides[get_current_user] = _override_user("user_a")
    mock_service.list.return_value = [
        {
            "slug": "pitch",
            "name": "Pitch",
            "version": 3,
            "emoji": "🎯",
            "vibe": "Direct",
            "description": "Sales",
            "suggested_model": "qwen",
            "suggested_channels": [],
            "required_skills": ["web-search"],
            "required_plugins": ["memory"],
        }
    ]
    r = client.get("/api/v1/catalog")
    assert r.status_code == 200
    assert r.json()["agents"][0]["slug"] == "pitch"
    app.dependency_overrides.pop(get_current_user, None)


def test_deploy_returns_new_agent_id(client, mock_service):
    app.dependency_overrides[get_current_user] = _override_user("user_a")
    mock_service.deploy = AsyncMock(
        return_value={
            "slug": "pitch",
            "version": 3,
            "agent_id": "agent_xyz",
            "name": "Pitch",
            "skills_added": ["web-search"],
            "plugins_enabled": ["memory"],
        }
    )
    r = client.post("/api/v1/catalog/deploy", json={"slug": "pitch"})
    assert r.status_code == 200
    assert r.json()["agent_id"] == "agent_xyz"
    mock_service.deploy.assert_awaited_once_with(owner_id="user_a", slug="pitch")
    app.dependency_overrides.pop(get_current_user, None)


def test_deploy_missing_slug_422(client, mock_service):
    app.dependency_overrides[get_current_user] = _override_user("user_a")
    r = client.post("/api/v1/catalog/deploy", json={})
    assert r.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


def test_deployed_lists_user_agent_template_provenance(client, mock_service):
    app.dependency_overrides[get_current_user] = _override_user("user_a")
    mock_service.list_deployed_for_user = MagicMock(
        return_value=[
            {"agent_id": "agent_1", "template_slug": "pitch", "template_version": 3},
        ]
    )
    r = client.get("/api/v1/catalog/deployed")
    assert r.status_code == 200
    assert r.json()["deployed"][0]["template_slug"] == "pitch"
    app.dependency_overrides.pop(get_current_user, None)


def test_publish_requires_platform_admin(client, mock_service):
    from fastapi import HTTPException

    def _deny() -> AuthContext:
        raise HTTPException(status_code=403, detail="Platform admin access required")

    app.dependency_overrides[require_platform_admin] = _deny

    r = client.post("/api/v1/admin/catalog/publish", json={"agent_id": "a1"})
    assert r.status_code == 403
    app.dependency_overrides.pop(require_platform_admin, None)


def test_publish_happy_path(client, mock_service):
    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin")
    mock_service.publish = AsyncMock(return_value={"slug": "pitch", "version": 4, "s3_prefix": "pitch/v4"})
    r = client.post("/api/v1/admin/catalog/publish", json={"agent_id": "agent_abc"})
    assert r.status_code == 200
    assert r.json()["version"] == 4
    mock_service.publish.assert_awaited_once()
    app.dependency_overrides.pop(require_platform_admin, None)


def test_publish_writes_audit_row(client, mock_service, admin_env):
    """POST /admin/catalog/publish creates an admin-actions row with
    action=catalog.publish and target_user_id=__catalog__."""
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin_42")
    mock_service.publish = AsyncMock(return_value={"slug": "pitch", "version": 1, "s3_prefix": "pitch/v1"})

    audit_mock = AsyncMock()
    with patch("core.repositories.admin_actions_repo.create", new=audit_mock):
        r = client.post(
            "/api/v1/admin/catalog/publish",
            json={"agent_id": "agent_abc"},
        )

    assert r.status_code == 200
    assert audit_mock.await_count == 1

    row_kwargs = audit_mock.await_args.kwargs
    assert row_kwargs["action"] == "catalog.publish"
    assert row_kwargs["target_user_id"] == "__catalog__"
    assert row_kwargs["admin_user_id"] == "user_admin_42"

    app.dependency_overrides.pop(require_platform_admin, None)


def test_admin_list_catalog_returns_live_and_retired(client, mock_service):
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin")
    mock_service.list_all = MagicMock(
        return_value={
            "live": [
                {
                    "slug": "pitch",
                    "name": "Pitch",
                    "current_version": 3,
                    "emoji": "🎯",
                    "vibe": "",
                    "description": "",
                    "suggested_model": "",
                    "suggested_channels": [],
                    "required_skills": [],
                    "required_plugins": [],
                    "published_at": "2026-04-22T00:00:00Z",
                    "published_by": "user_admin",
                }
            ],
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

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin")
    mock_service.unpublish = AsyncMock(
        return_value={"slug": "pitch", "last_version": 3, "last_manifest_url": "pitch/v3/manifest.json"}
    )

    audit_mock = AsyncMock()
    with patch("core.repositories.admin_actions_repo.create", new=audit_mock):
        r = client.post("/api/v1/admin/catalog/pitch/unpublish")

    assert r.status_code == 200
    assert r.json()["slug"] == "pitch"
    mock_service.unpublish.assert_awaited_once_with(admin_user_id="user_admin", slug="pitch")
    assert audit_mock.await_count == 1
    row_kwargs = audit_mock.await_args.kwargs
    assert row_kwargs["action"] == "catalog.unpublish"
    assert row_kwargs["target_user_id"] == "__catalog__"
    app.dependency_overrides.pop(require_platform_admin, None)


def test_admin_unpublish_missing_slug_404(client, mock_service):
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin")
    mock_service.unpublish = AsyncMock(side_effect=KeyError("not live"))

    r = client.post("/api/v1/admin/catalog/ghost/unpublish")
    assert r.status_code == 404

    app.dependency_overrides.pop(require_platform_admin, None)


def test_admin_list_versions(client, mock_service):
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin")
    mock_service.list_versions = MagicMock(
        return_value=[
            {
                "version": 1,
                "manifest_url": "pitch/v1/manifest.json",
                "published_at": "2026-04-19T00:00:00Z",
                "published_by": "user_admin",
                "manifest": {"slug": "pitch", "version": 1},
            },
        ]
    )
    r = client.get("/api/v1/admin/catalog/pitch/versions")
    assert r.status_code == 200
    body = r.json()
    assert body["versions"][0]["version"] == 1
    app.dependency_overrides.pop(require_platform_admin, None)


def test_publish_audit_captures_agent_id_in_payload(client, mock_service):
    """Publish audit row includes the agent_id (and optional slug/description) from req."""
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin_42")
    mock_service.publish = AsyncMock(return_value={"slug": "pitch", "version": 1, "s3_prefix": "pitch/v1"})

    audit_mock = AsyncMock()
    with patch("core.repositories.admin_actions_repo.create", new=audit_mock):
        r = client.post(
            "/api/v1/admin/catalog/publish",
            json={"agent_id": "agent_abc", "slug": "custom-pitch"},
        )

    assert r.status_code == 200
    payload = audit_mock.await_args.kwargs["payload"]
    assert payload["req"]["agent_id"] == "agent_abc"
    assert payload["req"]["slug"] == "custom-pitch"

    app.dependency_overrides.pop(require_platform_admin, None)


def test_unpublish_audit_captures_slug_in_payload(client, mock_service):
    """Unpublish audit row includes the slug path param."""
    from core.auth import AuthContext, require_platform_admin
    from main import app

    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin")
    mock_service.unpublish = AsyncMock(
        return_value={"slug": "pitch", "last_version": 3, "last_manifest_url": "pitch/v3/manifest.json"}
    )

    audit_mock = AsyncMock()
    with patch("core.repositories.admin_actions_repo.create", new=audit_mock):
        r = client.post("/api/v1/admin/catalog/pitch/unpublish")

    assert r.status_code == 200
    assert audit_mock.await_args.kwargs["payload"] == {"slug": "pitch"}

    app.dependency_overrides.pop(require_platform_admin, None)


def test_unpublish_idempotency_returns_cached_on_replay(client, mock_service):
    """Replayed POST with the same Idempotency-Key short-circuits — service runs once.

    Without @idempotency(), the second call would hit service.unpublish again
    which, after the first call retired the slug, would raise KeyError and
    surface as a 404 to the client (a completed action wrongly reported as
    a failure). With @idempotency(), the cached 200 payload is returned.
    """
    from core.auth import AuthContext, require_platform_admin
    from core.services.idempotency import reset_cache
    from main import app

    reset_cache()
    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin")
    mock_service.unpublish = AsyncMock(
        return_value={
            "slug": "pitch",
            "last_version": 3,
            "last_manifest_url": "pitch/v3/manifest.json",
        }
    )
    headers = {"Idempotency-Key": "test-unpublish-key-12345"}

    with patch("core.repositories.admin_actions_repo.create", new=AsyncMock()):
        r1 = client.post("/api/v1/admin/catalog/pitch/unpublish", headers=headers)
        r2 = client.post("/api/v1/admin/catalog/pitch/unpublish", headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    # Service was called exactly once; second POST returned the cached result.
    assert mock_service.unpublish.await_count == 1

    app.dependency_overrides.pop(require_platform_admin, None)
    reset_cache()


def test_publish_idempotency_returns_cached_on_replay(client, mock_service):
    """Replayed publish POST with the same Idempotency-Key short-circuits.

    Without @idempotency(), a retried publish would bump the version on
    every network retry. With @idempotency(), the cached 200 payload is
    returned and service.publish runs exactly once.
    """
    from core.auth import AuthContext, require_platform_admin
    from core.services.idempotency import reset_cache
    from main import app

    reset_cache()
    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin")
    mock_service.publish = AsyncMock(return_value={"slug": "pitch", "version": 4, "s3_prefix": "pitch/v4"})
    headers = {"Idempotency-Key": "test-publish-key-67890"}

    with patch("core.repositories.admin_actions_repo.create", new=AsyncMock()):
        r1 = client.post(
            "/api/v1/admin/catalog/publish",
            json={"agent_id": "agent_abc"},
            headers=headers,
        )
        r2 = client.post(
            "/api/v1/admin/catalog/publish",
            json={"agent_id": "agent_abc"},
            headers=headers,
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    assert mock_service.publish.await_count == 1

    app.dependency_overrides.pop(require_platform_admin, None)
    reset_cache()


def test_admin_catalog_endpoints_require_platform_admin(client):
    """Any non-admin user hitting /admin/catalog/* returns 403."""
    from core.auth import require_platform_admin
    from main import app
    from fastapi import HTTPException

    def _deny():
        raise HTTPException(status_code=403, detail="Platform admin access required")

    app.dependency_overrides[require_platform_admin] = _deny

    assert client.get("/api/v1/admin/catalog").status_code == 403
    assert client.post("/api/v1/admin/catalog/pitch/unpublish").status_code == 403
    assert client.get("/api/v1/admin/catalog/pitch/versions").status_code == 403
    app.dependency_overrides.pop(require_platform_admin, None)


# ---- owner_id resolution at the router boundary ----
#
# Codex P1: deploy() must derive ownership from the caller's active JWT
# context (resolve_owner_id(auth)) — NOT from a Clerk membership lookup —
# so a user with org memberships but currently in personal context never
# accidentally writes into the org partition.
#
# Codex P2: deploy and list_deployed must be keyed identically. Both
# routers use resolve_owner_id(auth) so they always agree.


def test_deploy_passes_org_owner_id_when_caller_is_in_org_context(client, mock_service):
    """End-user in org context: router must pass owner_id=org_id to service."""
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="user_member",
        org_id="org_abc",
        org_role="org:member",
    )
    mock_service.deploy = AsyncMock(
        return_value={
            "slug": "pitch",
            "version": 3,
            "agent_id": "agent_xyz",
            "name": "Pitch",
            "skills_added": [],
            "plugins_enabled": [],
        }
    )
    r = client.post("/api/v1/catalog/deploy", json={"slug": "pitch"})
    assert r.status_code == 200
    mock_service.deploy.assert_awaited_once_with(owner_id="org_abc", slug="pitch")
    app.dependency_overrides.pop(get_current_user, None)


def test_deploy_passes_user_owner_id_when_caller_is_personal(client, mock_service):
    """End-user in personal mode: owner_id == user_id, even if user has org memberships
    elsewhere — the JWT's active context wins (Codex P1)."""
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="user_solo",
        org_id=None,  # personal context
    )
    mock_service.deploy = AsyncMock(
        return_value={
            "slug": "pitch",
            "version": 3,
            "agent_id": "agent_xyz",
            "name": "Pitch",
            "skills_added": [],
            "plugins_enabled": [],
        }
    )
    r = client.post("/api/v1/catalog/deploy", json={"slug": "pitch"})
    assert r.status_code == 200
    mock_service.deploy.assert_awaited_once_with(owner_id="user_solo", slug="pitch")
    app.dependency_overrides.pop(get_current_user, None)


def test_list_deployed_keyed_by_owner_id_in_org_context(client, mock_service):
    """Codex P2 regression: deploy + list must be keyed identically. Router
    passes owner_id (not user_id) so org-context deploys remain visible."""
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="user_member",
        org_id="org_abc",
        org_role="org:member",
    )
    mock_service.list_deployed_for_user = MagicMock(
        return_value=[{"agent_id": "agent_xx", "template_slug": "pitch", "template_version": 3}]
    )
    r = client.get("/api/v1/catalog/deployed")
    assert r.status_code == 200
    mock_service.list_deployed_for_user.assert_called_once_with("org_abc")
    app.dependency_overrides.pop(get_current_user, None)


def test_publish_passes_org_owner_id_when_admin_in_org_context(client, mock_service):
    """Admin publishing while in org context: owner_id=org_id (where the agent's
    EFS lives), but admin_user_id stays as the raw user_id for published_by."""
    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(
        user_id="user_admin",
        email="admin@isol8.co",
        org_id="org_abc",
        org_role="org:admin",
    )
    mock_service.publish = AsyncMock(return_value={"slug": "pitch", "version": 1, "s3_prefix": "pitch/v1"})
    r = client.post(
        "/api/v1/admin/catalog/publish",
        json={"agent_id": "agent_admin_pitch"},
    )
    assert r.status_code == 200
    mock_service.publish.assert_awaited_once_with(
        admin_user_id="user_admin",
        owner_id="org_abc",
        agent_id="agent_admin_pitch",
        slug_override=None,
        description_override=None,
    )
    app.dependency_overrides.pop(require_platform_admin, None)
