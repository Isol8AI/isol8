"""User API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user, AuthContext
from core.repositories import user_repo
from schemas.user_schemas import SyncUserRequest, SyncUserResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/sync",
    response_model=SyncUserResponse,
    summary="Sync user from Clerk",
    description="Creates or returns the user record based on the authenticated Clerk user. Idempotent.",
    operation_id="sync_user",
    responses={
        400: {"description": "Invalid provider_choice / byo_provider combination"},
        401: {"description": "Missing or invalid Clerk JWT token"},
        500: {"description": "Database error"},
    },
)
async def sync_user(
    body: SyncUserRequest | None = None,
    auth: AuthContext = Depends(get_current_user),
):
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

    # Plan 3 Task 3: persist provider_choice (+ byo_provider when applicable)
    # so the gateway can branch on it. The body is fully optional -- legacy
    # callers (ChatLayout mount before Plan 3 onboarding ran) just get a
    # plain user-record sync.
    if body is not None and body.provider_choice is not None:
        if body.provider_choice == "byo_key" and body.byo_provider is None:
            raise HTTPException(
                status_code=400,
                detail="byo_provider is required when provider_choice is 'byo_key'",
            )
        try:
            await user_repo.set_provider_choice(
                user_id,
                provider_choice=body.provider_choice,
                byo_provider=body.byo_provider,
            )
        except Exception as e:
            logger.error("Database error persisting provider_choice for %s: %s", user_id, e)
            raise HTTPException(status_code=500, detail="Database operation failed")

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


@router.get(
    "/me",
    summary="Get the authenticated user's record",
    description=(
        "Returns the user's persisted fields needed by the frontend "
        "(provider_choice, byo_provider). Used by the LLMPanel settings "
        "page to render the correct provider section."
    ),
    operation_id="get_me",
    responses={401: {"description": "Missing or invalid Clerk JWT token"}},
)
async def get_me(auth: AuthContext = Depends(get_current_user)) -> dict:
    user = await user_repo.get(auth.user_id)
    if not user:
        # Frontend treats absent record as "not yet synced" — return an
        # empty shape so the panel's Loading state can resolve cleanly.
        return {
            "user_id": auth.user_id,
            "provider_choice": None,
            "byo_provider": None,
        }
    return {
        "user_id": auth.user_id,
        "provider_choice": user.get("provider_choice"),
        "byo_provider": user.get("byo_provider"),
    }
