"""Router for BYOK API key management."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user
from core.database import get_session_factory
from core.services.key_service import SUPPORTED_TOOLS, KeyService

logger = logging.getLogger(__name__)
router = APIRouter()


class SetKeyRequest(BaseModel):
    api_key: str


@router.get("")
async def list_keys(auth: AuthContext = Depends(get_current_user)):
    """List configured API keys (no values exposed)."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        service = KeyService(db)
        keys = await service.list_keys(auth.user_id)
        return {"keys": keys, "supported_tools": list(SUPPORTED_TOOLS.keys())}


@router.put("/{tool_id}")
async def set_key(
    tool_id: str,
    body: SetKeyRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Store an API key for a tool."""
    if tool_id not in SUPPORTED_TOOLS:
        raise HTTPException(status_code=400, detail=f"Unsupported tool: {tool_id}")

    session_factory = get_session_factory()
    async with session_factory() as db:
        service = KeyService(db)
        await service.set_key(auth.user_id, tool_id, body.api_key)
        await db.commit()

    # TODO: update openclaw.json on EFS + send config.apply RPC
    return {"status": "ok", "tool_id": tool_id}


@router.delete("/{tool_id}")
async def delete_key(
    tool_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    """Remove an API key and revert to Isol8-provided proxy."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        service = KeyService(db)
        deleted = await service.delete_key(auth.user_id, tool_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Key not found")
        await db.commit()

    # TODO: revert openclaw.json to proxy default + send config.apply RPC
    return {"status": "ok", "tool_id": tool_id}
