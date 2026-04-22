"""Admin dashboard router — /api/v1/admin/*

Every endpoint is gated by Depends(require_platform_admin) (CEO #351).
Mutation endpoints are wrapped with @audit_admin_action so a row lands
in DDB synchronously (CEO S1 fail-closed). Container + billing actions
also accept an Idempotency-Key header (CEO D1) to short-circuit double
clicks.

Read endpoints delegate to admin_service (Phase B composition layer).
Mutation endpoints call the underlying service (ecs_manager,
billing_service, clerk_admin, gateway_pool, config_patcher) directly —
admin_service intentionally doesn't compose those because each is a
distinct side-effect.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.auth import AuthContext, require_platform_admin
from core.containers import get_ecs_manager, get_gateway_pool
from core.repositories import admin_actions_repo  # noqa: F401 — patch target for tests
from core.services import (
    admin_service,
    billing_service,
    clerk_admin,
    system_health,
)
from core.services.admin_audit import audit_admin_action
from core.services.config_patcher import patch_openclaw_config
from core.services.idempotency import idempotency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class ResizeRequest(BaseModel):
    tier: str = Field(..., description="New plan tier (e.g. 'starter', 'pro', 'enterprise')")


class IssueCreditRequest(BaseModel):
    amount_cents: int = Field(..., gt=0, description="Credit amount in cents")
    reason: str = Field(..., min_length=1, description="Reason for credit (audited)")


class MarkInvoiceResolvedRequest(BaseModel):
    invoice_id: str = Field(..., description="Stripe invoice id")


class ConfigPatchRequest(BaseModel):
    patch: dict = Field(..., description="Config patch to deep-merge into openclaw.json")


# ---------------------------------------------------------------------------
# Auth + system
# ---------------------------------------------------------------------------


@router.get("/me")
async def admin_me(auth: AuthContext = Depends(require_platform_admin)):
    return {"user_id": auth.user_id, "email": auth.email, "is_admin": True}


@router.get("/system/health")
async def admin_system_health(auth: AuthContext = Depends(require_platform_admin)):
    return await system_health.get_system_health()


@router.get("/actions")
async def admin_actions_audit(
    target_user_id: str | None = Query(None),
    admin_user_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    cursor: str | None = Query(None),
    auth: AuthContext = Depends(require_platform_admin),
):
    try:
        return await admin_service.get_actions_audit(
            target_user_id=target_user_id,
            admin_user_id=admin_user_id,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# User directory + per-user reads
# ---------------------------------------------------------------------------


@router.get("/users")
async def admin_list_users(
    q: str = Query(""),
    plan_tier: str | None = Query(None),
    container_status: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(50, le=200),
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.list_users(q=q, limit=limit, cursor=cursor)


@router.get("/users/{user_id}/overview")
async def admin_user_overview(
    user_id: str,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.get_overview(user_id)


@router.get("/users/{user_id}/agents")
async def admin_user_agents(
    user_id: str,
    cursor: str | None = Query(None),
    limit: int = Query(50, le=200),
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.list_user_agents(user_id, cursor=cursor, limit=limit)


@router.get("/users/{user_id}/agents/{agent_id}")
async def admin_agent_detail(
    user_id: str,
    agent_id: str,
    auth: AuthContext = Depends(require_platform_admin),
):
    result = await admin_service.get_agent_detail(user_id, agent_id)
    if isinstance(result, dict) and result.get("error") == "container_not_running":
        raise HTTPException(status_code=409, detail=result)
    return result


@router.get("/users/{user_id}/posthog")
async def admin_user_posthog(
    user_id: str,
    limit: int = Query(100, le=500),
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.get_posthog_timeline(user_id, limit=limit)


@router.get("/users/{user_id}/logs")
async def admin_user_logs(
    user_id: str,
    level: str = Query("ERROR"),
    hours: int = Query(24, le=168),
    limit: int = Query(20, le=100),
    cursor: str | None = Query(None),
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.get_logs(user_id, level=level, hours=hours, limit=limit, cursor=cursor)


@router.get("/users/{user_id}/cloudwatch-url")
async def admin_user_cloudwatch_url(
    user_id: str,
    start: str = Query(...),
    end: str = Query(...),
    level: str = Query("ERROR"),
    auth: AuthContext = Depends(require_platform_admin),
):
    return {"url": admin_service.get_cloudwatch_url(user_id, start=start, end=end, level=level)}


# ---------------------------------------------------------------------------
# Container actions (D1 idempotency)
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/container/reprovision")
@idempotency()
@audit_admin_action("container.reprovision")
async def admin_container_reprovision(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    ecs = get_ecs_manager()
    return await ecs.reprovision_for_user(user_id)


@router.post("/users/{user_id}/container/stop")
@idempotency()
@audit_admin_action("container.stop")
async def admin_container_stop(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    ecs = get_ecs_manager()
    return await ecs.stop_user_service(user_id)


@router.post("/users/{user_id}/container/start")
@idempotency()
@audit_admin_action("container.start")
async def admin_container_start(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    ecs = get_ecs_manager()
    return await ecs.start_user_service(user_id)


@router.post("/users/{user_id}/container/resize")
@idempotency()
@audit_admin_action("container.resize")
async def admin_container_resize(
    user_id: str,
    body: ResizeRequest,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    ecs = get_ecs_manager()
    return await ecs.resize_for_user(user_id, body.tier)


# ---------------------------------------------------------------------------
# Billing actions
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/billing/cancel-subscription")
@idempotency()
@audit_admin_action("billing.cancel_subscription")
async def admin_billing_cancel_subscription(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await billing_service.cancel_subscription_for_owner(user_id)


@router.post("/users/{user_id}/billing/pause-subscription")
@idempotency()
@audit_admin_action("billing.pause_subscription")
async def admin_billing_pause_subscription(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await billing_service.pause_subscription_for_owner(user_id)


@router.post("/users/{user_id}/billing/issue-credit")
@idempotency()
@audit_admin_action("billing.issue_credit")
async def admin_billing_issue_credit(
    user_id: str,
    body: IssueCreditRequest,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await billing_service.issue_credit_for_owner(user_id, amount_cents=body.amount_cents, reason=body.reason)


@router.post("/users/{user_id}/billing/mark-invoice-resolved")
@idempotency()
@audit_admin_action("billing.mark_invoice_resolved")
async def admin_billing_mark_invoice_resolved(
    user_id: str,
    body: MarkInvoiceResolvedRequest,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await billing_service.mark_invoice_resolved(user_id, body.invoice_id)


# ---------------------------------------------------------------------------
# Account actions (Clerk)
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/account/suspend")
@audit_admin_action("account.suspend")
async def admin_account_suspend(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await clerk_admin.ban_user(user_id)


@router.post("/users/{user_id}/account/reactivate")
@audit_admin_action("account.reactivate")
async def admin_account_reactivate(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await clerk_admin.unban_user(user_id)


@router.post("/users/{user_id}/account/force-signout")
@audit_admin_action("account.force_signout")
async def admin_account_force_signout(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await clerk_admin.revoke_sessions(user_id)


@router.post("/users/{user_id}/account/resend-verification")
@audit_admin_action("account.resend_verification")
async def admin_account_resend_verification(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await clerk_admin.resend_verification(user_id)


# ---------------------------------------------------------------------------
# Config + agent actions
# ---------------------------------------------------------------------------


@router.patch("/users/{user_id}/config")
@audit_admin_action("config.patch", redact_paths=["patch"])
async def admin_config_patch(
    user_id: str,
    body: ConfigPatchRequest,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    await patch_openclaw_config(owner_id=user_id, patch=body.patch)
    return {"status": "patched"}


@router.post("/users/{user_id}/agents/{agent_id}/delete")
@audit_admin_action("agent.delete")
async def admin_agent_delete(
    user_id: str,
    agent_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    pool = get_gateway_pool()
    ecs = get_ecs_manager()
    container, ip = await ecs.resolve_running_container(user_id)
    if not container or not ip:
        raise HTTPException(status_code=409, detail="container_not_running")
    return await pool.send_rpc(
        user_id=user_id,
        req_id=f"admin-agent-delete-{agent_id}",
        method="agents.delete",
        params={"agent_id": agent_id},
        ip=ip,
        token=container["gateway_token"],
    )


@router.post("/users/{user_id}/agents/{agent_id}/clear-sessions")
@audit_admin_action("agent.clear_sessions")
async def admin_agent_clear_sessions(
    user_id: str,
    agent_id: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    pool = get_gateway_pool()
    ecs = get_ecs_manager()
    container, ip = await ecs.resolve_running_container(user_id)
    if not container or not ip:
        raise HTTPException(status_code=409, detail="container_not_running")
    return await pool.send_rpc(
        user_id=user_id,
        req_id=f"admin-agent-clear-{agent_id}",
        method="sessions.clear",
        params={"agent_id": agent_id},
        ip=ip,
        token=container["gateway_token"],
    )
