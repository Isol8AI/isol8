"""Clerk Backend API client for admin-side read operations.

Phase B v1 surface: list users, get one user. Mutation operations
(ban / unban / revoke sessions / resend verification) are added in
Phase C alongside the admin router endpoints that need them.

There is no centralized Clerk client in this codebase yet — billing.py
and desktop_auth.py call api.clerk.com inline via httpx. This module
consolidates the admin-side calls so admin_service.py can compose
without duplicating httpx setup.

Empty/missing CLERK_SECRET_KEY → callers get a stubbed empty response
so local dev without real Clerk admin creds still renders the admin
UI (with no users listed).
"""

import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


_CLERK_API_BASE = "https://api.clerk.com/v1"
_TIMEOUT_S = 5.0


async def list_users(*, query: str = "", limit: int = 50, offset: int = 0) -> dict:
    """Paginated list. Returns {users: list[dict], next_offset: int | None}.

    `query` is a Clerk search string (matches email, first/last name,
    user_id). `offset` is integer-paged (Clerk supports limit + offset).
    Stubs when CLERK_SECRET_KEY is unset.
    """
    if not settings.CLERK_SECRET_KEY:
        return {"users": [], "next_offset": None, "stubbed": True}

    params: dict = {"limit": min(limit, 500), "offset": offset, "order_by": "-created_at"}
    if query:
        params["query"] = query

    headers = {"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(f"{_CLERK_API_BASE}/users", headers=headers, params=params)
    except httpx.TimeoutException:
        return {"users": [], "next_offset": None, "error": "timeout"}
    except Exception as e:  # noqa: BLE001
        logger.warning("clerk_admin.list_users network error: %s", e)
        return {"users": [], "next_offset": None, "error": str(e)}

    if response.status_code >= 400:
        logger.warning("clerk_admin.list_users HTTP %s", response.status_code)
        return {"users": [], "next_offset": None, "error": f"http_{response.status_code}"}

    users = response.json()
    next_offset = offset + len(users) if len(users) >= limit else None
    return {"users": users, "next_offset": next_offset, "stubbed": False}


async def get_user(user_id: str) -> dict | None:
    """Single user by Clerk user_id. Returns None on 404."""
    if not settings.CLERK_SECRET_KEY:
        return None

    headers = {"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(f"{_CLERK_API_BASE}/users/{user_id}", headers=headers)
    except Exception as e:  # noqa: BLE001
        logger.warning("clerk_admin.get_user network error: %s", e)
        return None

    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        logger.warning("clerk_admin.get_user HTTP %s", response.status_code)
        return None
    return response.json()
