"""
Channel management API for user's OpenClaw container.

Requires a dedicated container — returns 404 for free-tier users.
"""

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user
from core.containers import get_container_manager
from core.containers.manager import ContainerError

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_container(user_id: str) -> int:
    cm = get_container_manager()
    port = cm.get_container_port(user_id)
    if not port:
        raise HTTPException(status_code=404, detail="No container found. Upgrade to a paid plan.")
    return port


def _exec(user_id: str, command: list[str]) -> str:
    cm = get_container_manager()
    try:
        return cm.exec_command(user_id, command)
    except ContainerError as e:
        logger.error("Container exec failed for user %s: %s", user_id, e)
        raise HTTPException(status_code=502, detail="Container command failed")


class ChannelConfig(BaseModel):
    config: Dict[str, Any]


@router.get(
    "",
    summary="List channels",
    description="Lists all communication channels and their status.",
    operation_id="list_channels",
    responses={404: {"description": "No container (free tier)"}},
)
async def list_channels(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "channel", "list", "--json"])
    try:
        channels = json.loads(raw)
    except json.JSONDecodeError:
        channels = []
    return {"channels": channels}


@router.put(
    "/{channel_name}",
    summary="Configure channel",
    description="Updates configuration for a channel.",
    operation_id="configure_channel",
    responses={404: {"description": "No container (free tier)"}},
)
async def configure_channel(
    channel_name: str,
    body: ChannelConfig,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    config_json = json.dumps(body.config)
    _exec(
        auth.user_id,
        [
            "openclaw",
            "channel",
            "configure",
            channel_name,
            "--config",
            config_json,
        ],
    )
    return {"channel": channel_name, "status": "configured"}


@router.post(
    "/{channel_name}/enable",
    summary="Enable channel",
    description="Enables a communication channel.",
    operation_id="enable_channel",
    responses={404: {"description": "No container (free tier)"}},
)
async def enable_channel(
    channel_name: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    _exec(auth.user_id, ["openclaw", "channel", "enable", channel_name])
    return {"channel": channel_name, "enabled": True}


@router.post(
    "/{channel_name}/disable",
    summary="Disable channel",
    description="Disables a communication channel.",
    operation_id="disable_channel",
    responses={404: {"description": "No container (free tier)"}},
)
async def disable_channel(
    channel_name: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    _exec(auth.user_id, ["openclaw", "channel", "disable", channel_name])
    return {"channel": channel_name, "enabled": False}
