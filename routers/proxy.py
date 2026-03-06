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
from sqlalchemy import select

from core.config import settings
from core.database import get_session_factory
from core.services.usage_service import UsageService
from models.billing import BillingAccount
from models.container import Container

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


@router.api_route(
    "/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def proxy_request(
    service: str,
    path: str,
    request: Request,
):
    """Forward request to upstream API with Isol8's key."""
    # Extract token from header
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization")
    token = auth_header[7:]

    if service not in UPSTREAM_URLS:
        raise HTTPException(status_code=404, detail=f"Unknown proxy service: {service}")

    upstream_key_attr = UPSTREAM_KEY_SETTINGS[service]
    upstream_key = getattr(settings, upstream_key_attr, None)
    if not upstream_key:
        raise HTTPException(status_code=503, detail=f"Service {service} not configured")

    session_factory = get_session_factory()
    async with session_factory() as db:
        # Validate gateway token
        result = await db.execute(select(Container).where(Container.gateway_token == token))
        container = result.scalar_one_or_none()
        if not container:
            raise HTTPException(status_code=401, detail="Invalid gateway token")

        # Get billing account
        result = await db.execute(select(BillingAccount).where(BillingAccount.clerk_user_id == container.user_id))
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=403, detail="No billing account")

        # Forward request to upstream
        upstream_url = f"{UPSTREAM_URLS[service]}/{path}"
        body = await request.body()

        # Rewrite model name for Perplexity — OpenClaw sends Bedrock model IDs
        # but Perplexity only accepts its own models (sonar, sonar-pro, etc.)
        if service == "search" and body:
            try:
                payload = json.loads(body)
                if "model" in payload:
                    payload["model"] = "sonar"
                    body = json.dumps(payload).encode()
            except (json.JSONDecodeError, TypeError):
                pass

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

        # Record usage (non-blocking - don't fail the request)
        try:
            usage_service = UsageService(db)
            await usage_service.record_tool_usage(
                billing_account_id=account.id,
                clerk_user_id=container.user_id,
                tool_id=f"perplexity_{service}",
                quantity=1,
                total_cost=DEFAULT_TOOL_COSTS.get(service, Decimal("0.005")),
            )
        except Exception:
            logger.exception("Failed to record proxy usage for user %s", container.user_id)
            await db.rollback()

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        media_type=upstream_resp.headers.get("content-type"),
    )
