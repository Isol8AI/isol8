"""User API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user, AuthContext
from core.repositories import user_repo
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

    # Note: no billing-account creation here. /users/sync fires from multiple
    # places (ChatLayout mount, onboarding, settings), and the caller's JWT
    # may be in a transient personal context while Clerk is mid-activation of
    # an org. Creating a billing row here would produce phantom
    # personal-context rows for users who are actually org members. Billing is
    # created lazily by POST /billing/checkout (the explicit "subscribe" signal)
    # which is also gated on require_org_admin, so only the first admin click
    # through Stripe Checkout ever writes the row.
    #
    # Container provisioning is also handled elsewhere (GET /container/status
    # + ProvisioningStepper) for the same reason.

    return {"status": status, "user_id": user_id}
