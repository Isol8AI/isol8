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
from core.services import channel_link_service

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_PROVIDERS = {"telegram", "discord", "slack"}


def _validate_provider(provider: str) -> str:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
    return provider


class LinkCompleteBody(BaseModel):
    agent_id: str
    code: str


@router.post(
    "/link/{provider}/complete",
    summary="Complete the member-link flow by pasting the pairing code",
)
async def link_complete(
    provider: str,
    body: LinkCompleteBody,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    owner_id = resolve_owner_id(auth)
    member_id = auth.user_id  # always the caller, even in org context

    try:
        result = await channel_link_service.complete_link(
            owner_id=owner_id,
            provider=provider,
            agent_id=body.agent_id,
            code=body.code,
            member_id=member_id,
            linked_via="settings",
        )
    except channel_link_service.PairingCodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except channel_link_service.PeerAlreadyLinkedError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result


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
