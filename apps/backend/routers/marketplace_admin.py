"""Admin moderation endpoints — approve, reject, takedown."""

from typing import Annotated

import boto3
from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth import AuthContext, require_platform_admin
from core.config import settings
from core.services import marketplace_service, takedown_service
from core.services.admin_audit import audit_admin_action


router = APIRouter(prefix="/api/v1/admin/marketplace", tags=["marketplace-admin"])


@router.get("/listings")
@audit_admin_action(
    "marketplace.list_review_queue",
    target_user_id_override="__marketplace__",
)
async def review_queue(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
):
    table = boto3.resource("dynamodb").Table(settings.MARKETPLACE_LISTINGS_TABLE)
    resp = table.query(
        IndexName="status-published-index",
        KeyConditionExpression="#s = :review",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":review": "review"},
        Limit=50,
    )
    return {"items": resp.get("Items", [])}


@router.post("/listings/{listing_id}/approve")
@audit_admin_action(
    "marketplace.approve",
    target_user_id_override="__marketplace__",
    capture_params=["listing_id"],
)
async def approve(
    listing_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
):
    try:
        return await marketplace_service.approve(listing_id=listing_id, version=1, approved_by=auth.user_id)
    except marketplace_service.InvalidStateError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/listings/{listing_id}/reject")
@audit_admin_action(
    "marketplace.reject",
    target_user_id_override="__marketplace__",
    capture_params=["listing_id", "notes"],
)
async def reject(
    listing_id: str,
    notes: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
):
    return await marketplace_service.reject(listing_id=listing_id, version=1, notes=notes, rejected_by=auth.user_id)


@router.post("/takedowns/{listing_id}")
@audit_admin_action(
    "marketplace.takedown",
    target_user_id_override="__marketplace__",
    capture_params=["listing_id", "takedown_id"],
)
async def takedown(
    listing_id: str,
    takedown_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
):
    await takedown_service.execute_full_takedown(
        listing_id=listing_id, takedown_id=takedown_id, decided_by=auth.user_id
    )
    return {"status": "taken_down"}
