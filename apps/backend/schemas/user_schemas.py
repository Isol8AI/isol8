"""Pydantic response schemas for user endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class SyncUserRequest(BaseModel):
    """Optional body for POST /users/sync.

    The frontend onboarding wizard (Plan 3 Task 11) calls /users/sync
    after the user picks a provider card. The body fields are all
    optional so existing callers (ChatLayout mount, settings page) that
    just want idempotent user creation keep working.

    ``provider_choice`` records which signup card was selected; the
    gateway branches on it (Plan 3 Tasks 4 + 5) to decide whether to
    gate chat on credits and whether to deduct on ``chat.final``.

    ``byo_provider`` is only meaningful when
    ``provider_choice == "byo_key"`` -- it identifies which key was
    saved. The endpoint enforces this invariant.
    """

    provider_choice: Literal["chatgpt_oauth", "byo_key", "bedrock_claude"] | None = Field(
        default=None,
        description="Which signup card the user picked.",
    )
    byo_provider: Literal["openai", "anthropic"] | None = Field(
        default=None,
        description="Which BYO key was saved. Required when provider_choice='byo_key'.",
    )


class SyncUserResponse(BaseModel):
    """Response from POST /users/sync."""

    status: str = Field(..., description="'created' or 'exists'")
    user_id: str = Field(..., description="Clerk user ID")


class UserPublicKeyResponse(BaseModel):
    """Response from GET /users/{user_id}/public-key."""

    user_id: str = Field(..., description="Clerk user ID")
    public_key: str = Field(..., description="X25519 public key (32 bytes hex)")


class CreateKeysResponse(BaseModel):
    """Response from POST /users/me/keys."""

    status: str = Field(..., description="'created'")
    public_key: str = Field(..., description="X25519 public key (32 bytes hex)")
