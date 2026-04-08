"""Channel management router.

Exposes:
- GET /links/me — list caller's channel link status across bots
- POST /link/{provider}/complete — member self-link flow
- DELETE /link/{provider}/{agent_id} — member self-unlink
- DELETE /{provider}/{agent_id} — admin bot delete
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import (
    AuthContext,
    get_current_user,
    require_org_admin,
    resolve_owner_id,
)
from core.containers.config import read_openclaw_config_from_efs
from core.repositories import channel_link_repo
from core.services import channel_link_service
from core.services.config_patcher import (
    delete_openclaw_config_path,
    remove_from_openclaw_config_list,
)

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


@router.get("/links/me", summary="List the caller's channel link status across all bots")
async def get_links_me(auth: AuthContext = Depends(get_current_user)):
    owner_id = resolve_owner_id(auth)
    member_id = auth.user_id

    config = await read_openclaw_config_from_efs(owner_id) or {}
    channels_cfg = config.get("channels", {}) if isinstance(config, dict) else {}

    # Look up all link rows for this member
    all_member_links = await channel_link_repo.query_by_member(member_id)
    links_for_owner = {
        (link["provider"], link["agent_id"]): link for link in all_member_links if link.get("owner_id") == owner_id
    }

    can_create_bots = (not auth.is_org_context) or auth.is_org_admin
    result: dict = {"can_create_bots": can_create_bots}
    for provider in ("telegram", "discord", "slack"):
        provider_cfg = channels_cfg.get(provider, {}) if isinstance(channels_cfg, dict) else {}
        accounts = provider_cfg.get("accounts", {}) if isinstance(provider_cfg, dict) else {}
        bots = []
        if isinstance(accounts, dict):
            for agent_id in accounts.keys():
                linked = (provider, agent_id) in links_for_owner
                bots.append(
                    {
                        "agent_id": agent_id,
                        "bot_username": agent_id,  # placeholder; live name comes from channels.status later
                        "linked": linked,
                    }
                )
        result[provider] = bots
    return result


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
    member_id = auth.user_id

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
    summary="Unlink the caller's identity from a bot",
)
async def link_delete(
    provider: str,
    agent_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    owner_id = resolve_owner_id(auth)
    member_id = auth.user_id

    # Find the member's own row for this bot
    member_rows = await channel_link_repo.query_by_member(member_id)
    match = next(
        (
            row
            for row in member_rows
            if row.get("owner_id") == owner_id and row.get("provider") == provider and row.get("agent_id") == agent_id
        ),
        None,
    )
    if match is None:
        return {"status": "not_linked"}

    peer_id = match["peer_id"]

    await remove_from_openclaw_config_list(
        owner_id,
        ["channels", provider, "accounts", agent_id, "allowFrom"],
        predicate=lambda v: v == peer_id,
    )
    await channel_link_repo.delete(
        owner_id=owner_id,
        provider=provider,
        agent_id=agent_id,
        peer_id=peer_id,
    )
    return {"status": "unlinked"}


@router.delete(
    "/{provider}/{agent_id}",
    summary="Admin: delete a bot from an agent entirely",
)
async def admin_delete_bot(
    provider: str,
    agent_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_provider(provider)
    require_org_admin(auth)
    owner_id = resolve_owner_id(auth)

    # Remove the account block
    await delete_openclaw_config_path(
        owner_id,
        ["channels", provider, "accounts", agent_id],
    )
    # Remove the binding that routes this (provider, accountId) to the agent
    await remove_from_openclaw_config_list(
        owner_id,
        ["bindings"],
        predicate=lambda b: (
            isinstance(b, dict)
            and b.get("match", {}).get("channel") == provider
            and b.get("match", {}).get("accountId") == agent_id
        ),
    )
    # Sweep channel-link rows for this bot
    count = await channel_link_repo.sweep_by_owner_provider_agent(
        owner_id=owner_id,
        provider=provider,
        agent_id=agent_id,
    )
    logger.info(
        "Admin %s deleted %s bot for agent %s in owner %s (swept %d links)",
        auth.user_id,
        provider,
        agent_id,
        owner_id,
        count,
    )
    return {"status": "deleted", "links_swept": count}
