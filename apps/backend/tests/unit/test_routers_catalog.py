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
def admin_env(monkeypatch):
    monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_admin_42")
    yield


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
    mock_service.deploy.assert_awaited_once_with(user_id="user_a", slug="pitch")
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
