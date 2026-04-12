"""
Dev-only container provisioning endpoints.

Bypasses Stripe for local testing — disabled in production.
"""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthContext, get_current_user, get_owner_type, require_org_admin, resolve_owner_id
from core.config import settings, TIER_CONFIG
from core.observability.metrics import put_metric
from core.containers import get_ecs_manager
from core.containers.ecs_manager import EcsManagerError
from core.repositories import container_repo

logger = logging.getLogger(__name__)

router = APIRouter()


async def require_non_production() -> None:
    """Dependency that blocks access in production environments."""
    if settings.ENVIRONMENT == "prod":
        put_metric("debug.endpoint.prod_hit", dimensions={"endpoint": "debug"})
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
    owner_id = resolve_owner_id(auth)
    owner_type = get_owner_type(auth)

    # Check for existing service
    existing = await container_repo.get_by_owner_id(owner_id)
    if existing and existing.get("status") in ("running", "provisioning"):
        return {
            "status": "already_running",
            "service_name": existing.get("service_name"),
            "owner_id": owner_id,
            "owner_type": owner_type,
        }

    try:
        gateway_token = secrets.token_urlsafe(32)
        ecs_manager = get_ecs_manager()

        # Step 1: Create ECS service (desiredCount=0) — creates access
        # point and EFS dir, but does NOT start the container yet.
        service_name = await ecs_manager.create_user_service(owner_id, gateway_token)

        # Step 2: Write all configs to EFS before the container boots. This
        # is the single source of truth for per-container files — it writes
        # openclaw.json, .mcporter/mcporter.json, the node device PEM, and
        # the combined devices/paired.json (with BOTH the node and the
        # operator device entries, KMS-encrypted operator seed persisted to
        # the DynamoDB containers row).
        await ecs_manager.write_user_configs(owner_id, gateway_token, tier="starter")

        # Step 3: Now start the container — configs are on EFS.
        await ecs_manager.start_user_service(owner_id)

        return {
            "status": "provisioned",
            "service_name": service_name,
            "owner_id": owner_id,
            "owner_type": owner_type,
        }
    except EcsManagerError as e:
        logger.error("Dev provision failed for owner %s: %s", owner_id, e)
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
    owner_id = resolve_owner_id(auth)
    owner_type = get_owner_type(auth)

    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")

    try:
        # Look up billing tier for this owner
        from core.repositories import billing_repo

        account = await billing_repo.get_by_owner_id(owner_id)
        tier = account.get("plan_tier", "free") if account else "free"
        tier_cfg = TIER_CONFIG.get(tier, TIER_CONFIG["free"])

        # Deep-merge only the fields we control (preserves OpenClaw's runtime additions)
        from core.services.config_patcher import patch_openclaw_config, ConfigPatchError
        from core.containers.config import _models_for_tier

        patch = {
            "models": {
                "providers": {
                    "amazon-bedrock": {
                        "baseUrl": f"https://bedrock-runtime.{settings.AWS_REGION}.amazonaws.com",
                        "api": "bedrock-converse-stream",
                        "auth": "aws-sdk",
                        "models": _models_for_tier(tier),
                    },
                },
            },
            "agents": {
                "defaults": {
                    "model": {"primary": tier_cfg["primary_model"]},
                    "models": tier_cfg.get("model_aliases", {}),
                },
            },
        }

        ecs_manager = get_ecs_manager()
        try:
            await patch_openclaw_config(owner_id, patch)
        except ConfigPatchError:
            # No existing config — fall back to full write (first provision).
            # write_user_configs handles openclaw.json + mcporter.json + node
            # device PEM + combined devices/paired.json (node + operator),
            # and persists the KMS-encrypted operator seed to DynamoDB.
            await ecs_manager.write_user_configs(owner_id, container["gateway_token"], tier=tier)
        else:
            # Patch succeeded — openclaw.json was updated in place via deep
            # merge. We still need to ensure device trust store is current
            # (e.g. a newly-added operator entry after the OpenClaw 4.5
            # upgrade), without rewriting openclaw.json.
            await ecs_manager.ensure_device_identities(owner_id, container["gateway_token"])

        await ecs_manager.start_user_service(owner_id)

        return {
            "status": "redeploying",
            "service_name": container["service_name"],
            "owner_id": owner_id,
            "owner_type": owner_type,
            "tier": tier,
        }
    except EcsManagerError as e:
        logger.error("Dev redeploy failed for owner %s: %s", owner_id, e)
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
    owner_id = resolve_owner_id(auth)
    if auth.is_org_context:
        require_org_admin(auth)

    try:
        await get_ecs_manager().delete_user_service(owner_id)
        return {"status": "removed"}
    except EcsManagerError as e:
        logger.error("Dev remove failed for owner %s: %s", owner_id, e)
        raise HTTPException(status_code=503, detail=str(e))
