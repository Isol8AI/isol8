"""Teams BFF — Issues.

Tier 2 mutating resource: ``CreateIssueBody`` and ``PatchIssueBody``
forbid extras, so unknown / smuggled fields are 422'd at the FastAPI
boundary. No adapter synthesis here — issues are pure user data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from . import agents as _agents
from .deps import TeamsContext
from .schemas import CreateIssueBody, PatchIssueBody

router = APIRouter()
_ctx = _agents._ctx


@router.get("/issues")
async def list_issues(ctx: TeamsContext = Depends(_ctx)):
    """List issues in the caller's company."""
    return await _agents._admin().list_issues(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )


@router.get("/issues/{issue_id}")
async def get_issue(issue_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Fetch a single issue by id."""
    return await _agents._admin().get_issue(
        issue_id=issue_id,
        session_cookie=ctx.session_cookie,
    )


@router.post("/issues")
async def create_issue(
    body: CreateIssueBody,
    ctx: TeamsContext = Depends(_ctx),
):
    """Create an issue."""
    return await _agents._admin().create_issue(
        company_id=ctx.company_id,
        body=body.model_dump(exclude_none=True),
        session_cookie=ctx.session_cookie,
    )


@router.patch("/issues/{issue_id}")
async def patch_issue(
    issue_id: str,
    body: PatchIssueBody,
    ctx: TeamsContext = Depends(_ctx),
):
    """Patch an issue."""
    return await _agents._admin().patch_issue(
        issue_id=issue_id,
        body=body.model_dump(exclude_none=True),
        session_cookie=ctx.session_cookie,
    )
