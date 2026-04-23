"""Tests for `require_platform_admin` — the @isol8.co email-domain gate.

Policy: a caller is a platform admin iff the Clerk JWT's `email` claim ends
with `@isol8.co` (case-insensitive). No env var, no allowlist — Clerk is the
source of truth for who holds an @isol8.co email.
"""

import pytest
from fastapi import HTTPException

from core.auth import AuthContext, require_platform_admin


def _make_auth(email: str | None) -> AuthContext:
    return AuthContext(user_id="user_test", email=email)


def test_require_platform_admin_allows_isol8_email():
    auth = _make_auth("prasiddha@isol8.co")
    assert require_platform_admin(auth) is auth


def test_require_platform_admin_rejects_external_email():
    auth = _make_auth("attacker@example.com")
    with pytest.raises(HTTPException) as exc:
        require_platform_admin(auth)
    assert exc.value.status_code == 403


def test_require_platform_admin_rejects_missing_email():
    auth = _make_auth(None)
    with pytest.raises(HTTPException) as exc:
        require_platform_admin(auth)
    assert exc.value.status_code == 403


def test_require_platform_admin_is_case_insensitive():
    """Clerk may echo emails with mixed case; the gate must lowercase before comparing."""
    auth = _make_auth("PRASIDDHA@ISOL8.CO")
    assert require_platform_admin(auth) is auth
