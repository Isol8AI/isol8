"""
ECS-compatible credential vending endpoint for per-user containers.

Containers on the Docker bridge network cannot reach EC2 IMDS.
This endpoint serves temporary STS credentials in the format
expected by AWS SDK's AWS_CONTAINER_CREDENTIALS_FULL_URI.

The SDK auto-refreshes 5 minutes before expiration.

Security:
- Authenticated by gateway_token (256-bit random, server-side only)
- Returns Bedrock-scoped credentials only
- Hidden from public OpenAPI schema
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import boto3
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from core.config import settings
from core.containers import get_container_manager
from core.containers.manager import ContainerInfo

logger = logging.getLogger(__name__)

router = APIRouter()

_credential_cache: dict[str, "CachedCredentials"] = {}
_REFRESH_MARGIN = timedelta(minutes=10)


@dataclass
class CachedCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime


class EcsCredentialResponse(BaseModel):
    """ECS credential format expected by AWS SDK."""

    AccessKeyId: str
    SecretAccessKey: str
    Token: str
    Expiration: str  # ISO 8601 UTC


def _find_user_by_token(cache: dict[str, ContainerInfo], token: str) -> Optional[str]:
    """Look up user_id by gateway_token. O(n) scan, fine for ~1000 containers."""
    for user_id, info in cache.items():
        if info.gateway_token == token:
            return user_id
    return None


def _get_or_refresh_credentials(user_id: str) -> CachedCredentials:
    """Return cached credentials or call STS AssumeRole."""
    cached = _credential_cache.get(user_id)
    now = datetime.now(timezone.utc)

    if cached and (cached.expiration - now) > _REFRESH_MARGIN:
        return cached

    sts = boto3.client("sts")
    resp = sts.assume_role(
        RoleArn=settings.CONTAINER_EXECUTION_ROLE_ARN,
        RoleSessionName=f"container-{user_id[:32]}",
        DurationSeconds=3600,
    )

    creds = resp["Credentials"]
    result = CachedCredentials(
        access_key_id=creds["AccessKeyId"],
        secret_access_key=creds["SecretAccessKey"],
        session_token=creds["SessionToken"],
        expiration=creds["Expiration"].replace(tzinfo=timezone.utc)
        if creds["Expiration"].tzinfo is None
        else creds["Expiration"],
    )
    _credential_cache[user_id] = result
    logger.debug("Refreshed STS credentials for user=%s, expires=%s", user_id, result.expiration)
    return result


@router.get(
    "/credentials",
    response_model=EcsCredentialResponse,
    include_in_schema=False,
    summary="ECS-compatible credential vending for containers",
)
async def get_container_credentials(
    authorization: Optional[str] = Header(None),
) -> EcsCredentialResponse:
    """Return temporary AWS credentials for the requesting container."""
    if not authorization:
        raise HTTPException(status_code=403, detail="Missing authorization")

    # AWS SDK sends AWS_CONTAINER_AUTHORIZATION_TOKEN as-is, but some
    # SDK versions may prefix with "Bearer ". Strip it for comparison.
    token = authorization
    if token.lower().startswith("bearer "):
        token = token[7:]

    cm = get_container_manager()
    user_id = _find_user_by_token(cm._cache, token)

    if not user_id:
        logger.warning("Credential request with unknown token (first 8: %s...)", authorization[:8])
        raise HTTPException(status_code=403, detail="Invalid token")

    try:
        creds = _get_or_refresh_credentials(user_id)
    except Exception as e:
        logger.error("STS AssumeRole failed for user=%s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Failed to obtain credentials")

    return EcsCredentialResponse(
        AccessKeyId=creds.access_key_id,
        SecretAccessKey=creds.secret_access_key,
        Token=creds.session_token,
        Expiration=creds.expiration.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
