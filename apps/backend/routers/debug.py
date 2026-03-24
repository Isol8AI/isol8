"""
Dev-only container provisioning endpoints.

Bypasses Stripe for local testing — disabled in production.
"""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthContext, get_current_user
from core.config import settings
from core.containers import get_ecs_manager, get_workspace
from core.containers.config import write_mcporter_config, write_openclaw_config
from core.containers.ecs_manager import EcsManagerError
from core.repositories import container_repo

logger = logging.getLogger(__name__)

router = APIRouter()


async def require_non_production() -> None:
    """Dependency that blocks access in production environments."""
    if settings.ENVIRONMENT == "prod":
        raise HTTPException(status_code=403, detail="Not available in production")


@router.post(
    "/provision",
    summary="Provision container (dev only)",
    description=(
        "Manually provisions an ECS Fargate service for the authenticated user. "
        "Only available in non-production environments for local testing."
    ),
    operation_id="debug_provision_container",
    dependencies=[Depends(require_non_production)],
    responses={
        403: {"description": "Not available in production"},
        409: {"description": "Container already running"},
        503: {"description": "Provisioning failed"},
    },
)
async def provision_container(
    auth: AuthContext = Depends(get_current_user),
):
    user_id = auth.user_id

    # Check for existing service
    existing = await container_repo.get_by_user_id(user_id)
    if existing and existing.get("status") in ("running", "provisioning"):
        return {
            "status": "already_running",
            "service_name": existing.get("service_name"),
            "user_id": user_id,
        }

    try:
        gateway_token = secrets.token_urlsafe(32)

        # Step 1: Create ECS service (desiredCount=0) — creates access
        # point and EFS dir, but does NOT start the container yet.
        service_name = await get_ecs_manager().create_user_service(user_id, gateway_token)

        # Step 2: Write all configs to EFS before the container boots.
        config_json = write_openclaw_config(
            region=settings.AWS_REGION,
            gateway_token=gateway_token,
            proxy_base_url=settings.PROXY_BASE_URL,
        )
        get_workspace().write_file(user_id, "openclaw.json", config_json)
        get_workspace().write_file(user_id, ".mcporter/mcporter.json", write_mcporter_config())

        # Step 3: Now start the container — configs are on EFS.
        await get_ecs_manager().start_user_service(user_id)

        return {
            "status": "provisioned",
            "service_name": service_name,
            "user_id": user_id,
        }
    except EcsManagerError as e:
        logger.error("Dev provision failed for user %s: %s", user_id, e)
        raise HTTPException(status_code=503, detail=str(e))


@router.patch(
    "/provision",
    summary="Update config and redeploy (dev only)",
    description=(
        "Rewrites openclaw.json with the latest config template and forces "
        "a new ECS deployment so the gateway picks up the changes."
    ),
    operation_id="debug_redeploy_container",
    dependencies=[Depends(require_non_production)],
    responses={
        403: {"description": "Not available in production"},
        404: {"description": "No container found"},
        503: {"description": "Redeploy failed"},
    },
)
async def redeploy_container(
    auth: AuthContext = Depends(get_current_user),
):
    user_id = auth.user_id

    container = await container_repo.get_by_user_id(user_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")

    try:
        config_json = write_openclaw_config(
            region=settings.AWS_REGION,
            gateway_token=container["gateway_token"],
            proxy_base_url=settings.PROXY_BASE_URL,
        )
        get_workspace().write_file(user_id, "openclaw.json", config_json)

        await get_ecs_manager().start_user_service(user_id)

        return {
            "status": "redeploying",
            "service_name": container["service_name"],
            "user_id": user_id,
        }
    except EcsManagerError as e:
        logger.error("Dev redeploy failed for user %s: %s", user_id, e)
        raise HTTPException(status_code=503, detail=str(e))


@router.delete(
    "/provision",
    summary="Remove container (dev only)",
    description="Removes the user's ECS Fargate service. Dev only.",
    operation_id="debug_remove_container",
    dependencies=[Depends(require_non_production)],
    responses={
        403: {"description": "Not available in production"},
        404: {"description": "No container found"},
    },
)
async def remove_container(
    auth: AuthContext = Depends(get_current_user),
):
    user_id = auth.user_id

    try:
        await get_ecs_manager().delete_user_service(user_id)
        return {"status": "removed"}
    except EcsManagerError as e:
        logger.error("Dev remove failed for user %s: %s", user_id, e)
        raise HTTPException(status_code=503, detail=str(e))
