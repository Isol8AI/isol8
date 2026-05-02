"""Admin session manager for the Paperclip service account.

Maintains a long-lived Better Auth session for ``admin@isol8.co`` —
the only user with the ``instance_admin`` role on the Paperclip
deployment. Used by ``paperclip_provisioning`` to call privileged
endpoints (``POST /api/companies``, ``approve_join_request``, etc.)
that regular signed-up users can't reach in Paperclip's
``authenticated`` deployment mode.

**Why a service account instead of granting every user instance_admin:**
the alternative — putting Paperclip in ``local_trusted`` mode — would
make every request implicit-admin and lose Paperclip's per-company
authz isolation entirely. With the service account, regular users
remain non-admin (Paperclip's authz still filters their requests by
company memberships), and only the backend has elevated privileges.

**Credential lifecycle:**
- Read once per process from Secrets Manager (``isol8/{env}/paperclip_admin_credentials``)
- Cached for the process lifetime
- Better Auth session re-acquired on first call after process start, on
  401 from any downstream admin call (call ``invalidate_admin_session()``),
  and after ~23h regardless (well below Better Auth's 7-day default TTL)
- Async-safe: concurrent callers serialize on a single asyncio.Lock so
  we don't issue parallel sign-ins on cold start

**Bootstrap dependency:**
This module raises a clear ``RuntimeError`` if the Secrets Manager entry
doesn't exist — that means the operator hasn't run
``apps/backend/scripts/bootstrap_paperclip_admin.py`` yet. Provisioning
fails loudly rather than silently degrading.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import boto3
import httpx

from core.services.paperclip_admin_client import PaperclipAdminClient

logger = logging.getLogger(__name__)

# Refresh well before Better Auth's 7-day default expiry. 23h gives at
# most one refresh per day; on backend redeploys we get a fresh session
# anyway. Tuning knob — if Paperclip's TTL changes, lower this.
_SESSION_TTL_SECONDS = 23 * 3600

# AWS Secrets Manager naming convention. Per-env: dev →
# ``isol8/dev/paperclip_admin_credentials``. Created by the bootstrap
# script after sign-up; fields ``email`` + ``password`` (JSON).
_SECRET_NAME_TEMPLATE = "isol8/{env}/paperclip_admin_credentials"


class _AdminSessionState:
    """Singleton state for the process. Held outside any class so
    multiple PaperclipAdminClient instances share the same session.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._token: str | None = None
        self._token_acquired_at: float = 0.0
        self._email: str | None = None
        self._password: str | None = None

    def is_token_fresh(self) -> bool:
        return self._token is not None and (time.time() - self._token_acquired_at) < _SESSION_TTL_SECONDS

    def invalidate(self) -> None:
        self._token = None
        self._token_acquired_at = 0.0


_state = _AdminSessionState()


def _load_credentials_from_secrets_manager(env: str) -> tuple[str, str]:
    """Synchronous Secrets Manager read. boto3 has no async support
    natively; for a one-shot at first sign-in the sync call inside
    ``asyncio.to_thread`` is fine.
    """
    secret_name = _SECRET_NAME_TEMPLATE.format(env=env)
    client = boto3.client("secretsmanager")
    try:
        resp = client.get_secret_value(SecretId=secret_name)
    except client.exceptions.ResourceNotFoundException as e:
        raise RuntimeError(
            f"Paperclip admin credentials not found at {secret_name}. "
            "Run apps/backend/scripts/bootstrap_paperclip_admin.py once per env "
            "to create the admin user and write the secret."
        ) from e
    payload = json.loads(resp["SecretString"])
    email = payload.get("email")
    password = payload.get("password")
    if not email or not password:
        raise RuntimeError(f"Secret {secret_name} is malformed: expected JSON with 'email' and 'password' fields")
    return email, password


async def get_admin_session_token(http_client: httpx.AsyncClient) -> str:
    """Return a fresh Better Auth session token for admin@isol8.co.

    Uses the caller-provided httpx client (so the lifecycle is owned
    by whoever's making the provisioning call). Caches the token; on
    expiry or invalidation, re-signs-in. Async-safe.
    """
    async with _state._lock:
        if _state.is_token_fresh():
            assert _state._token is not None
            return _state._token

        if _state._email is None or _state._password is None:
            env = os.environ.get("ENVIRONMENT", "")
            email, password = await asyncio.to_thread(_load_credentials_from_secrets_manager, env)
            _state._email = email
            _state._password = password

        admin = PaperclipAdminClient(http_client=http_client)
        signin = await admin.sign_in_user(
            email=_state._email,
            password=_state._password,
        )
        token = signin.get("token")
        if not token:
            raise RuntimeError("Better Auth sign-in for admin returned no token")

        _state._token = token
        _state._token_acquired_at = time.time()
        logger.info(
            "paperclip_admin_session: acquired admin session for %s",
            _state._email,
        )
        return token


def invalidate_admin_session() -> None:
    """Force re-acquisition of the admin session on the next call.

    Called by provisioning when an admin-bearing request returns 401
    (session expired, password rotated, etc.). The next
    ``get_admin_session_token`` call will sign in fresh.
    """
    _state.invalidate()
    logger.info("paperclip_admin_session: invalidated cached session token")
