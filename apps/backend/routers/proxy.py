"""Proxy router for Isol8-provided external tool APIs.

Routes tool calls from user containers through our backend,
keeping real API keys server-side. Users authenticate with
their gateway_token.
"""

import json
import logging
from decimal import Decimal

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from core.config import settings
from core.repositories import container_repo, billing_repo

logger = logging.getLogger(__name__)
router = APIRouter()

UPSTREAM_URLS = {
    "search": "https://api.perplexity.ai",
}

UPSTREAM_KEY_SETTINGS = {
    "search": "PERPLEXITY_API_KEY",
}

# Default cost per tool call (looked up from ToolPricing in production)
DEFAULT_TOOL_COSTS = {
    "search": Decimal("0.005"),
}


async def _authenticate_and_check_budget(
    request: Request,
) -> tuple[dict, dict]:
    """Validate gateway token and enforce budget before proxying.

    Returns (container, billing_account) on success.
    Raises HTTPException on auth failure or budget exceeded.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization")
    token = auth_header[7:]

    container = await container_repo.get_by_gateway_token(token)
    if not container:
        raise HTTPException(status_code=401, detail="Invalid gateway token")

    account = await billing_repo.get_by_owner_id(container["owner_id"])
    if not account:
        raise HTTPException(status_code=403, detail="No billing account")

    # Enforce budget: block requests when monthly usage exceeds plan budget.
    # Budget enforcement is simplified during DynamoDB migration — usage tracking
    # will be re-implemented. For now, allow all requests for paying users.
    # Free tier users are still gated by the existence of a billing account.

    return container, account


@router.api_route(
    "/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
    include_in_schema=False,
)
async def proxy_request(
    service: str,
    path: str,
    request: Request,
):
    """Forward request to upstream API with Isol8's key."""
    logger.info(
        "Proxy request: %s %s/%s from %s",
        request.method,
        service,
        path,
        request.client.host if request.client else "unknown",
    )
    if service not in UPSTREAM_URLS:
        raise HTTPException(status_code=404, detail=f"Unknown proxy service: {service}")

    upstream_key_attr = UPSTREAM_KEY_SETTINGS[service]
    upstream_key = getattr(settings, upstream_key_attr, None)
    if not upstream_key:
        raise HTTPException(status_code=503, detail=f"Service {service} not configured")

    container, account = await _authenticate_and_check_budget(request)

    # Forward request to upstream
    upstream_url = f"{UPSTREAM_URLS[service]}/{path}"
    body = await request.body()

    # Rewrite model name for Perplexity — OpenClaw sends Bedrock model IDs
    # but Perplexity only accepts its own models (sonar, sonar-pro, etc.)
    if service == "search" and body:
        try:
            payload = json.loads(body)
            logger.info(
                "Proxy request body for user %s: model=%s keys=%s",
                container["owner_id"],
                payload.get("model"),
                list(payload.keys()),
            )
            if "model" in payload:
                payload["model"] = "sonar"
                body = json.dumps(payload).encode()
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream_resp = await client.request(
                method=request.method,
                url=upstream_url,
                content=body,
                headers={
                    "Authorization": f"Bearer {upstream_key}",
                    "Content-Type": request.headers.get("content-type", "application/json"),
                },
            )
        logger.info(
            "Proxy upstream response: %s %s for user %s, upstream_headers=%s, body_len=%d",
            upstream_resp.status_code,
            upstream_url,
            container["owner_id"],
            dict(upstream_resp.headers),
            len(upstream_resp.content),
        )
        logger.info(
            "Proxy response body preview for user %s: %.500s",
            container["owner_id"],
            upstream_resp.text,
        )
    except Exception as e:
        logger.error("Proxy upstream error for user %s: %s — %s", container["owner_id"], upstream_url, e)
        raise

    # Usage recording is stubbed out during DynamoDB migration

    # Build response — only forward safe headers.
    # Strip auth headers (leak prevention) AND transport headers (content-length,
    # content-encoding, transfer-encoding) because httpx may have decompressed or
    # de-chunked the body, making the original values incorrect for the bytes we
    # actually return. FastAPI will set correct values from upstream_resp.content.
    safe_headers = {}
    for key, value in upstream_resp.headers.items():
        lower = key.lower()
        if lower in (
            "authorization",
            "www-authenticate",
            "set-cookie",
            "x-api-key",
            "content-length",
            "content-encoding",
            "transfer-encoding",
        ):
            continue
        safe_headers[key] = value

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        media_type=upstream_resp.headers.get("content-type"),
        headers=safe_headers,
    )
