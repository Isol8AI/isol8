"""Shared FastAPI dependencies for common patterns."""

from fastapi import Depends, HTTPException

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.containers import get_ecs_manager


async def get_running_container(
    auth: AuthContext = Depends(get_current_user),
) -> tuple[dict, str]:
    """Resolve the authenticated user's running container and IP.

    Returns (container_dict, ip_address). Raises 404 if no running container.
    """
    owner_id = resolve_owner_id(auth)
    ecs_manager = get_ecs_manager()
    container, ip = await ecs_manager.resolve_running_container(owner_id)
    if not container or not ip:
        raise HTTPException(status_code=404, detail="No running container")
    return container, ip
