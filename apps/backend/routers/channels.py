"""Router for messaging channel management.

Thin wrappers that send RPCs to the user's OpenClaw container
for channel configuration (Telegram, Discord, WhatsApp).
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.containers import get_ecs_manager, get_gateway_pool

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_PROVIDERS = {"telegram", "discord", "whatsapp"}


class TelegramConfigRequest(BaseModel):
    bot_token: str


class DiscordConfigRequest(BaseModel):
    bot_token: str
    guild_id: str


async def _send_channel_rpc(user_id: str, method: str, params: dict) -> dict:
    """Send an RPC to the user's container via the gateway pool."""
    pool = get_gateway_pool()
    ecs = get_ecs_manager()
    container, ip = await ecs.resolve_running_container(user_id)
    if not container or not ip:
        raise HTTPException(status_code=404, detail="No running container")
    req_id = str(uuid.uuid4())
    return await pool.send_rpc(user_id, req_id, method, params, ip, container["gateway_token"])


@router.get("")
async def list_channels(auth: AuthContext = Depends(get_current_user)):
    """List connected channels and their status."""
    owner_id = resolve_owner_id(auth)
    try:
        result = await _send_channel_rpc(owner_id, "channels.status", {})
        return {"channels": result}
    except Exception as e:
        logger.warning("Failed to get channel status for %s: %s", owner_id, e)
        return {"channels": []}


@router.post("/telegram")
async def configure_telegram(
    body: TelegramConfigRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Configure Telegram bot channel."""
    owner_id = resolve_owner_id(auth)
    result = await _send_channel_rpc(
        owner_id,
        "channels.configure",
        {"provider": "telegram", "token": body.bot_token},
    )
    return {"status": "ok", "provider": "telegram", "result": result}


@router.post("/discord")
async def configure_discord(
    body: DiscordConfigRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Configure Discord bot channel."""
    owner_id = resolve_owner_id(auth)
    result = await _send_channel_rpc(
        owner_id,
        "channels.configure",
        {
            "provider": "discord",
            "token": body.bot_token,
            "guild_id": body.guild_id,
        },
    )
    return {"status": "ok", "provider": "discord", "result": result}


@router.post("/whatsapp/pair")
async def whatsapp_pair(auth: AuthContext = Depends(get_current_user)):
    """Initiate WhatsApp QR code pairing."""
    owner_id = resolve_owner_id(auth)
    result = await _send_channel_rpc(
        owner_id,
        "channels.whatsapp.pair",
        {},
    )
    return {"status": "pairing", "qr": result.get("qr"), "timeout": 60}


@router.get("/whatsapp/qr")
async def whatsapp_qr(auth: AuthContext = Depends(get_current_user)):
    """Poll for current WhatsApp QR code."""
    owner_id = resolve_owner_id(auth)
    result = await _send_channel_rpc(
        owner_id,
        "channels.whatsapp.qr",
        {},
    )
    return result


@router.delete("/{provider}")
async def disconnect_channel(
    provider: str,
    auth: AuthContext = Depends(get_current_user),
):
    """Disconnect a messaging channel."""
    owner_id = resolve_owner_id(auth)
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    await _send_channel_rpc(
        owner_id,
        "channels.disconnect",
        {"provider": provider},
    )
    return {"status": "ok", "provider": provider}
