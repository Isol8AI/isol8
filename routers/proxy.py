"""Proxy router for Isol8-provided external tool APIs.

Routes tool calls from user containers through our backend,
keeping real API keys server-side. Users authenticate with
their gateway_token.
"""

import json
import logging
from decimal import Decimal

import boto3
import httpx
from botocore.config import Config as BotoConfig
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

# Bedrock Titan Embed v2: $0.00002 per 1K input tokens
EMBEDDING_COST_PER_TOKEN = Decimal("0.00000002")
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024

_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.AWS_REGION,
            config=BotoConfig(
                read_timeout=30,
                connect_timeout=10,
                retries={"max_attempts": 2},
            ),
        )
    return _bedrock_client


async def _call_bedrock_embed(text: str) -> dict:
    """Call Bedrock Titan Embed v2 and return the response dict."""
    client = _get_bedrock_client()
    body = json.dumps(
        {
            "inputText": text,
            "dimensions": EMBEDDING_DIMENSIONS,
            "normalize": True,
        }
    )
    response = client.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    return json.loads(response["body"].read())


@router.post("/embeddings/embeddings", include_in_schema=False)
async def proxy_embeddings(request: Request):
    """OpenAI-compatible embeddings endpoint backed by Bedrock Titan."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization")
    token = auth_header[7:]

    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(select(Container).where(Container.gateway_token == token))
        container = result.scalar_one_or_none()
        if not container:
            raise HTTPException(status_code=401, detail="Invalid gateway token")

        result = await db.execute(select(BillingAccount).where(BillingAccount.clerk_user_id == container.user_id))
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=403, detail="No billing account")

        body = await request.json()
        input_data = body.get("input", "")
        texts = input_data if isinstance(input_data, list) else [input_data]

        embeddings = []
        total_tokens = 0

        for i, text in enumerate(texts):
            result = await _call_bedrock_embed(text)
            embeddings.append(
                {
                    "object": "embedding",
                    "index": i,
                    "embedding": result["embedding"],
                }
            )
            total_tokens += result.get("inputTextTokenCount", 0)

        # Record usage
        try:
            usage_service = UsageService(db)
            cost = EMBEDDING_COST_PER_TOKEN * total_tokens
            await usage_service.record_tool_usage(
                billing_account_id=account.id,
                clerk_user_id=container.user_id,
                tool_id="bedrock_embeddings",
                quantity=total_tokens,
                total_cost=cost,
                source="embeddings",
            )
        except Exception:
            logger.exception("Failed to record embedding usage for user %s", container.user_id)
            await db.rollback()

        return {
            "object": "list",
            "data": embeddings,
            "model": body.get("model", "titan-embed-v2"),
            "usage": {
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens,
            },
        }


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

        # Record usage only on successful upstream response
        if upstream_resp.is_success:
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

    # Build response — only forward safe headers, never auth-related ones
    safe_headers = {}
    for key, value in upstream_resp.headers.items():
        lower = key.lower()
        if lower not in ("authorization", "www-authenticate", "set-cookie", "x-api-key"):
            safe_headers[key] = value

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        media_type=upstream_resp.headers.get("content-type"),
        headers=safe_headers,
    )
