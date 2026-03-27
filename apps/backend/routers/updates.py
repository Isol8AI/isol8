"""Container updates router -- pending updates, apply/schedule, admin creation."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthContext, get_current_user, require_org_admin, resolve_owner_id
from core.repositories import update_repo
from core.services.update_service import apply_update, queue_fleet_image_update

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ApplyRequest(BaseModel):
    schedule: str = Field(
        ...,
        description="When to apply: 'now', 'tonight', or 'remind_later'",
        pattern="^(now|tonight|remind_later)$",
    )


class AdminUpdateRequest(BaseModel):
    owner_id: str = Field(..., description="Owner ID or 'all' for fleet-wide")
    update_type: str = Field(..., description="Type of update (e.g. 'image_update', 'container_resize')")
    description: str = Field(..., description="Human-readable description")
    changes: dict = Field(default_factory=dict, description="Change payload")
    force_by: Optional[str] = Field(default=None, description="ISO timestamp deadline")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/updates",
    summary="Get pending updates",
    description="Returns all pending or scheduled updates for the authenticated owner.",
)
async def get_pending_updates(auth: AuthContext = Depends(get_current_user)):
    owner_id = resolve_owner_id(auth)
    items = await update_repo.get_pending(owner_id)
    return {"updates": items}


@router.post(
    "/updates/{update_id}/apply",
    summary="Apply or schedule an update",
    description="Apply an update immediately, schedule for tonight, or snooze.",
)
async def apply_or_schedule_update(
    update_id: str,
    body: ApplyRequest,
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)

    # Require org admin when in org context
    if auth.is_org_context:
        require_org_admin(auth)

    if body.schedule == "now":
        success = await apply_update(owner_id, update_id)
        if not success:
            raise HTTPException(
                status_code=409, detail="Update could not be applied (already in progress or invalid state)"
            )
        return {"status": "applied", "update_id": update_id}

    elif body.schedule == "tonight":
        # Calculate next 2 AM UTC
        now_utc = datetime.now(timezone.utc)
        tonight_2am = now_utc.replace(hour=2, minute=0, second=0, microsecond=0)
        if tonight_2am <= now_utc:
            tonight_2am += timedelta(days=1)
        scheduled_at = tonight_2am.isoformat()

        success = await update_repo.set_scheduled(owner_id, update_id, scheduled_at)
        if not success:
            raise HTTPException(status_code=409, detail="Update could not be scheduled (invalid state)")
        return {"status": "scheduled", "update_id": update_id, "scheduled_at": scheduled_at}

    else:  # remind_later
        success = await update_repo.set_snoozed(owner_id, update_id)
        if not success:
            raise HTTPException(status_code=409, detail="Update could not be snoozed (not found)")
        return {"status": "snoozed", "update_id": update_id}


@router.post(
    "/updates",
    summary="Admin: create updates",
    description="Create a pending update for a specific owner or all owners (fleet-wide image update).",
)
async def admin_create_update(
    body: AdminUpdateRequest,
    auth: AuthContext = Depends(get_current_user),
):
    # Admin endpoint -- require org admin in org context
    if auth.is_org_context:
        require_org_admin(auth)

    if body.owner_id == "all" and body.update_type == "image_update":
        new_image = body.changes.get("new_image", "")
        if not new_image:
            raise HTTPException(status_code=400, detail="changes.new_image is required for fleet image updates")
        count = await queue_fleet_image_update(new_image, body.description)
        return {"status": "queued", "count": count}

    # Single owner update
    item = await update_repo.create(
        owner_id=body.owner_id,
        update_type=body.update_type,
        description=body.description,
        changes=body.changes,
        force_by=body.force_by,
    )
    return {"status": "created", "update": item}
