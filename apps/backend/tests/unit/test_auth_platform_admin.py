import pytest
from fastapi import HTTPException

from core.auth import AuthContext, require_platform_admin


def _make_auth(user_id: str) -> AuthContext:
    return AuthContext(user_id=user_id)


def test_require_platform_admin_allows_listed_user(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_USER_IDS", "user_alpha,user_beta")
    from core import config

    config.settings.PLATFORM_ADMIN_USER_IDS = "user_alpha,user_beta"

    auth = _make_auth("user_alpha")
    assert require_platform_admin(auth) is auth


def test_require_platform_admin_rejects_unlisted_user(monkeypatch):
    from core import config

    config.settings.PLATFORM_ADMIN_USER_IDS = "user_alpha"

    auth = _make_auth("user_outsider")
    with pytest.raises(HTTPException) as exc:
        require_platform_admin(auth)
    assert exc.value.status_code == 403


def test_require_platform_admin_rejects_when_allowlist_empty():
    from core import config

    config.settings.PLATFORM_ADMIN_USER_IDS = ""

    auth = _make_auth("anyone")
    with pytest.raises(HTTPException) as exc:
        require_platform_admin(auth)
    assert exc.value.status_code == 403
