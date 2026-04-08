"""Channel management router.

Exposes:
- POST /link/{provider}/complete — member self-link flow
- DELETE /link/{provider}/{agent_id} — member self-unlink
- DELETE /{provider}/{agent_id} — admin bot delete
- GET /links/me — list caller's channel link status across bots

The old configure endpoints (POST /telegram, POST /discord, WhatsApp
pairing) are removed — bot configuration now goes through PATCH /api/v1/config.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel  # noqa: F401  (used by E2/E3)

from core.auth import (
    AuthContext,
    get_current_user,
    require_org_admin,
    resolve_owner_id,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_PROVIDERS = {"telegram", "discord", "slack"}


def _validate_provider(provider: str) -> str:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
    return provider


@router.delete(
    "/link/{provider}/{agent_id}",
    summary="Member self-unlink (stub — filled in by E3)",
)
async def link_delete_stub(
    provider: str,
    agent_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    # Full implementation arrives in Task E3
    raise HTTPException(status_code=501, detail="not_yet_implemented")


@router.delete(
    "/{provider}/{agent_id}",
    summary="Admin: delete a bot from an agent (stub — filled in by E3)",
)
async def admin_delete_bot_stub(
    provider: str,
    agent_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    require_org_admin(auth)
    resolve_owner_id(auth)
    # Full implementation arrives in Task E3
    raise HTTPException(status_code=501, detail="not_yet_implemented")
