"""Pydantic schemas for the organizations API surface."""

from typing import Literal

from pydantic import BaseModel, EmailStr


class CreateInvitationRequest(BaseModel):
    """Body for POST /api/v1/orgs/{org_id}/invitations.

    `role` matches Clerk's role-key convention. Default org members get
    "org:member"; org admins get "org:admin". The frontend invite form
    surfaces a role select that maps to these two strings.
    """

    email: EmailStr
    role: Literal["org:admin", "org:member"] = "org:member"


class CreateInvitationResponse(BaseModel):
    invitation_id: str
