"""Shared FastAPI deps for the Teams BFF routers.

Centralizes the (auth -> paperclip-companies row -> user-session cookie)
chain that every Teams endpoint runs at the top of its handler. Lives
as a class + a resolver so we can unit-test without a FastAPI request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from fastapi import HTTPException

from core.auth import AuthContext, resolve_owner_id
from core.repositories.paperclip_repo import PaperclipCompany


class TeamsContextError(HTTPException):
    """HTTPException with a friendlier name for raising at the boundary."""


@dataclass
class TeamsContext:
    user_id: str
    org_id: str | None
    owner_id: str
    company_id: str
    paperclip_user_id: str
    session_cookie: str


class _Repo(Protocol):
    async def get(self, user_id: str) -> PaperclipCompany | None: ...


SessionFactory = Callable[[str], Awaitable[str]]


async def resolve_teams_context(
    *,
    auth: AuthContext,
    repo: _Repo,
    session_factory: SessionFactory,
) -> TeamsContext:
    """Build a ``TeamsContext`` for the current request, or raise.

    Status codes follow spec §9 error handling:
      - 409 if there's no DDB row at all (provisioning never started).
      - 202 if the row exists but ``status != "active"``. The UI polls.
      - 503 if the row is ``status="failed"`` (operator-resolved).
    """
    company = await repo.get(auth.user_id)
    if company is None:
        raise TeamsContextError(status_code=409, detail="team workspace not provisioned")
    if company.status == "provisioning":
        raise TeamsContextError(status_code=202, detail="team workspace provisioning")
    if company.status == "failed":
        raise TeamsContextError(status_code=503, detail="team workspace provisioning failed")
    if company.status != "active":
        raise TeamsContextError(status_code=503, detail=f"team workspace status={company.status}")

    cookie = await session_factory(auth.user_id)

    return TeamsContext(
        user_id=auth.user_id,
        org_id=auth.org_id,
        owner_id=resolve_owner_id(auth),
        company_id=company.company_id,
        paperclip_user_id=company.paperclip_user_id,
        session_cookie=cookie,
    )
