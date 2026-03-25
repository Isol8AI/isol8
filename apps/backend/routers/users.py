"""User API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user, AuthContext, resolve_owner_id, get_owner_type
from core.repositories import user_repo
from core.services.billing_service import BillingService
from schemas.user_schemas import SyncUserResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/sync",
    response_model=SyncUserResponse,
    summary="Sync user from Clerk",
    description="Creates or returns the user record based on the authenticated Clerk user. Idempotent.",
    operation_id="sync_user",
    responses={
        401: {"description": "Missing or invalid Clerk JWT token"},
        500: {"description": "Database error"},
    },
)
async def sync_user(auth: AuthContext = Depends(get_current_user)):
    user_id = auth.user_id

    existing = await user_repo.get(user_id)

    if not existing:
        try:
            await user_repo.put(user_id)
            status = "created"
        except Exception as e:
            logger.error("Database error on user sync for %s: %s", user_id, e)
            raise HTTPException(status_code=500, detail="Database operation failed")
    else:
        status = "exists"

    # Ensure billing account exists (idempotent — covers users created before billing)
    try:
        billing = BillingService()
        owner_id = resolve_owner_id(auth)
        owner_type = get_owner_type(auth)
        await billing.create_customer_for_owner(
            owner_id=owner_id,
            owner_type=owner_type,
        )
    except Exception as e:
        logger.warning("Failed to ensure billing account for user %s: %s", user_id, e)

    return {"status": status, "user_id": user_id}
