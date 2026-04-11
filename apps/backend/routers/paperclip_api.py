"""
Paperclip API proxy router.

Provides status, enable/disable, and proxy endpoints for the Paperclip
sidecar. All requests are authenticated via Clerk and tier-gated to
pro/enterprise users.

The proxy forwards requests to the user's Paperclip container at
http://{container_ip}:3100/api/{path} using the stored Board API Key.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.config import TIER_CONFIG, settings
from core.containers import get_ecs_manager
from core.repositories import container_repo

logger = logging.getLogger(__name__)

router = APIRouter()

_PROXY_TIMEOUT = 30.0


def _check_tier_eligible(tier: str) -> None:
    """Raise 403 if the user's tier doesn't support Paperclip."""
    if not TIER_CONFIG.get(tier, {}).get("paperclip_enabled", False):
        raise HTTPException(status_code=403, detail="Paperclip requires Pro or Enterprise tier")


@router.get("/status")
async def paperclip_status(
    auth: AuthContext = Depends(get_current_user),
):
    """Check if Paperclip is enabled and healthy for the current user/org."""
    owner_id = resolve_owner_id(auth)
    container = await container_repo.get_by_owner_id(owner_id)
    # Org members who aren't admins can view but can't toggle
    can_toggle = not auth.is_org_context or auth.is_org_admin

    if not container:
        return {
            "enabled": False,
            "healthy": False,
            "eligible": False,
            "can_toggle": can_toggle,
        }

    tier = container.get("tier", "free")
    eligible = TIER_CONFIG.get(tier, {}).get("paperclip_enabled", False)
    enabled = container.get("paperclip_enabled", False)

    if not enabled:
        return {
            "enabled": False,
            "healthy": False,
            "eligible": eligible,
            "can_toggle": can_toggle,
        }

    # Check Paperclip health
    healthy = False
    try:
        ecs = get_ecs_manager()
        ip = await ecs.discover_ip(owner_id)
        if ip:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://{ip}:{settings.PAPERCLIP_PORT}/api/health")
                healthy = resp.status_code == 200
    except Exception:
        pass

    return {
        "enabled": True,
        "healthy": healthy,
        "eligible": eligible,
        "can_toggle": can_toggle,
    }


def _require_admin_for_org(auth: AuthContext) -> None:
    """Raise 403 if user is in org context but not an admin."""
    if auth.is_org_context and not auth.is_org_admin:
        raise HTTPException(
            status_code=403,
            detail="Only organization admins can enable or disable Teams",
        )


@router.post("/enable")
async def enable_paperclip(
    auth: AuthContext = Depends(get_current_user),
):
    """Enable Paperclip sidecar for the current user/org."""
    _require_admin_for_org(auth)
    owner_id = resolve_owner_id(auth)
    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")

    tier = container.get("tier", "free")
    _check_tier_eligible(tier)

    if container.get("paperclip_enabled"):
        return {"status": "already_enabled"}

    ecs = get_ecs_manager()
    result = await ecs.enable_paperclip(owner_id)
    return result


@router.post("/disable")
async def disable_paperclip(
    auth: AuthContext = Depends(get_current_user),
):
    """Disable Paperclip sidecar for the current user/org."""
    _require_admin_for_org(auth)
    owner_id = resolve_owner_id(auth)
    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")

    if not container.get("paperclip_enabled"):
        return {"status": "already_disabled"}

    ecs = get_ecs_manager()
    result = await ecs.disable_paperclip(owner_id)
    return result


@router.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_to_paperclip(
    path: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
):
    """Proxy requests to the user's Paperclip container.

    Forwards to http://{container_ip}:3100/api/{path} with the
    stored Board API Key in the Authorization header.
    """
    owner_id = resolve_owner_id(auth)
    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")
    if not container.get("paperclip_enabled"):
        raise HTTPException(status_code=400, detail="Paperclip is not enabled")

    board_key = container.get("paperclip_board_key")
    if not board_key:
        raise HTTPException(status_code=503, detail="Paperclip board key not provisioned yet")

    ecs = get_ecs_manager()
    ip = await ecs.discover_ip(owner_id)
    if not ip:
        raise HTTPException(status_code=502, detail="Cannot resolve container IP")

    upstream_url = f"http://{ip}:{settings.PAPERCLIP_PORT}/api/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    body = await request.body()

    forward_headers: dict[str, str] = {}
    if body:
        content_type = request.headers.get("content-type")
        if content_type:
            forward_headers["content-type"] = content_type

    forward_headers["authorization"] = f"Bearer {board_key}"

    async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=upstream_url,
                content=body if body else None,
                headers=forward_headers,
            )
        except httpx.ConnectError:
            raise HTTPException(status_code=502, detail="Paperclip sidecar not reachable")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Paperclip sidecar timeout")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )
