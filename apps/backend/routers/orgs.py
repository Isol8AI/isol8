"""Organization management endpoints — invite creation gate (Gate A)."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthContext, get_current_user, require_org_admin
from core.observability.metrics import put_metric
from core.repositories import billing_repo
from core.services import clerk_admin
from core.tenancy_codes import PERSONAL_USER_EXISTS
from schemas.orgs import CreateInvitationRequest, CreateInvitationResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/{org_id}/invitations",
    response_model=CreateInvitationResponse,
    status_code=201,
    summary="Create an org invitation",
    description=(
        "Refuses with 409 if the invitee already has an active or trialing "
        "personal Isol8 subscription. Otherwise forwards to Clerk's "
        "createInvitation API."
    ),
    operation_id="create_org_invitation",
)
async def create_invitation(
    org_id: str,
    body: CreateInvitationRequest,
    auth: AuthContext = Depends(get_current_user),
) -> CreateInvitationResponse:
    # Caller must be an admin of THIS org. require_org_admin only checks
    # the role within the active org; the path-vs-token org_id match
    # closes the cross-org admin escalation gap.
    require_org_admin(auth)
    if auth.org_id != org_id:
        raise HTTPException(403, "Cannot invite to a different org")

    invitee_email = body.email.lower()

    # Tenancy invariant: refuse if invitee has an active personal sub.
    existing = await clerk_admin.find_user_by_email(invitee_email)
    if existing is not None:
        account = await billing_repo.get_by_owner_id(existing["id"])
        if account and account.get("subscription_status") in ("active", "trialing"):
            put_metric("orgs.invitation.blocked", dimensions={"reason": PERSONAL_USER_EXISTS})
            logger.info(
                "orgs.invitation.blocked owner_id=%s personal_status=%s",
                existing["id"],
                account.get("subscription_status"),
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": PERSONAL_USER_EXISTS,
                    # body.email preserves the inviter's typed casing for the
                    # human-readable message; invitee_email (above) is lowercased
                    # for the Clerk lookup itself.
                    "message": (
                        f"{body.email} already has an active personal Isol8 "
                        "subscription. They must cancel it before they can "
                        "be invited to an organization."
                    ),
                },
            )

    try:
        invite = await clerk_admin.create_organization_invitation(
            org_id=org_id,
            email=invitee_email,
            role=body.role,
            inviter_user_id=auth.user_id,
        )
    except HTTPException:
        put_metric("orgs.invitation.failed", dimensions={"reason": "clerk_error"})
        raise
    put_metric("orgs.invitation.created", dimensions={"role": body.role})
    logger.info(
        "orgs.invitation.created org_id=%s invitee=%s role=%s invitation_id=%s",
        org_id,
        invitee_email,
        body.role,
        invite["id"],
    )
    return CreateInvitationResponse(invitation_id=invite["id"])
