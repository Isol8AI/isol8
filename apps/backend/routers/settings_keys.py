"""Router for BYOK API key management."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user, require_org_admin, resolve_owner_id
from core.services.key_service import (
    SUPPORTED_LLM_PROVIDERS,
    SUPPORTED_TOOLS,
    KeyService,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Union of tool keys (Perplexity/Firecrawl/etc.) and LLM provider keys
# (OpenAI/Anthropic). Both shapes go through this router; the service layer
# decides whether to mirror into Secrets Manager.
ALLOWED_KEY_IDS = set(SUPPORTED_TOOLS.keys()) | set(SUPPORTED_LLM_PROVIDERS.keys())


class SetKeyRequest(BaseModel):
    api_key: str


@router.get("")
async def list_keys(
    auth: AuthContext = Depends(get_current_user),
):
    """List configured API keys (no values exposed)."""
    owner_id = resolve_owner_id(auth)
    service = KeyService()
    keys = await service.list_keys(owner_id)
    return {
        "keys": keys,
        # Tool keys remain under the legacy field name so the existing UI
        # surface keeps working; LLM providers are exposed under their own
        # field so callers can render them as a separate group.
        "supported_tools": list(SUPPORTED_TOOLS.keys()),
        "supported_llm_providers": list(SUPPORTED_LLM_PROVIDERS.keys()),
    }


@router.put("/{tool_id}")
async def set_key(
    tool_id: str,
    body: SetKeyRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Store an API key for a tool."""
    owner_id = resolve_owner_id(auth)
    if auth.is_org_context:
        require_org_admin(auth)
    if tool_id not in ALLOWED_KEY_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported tool: {tool_id}")

    service = KeyService()
    await service.set_key(owner_id, tool_id, body.api_key)

    # TODO: update openclaw.json on EFS + send config.apply RPC
    return {"status": "ok", "tool_id": tool_id}


@router.delete("/{tool_id}")
async def delete_key(
    tool_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    """Remove an API key. The tool becomes unavailable until a new key is added."""
    owner_id = resolve_owner_id(auth)
    if auth.is_org_context:
        require_org_admin(auth)
    if tool_id not in ALLOWED_KEY_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported tool: {tool_id}")

    service = KeyService()
    deleted = await service.delete_key(owner_id, tool_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Key not found")

    return {"status": "ok", "tool_id": tool_id}
