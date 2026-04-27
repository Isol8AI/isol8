"""ChatGPT OAuth endpoints.

Per spec §5.1: backend-driven device-code flow. Frontend POSTs /start,
shows the user_code + verification_uri to the user, then polls /poll
until status flips from "pending" to "completed".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthContext, get_current_user
from core.containers.workspace import delete_codex_auth
from core.services.oauth_service import (
    DevicePollPending,
    DevicePollResult,
    OAuthAlreadyActiveError,
    poll_device_code,
    request_device_code,
    revoke_user_oauth,
)


router = APIRouter(prefix="/oauth/chatgpt", tags=["oauth"])


@router.post(
    "/start",
    summary="Begin a ChatGPT OAuth device-code session",
    description=(
        "Returns the user-facing fields needed to complete OAuth in the "
        "browser: user_code (typed at verification_uri) and the polling "
        "interval. Returns 409 if the user already has an active session."
    ),
)
async def start(ctx: AuthContext = Depends(get_current_user)):
    try:
        result = await request_device_code(user_id=ctx.user_id)
    except OAuthAlreadyActiveError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {
        "user_code": result.user_code,
        "verification_uri": result.verification_uri,
        "expires_in": result.expires_in,
        "interval": result.interval,
    }


@router.post(
    "/poll",
    summary="Poll the device-code session for completion",
    description=(
        "Returns {status: 'pending'} until OpenAI accepts the user_code, "
        "then {status: 'completed', account_id: ...}. Frontend should poll "
        "every `interval` seconds (returned by /start)."
    ),
)
async def poll(ctx: AuthContext = Depends(get_current_user)):
    result = await poll_device_code(user_id=ctx.user_id)
    if result is DevicePollPending:
        return {"status": "pending"}
    assert isinstance(result, DevicePollResult)
    return {"status": "completed", "account_id": result.account_id}


@router.post(
    "/disconnect",
    summary="Revoke the user's stored ChatGPT OAuth tokens",
    description=(
        "Deletes the persisted OAuth row AND the EFS-staged Codex auth.json so "
        "the container can no longer use the tokens cold. After this, /start can "
        "be called again to begin a new OAuth session."
    ),
)
async def disconnect(ctx: AuthContext = Depends(get_current_user)):
    await revoke_user_oauth(user_id=ctx.user_id)
    # Also remove the staged auth.json from EFS — without this the container
    # keeps the tokens for the rest of its lifetime even after we revoke the
    # row. Codex P1 on PR #393.
    try:
        await delete_codex_auth(user_id=ctx.user_id)
    except Exception:
        # Best-effort: the row deletion above is the authoritative signal.
        # EFS unlink failures shouldn't 5xx the disconnect.
        pass
    return {"status": "disconnected"}
