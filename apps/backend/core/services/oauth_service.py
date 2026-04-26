"""ChatGPT OAuth — device-code flow orchestration.

We use the public Codex CLI client_id verified at
https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/utils/oauth/openai-codex.ts
The device-code endpoint is officially supported by OpenAI per
https://developers.openai.com/codex/auth.

We do NOT install @mariozechner/pi-ai — that's a CLI library that writes
tokens to ~/.codex/auth.json (single-file pattern, would clobber on a
shared backend). We borrow only the constants here and orchestrate the
device-code flow ourselves with isolated per-user storage in DDB.

Per spec §5.1 + §5.1.1.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Final

import boto3
import httpx
from cryptography.fernet import Fernet

from core.config import settings


logger = logging.getLogger(__name__)


# Constants borrowed from pi-ai (see module docstring).
CLIENT_ID: Final = "app_EMoamEEZ73f0CkXaXp7hrann"
DEVICE_CODE_URL: Final = "https://auth.openai.com/codex/device"
TOKEN_URL: Final = "https://auth.openai.com/oauth/token"
SCOPE: Final = "openid profile email offline_access"


@dataclass(frozen=True)
class DeviceCodeResponse:
    """User-facing fields shown in our UI to drive completion.

    Note: the server-side `device_code` is intentionally NOT exposed —
    it stays in DDB and is only used by `poll_device_code` server-side.
    """

    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass(frozen=True)
class DevicePollResult:
    """Returned on successful poll. Tokens are persisted internally;
    callers receive only an opaque marker that auth completed."""

    account_id: str | None


# Sentinel returned while OpenAI says "still pending".
DevicePollPending: Final = object()


def _table():
    table_name = os.environ.get("OAUTH_TOKENS_TABLE") or settings.OAUTH_TOKENS_TABLE
    if not table_name:
        raise RuntimeError("OAUTH_TOKENS_TABLE is empty — backend is misconfigured.")
    return boto3.resource("dynamodb", region_name=settings.AWS_REGION).Table(table_name)


def _fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY") or settings.ENCRYPTION_KEY
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is empty — backend is misconfigured.")
    return Fernet(key.encode() if isinstance(key, str) else key)


async def request_device_code(*, user_id: str) -> DeviceCodeResponse:
    """Start a device-code session for this user. Persists the device_code
    in DDB so the subsequent poll knows what to ask OpenAI about.

    Each call is independent — many users can have device-code sessions
    in flight concurrently against the same client_id (per spec §5.1).
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            DEVICE_CODE_URL,
            data={"client_id": CLIENT_ID, "scope": SCOPE},
        )
    resp.raise_for_status()
    body = resp.json()

    _table().put_item(
        Item={
            "user_id": user_id,
            "state": "pending",
            "device_code": body["device_code"],
            "user_code": body["user_code"],
            "interval": int(body.get("interval", 5)),
        }
    )
    return DeviceCodeResponse(
        user_code=body["user_code"],
        verification_uri=body["verification_uri"],
        expires_in=int(body["expires_in"]),
        interval=int(body.get("interval", 5)),
    )


async def poll_device_code(*, user_id: str) -> DevicePollResult | object:
    """Poll OpenAI's token endpoint for this user's device-code session.

    Returns DevicePollPending while OpenAI says authorization_pending.
    Returns DevicePollResult on success, after Fernet-encrypting the
    tokens into DDB. Raises if the session is unknown / expired / errored.
    """
    row = _table().get_item(Key={"user_id": user_id}).get("Item")
    if not row or row.get("state") not in ("pending",):
        raise RuntimeError(f"No pending device-code session for user {user_id}")

    device_code = row["device_code"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": CLIENT_ID,
                "device_code": device_code,
            },
        )

    if resp.status_code == 400:
        err = resp.json().get("error")
        if err == "authorization_pending":
            return DevicePollPending
        if err == "slow_down":
            # Per OAuth device-code spec — caller should back off; we
            # treat as pending. Optional: bump interval in DDB.
            return DevicePollPending
        raise RuntimeError(f"OpenAI device-code poll failed: {err}")
    resp.raise_for_status()

    body = resp.json()
    tokens_plain = json.dumps(
        {
            "access_token": body["access_token"],
            "refresh_token": body["refresh_token"],
            "id_token": body.get("id_token"),
            "account_id": body.get("account_id"),
        }
    ).encode()
    encrypted = _fernet().encrypt(tokens_plain)

    _table().update_item(
        Key={"user_id": user_id},
        UpdateExpression=("SET #s = :ok, encrypted_tokens = :tok, account_id = :acc REMOVE device_code, user_code, #i"),
        ExpressionAttributeNames={"#s": "state", "#i": "interval"},
        ExpressionAttributeValues={
            ":ok": "active",
            ":tok": encrypted,
            ":acc": body.get("account_id") or "",
        },
    )
    return DevicePollResult(account_id=body.get("account_id"))


async def get_decrypted_tokens(*, user_id: str) -> dict | None:
    """Decrypt and return the user's stored OAuth tokens. None if no row."""
    row = _table().get_item(Key={"user_id": user_id}).get("Item")
    if not row or row.get("state") != "active":
        return None
    plain = _fernet().decrypt(bytes(row["encrypted_tokens"]))
    return json.loads(plain.decode())


async def revoke_user_oauth(*, user_id: str) -> None:
    """Delete the user's OAuth row. Caller is responsible for also
    deleting any pre-staged auth file on EFS (see workspace.py)."""
    _table().delete_item(Key={"user_id": user_id})
