# LanceDB + Bedrock Embeddings Proxy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable memory-lancedb plugin on all OpenClaw instances with Bedrock Titan Embeddings served via an OpenAI-compatible proxy, with usage tracking and billing.

**Architecture:** The Isol8 proxy router (`routers/proxy.py`) gets a new "embeddings" service that translates OpenAI embedding requests to Bedrock Titan Embed v2. The `write_openclaw_config()` adds a `plugins` section enabling memory-lancedb pointed at this proxy. Each embedding call is billed via `record_tool_usage()`.

**Tech Stack:** FastAPI, boto3 (Bedrock Runtime), OpenAI embeddings format, LanceDB (OpenClaw plugin), existing UsageService

---

### Task 1: Add Bedrock Embeddings Route to Proxy

**Files:**
- Modify: `backend/routers/proxy.py`
- Test: `backend/tests/unit/routers/test_proxy_embeddings.py`

**Context:** The proxy router authenticates requests via gateway_token (matches to a Container row), then forwards to upstream APIs. The embeddings route intercepts the OpenAI `/embeddings` format and calls Bedrock Titan instead.

Bedrock Titan Embed v2 (`amazon.titan-embed-text-v2:0`):
- Request: `{"inputText": "...", "dimensions": 1024, "normalize": true}`
- Response: `{"embedding": [...], "inputTextTokenCount": N}`

OpenAI embeddings format:
- Request: `{"model": "...", "input": "text"}`
- Response: `{"object": "list", "data": [{"object": "embedding", "index": 0, "embedding": [...]}], "model": "...", "usage": {"prompt_tokens": N, "total_tokens": N}}`

**Step 1: Write the failing test**

Create `backend/tests/unit/routers/test_proxy_embeddings.py`:

```python
"""Tests for Bedrock embeddings proxy."""

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
def mock_container():
    container = MagicMock()
    container.user_id = "user_123"
    container.gateway_token = "test-token"
    return container


@pytest.fixture
def mock_billing_account():
    account = MagicMock()
    account.id = uuid4()
    account.clerk_user_id = "user_123"
    account.markup_multiplier = Decimal("1.4")
    return account


@pytest.fixture
def mock_bedrock_response():
    return {
        "embedding": [0.1] * 1024,
        "inputTextTokenCount": 5,
    }


@pytest.mark.asyncio
async def test_embeddings_returns_openai_format(
    mock_container, mock_billing_account, mock_bedrock_response
):
    """Proxy returns OpenAI-compatible embedding response."""
    with (
        patch("routers.proxy.get_session_factory") as mock_sf,
        patch("routers.proxy._call_bedrock_embed") as mock_bedrock,
    ):
        # DB mocks
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(
            side_effect=[mock_container, mock_billing_account]
        )
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_sf.return_value = MagicMock(return_value=mock_session)

        mock_bedrock.return_value = mock_bedrock_response

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/proxy/embeddings/embeddings",
                json={"model": "titan-embed-v2", "input": "hello world"},
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "list"
        assert len(body["data"]) == 1
        assert body["data"][0]["object"] == "embedding"
        assert len(body["data"][0]["embedding"]) == 1024
        assert body["usage"]["prompt_tokens"] == 5


@pytest.mark.asyncio
async def test_embeddings_batch_input(
    mock_container, mock_billing_account, mock_bedrock_response
):
    """Proxy handles list input (multiple texts)."""
    with (
        patch("routers.proxy.get_session_factory") as mock_sf,
        patch("routers.proxy._call_bedrock_embed") as mock_bedrock,
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(
            side_effect=[mock_container, mock_billing_account]
        )
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_sf.return_value = MagicMock(return_value=mock_session)

        mock_bedrock.return_value = mock_bedrock_response

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/proxy/embeddings/embeddings",
                json={"model": "titan-embed-v2", "input": ["hello", "world"]},
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 2
        assert mock_bedrock.call_count == 2


@pytest.mark.asyncio
async def test_embeddings_records_usage(
    mock_container, mock_billing_account, mock_bedrock_response
):
    """Proxy records tool usage for billing."""
    with (
        patch("routers.proxy.get_session_factory") as mock_sf,
        patch("routers.proxy._call_bedrock_embed") as mock_bedrock,
        patch("routers.proxy.UsageService") as mock_usage_cls,
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(
            side_effect=[mock_container, mock_billing_account]
        )
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_sf.return_value = MagicMock(return_value=mock_session)

        mock_bedrock.return_value = mock_bedrock_response

        mock_usage = AsyncMock()
        mock_usage_cls.return_value = mock_usage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/proxy/embeddings/embeddings",
                json={"model": "titan-embed-v2", "input": "hello"},
                headers={"Authorization": "Bearer test-token"},
            )

        mock_usage.record_tool_usage.assert_called_once()
        call_kwargs = mock_usage.record_tool_usage.call_args[1]
        assert call_kwargs["tool_id"] == "bedrock_embeddings"
        assert call_kwargs["quantity"] == 5  # token count


@pytest.mark.asyncio
async def test_embeddings_rejects_invalid_token():
    """Proxy rejects requests with no auth."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/proxy/embeddings/embeddings",
            json={"model": "titan-embed-v2", "input": "hello"},
        )
    assert resp.status_code == 401
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/routers/test_proxy_embeddings.py -v`
Expected: FAIL (embeddings route doesn't exist yet)

**Step 3: Implement the embeddings proxy**

Modify `backend/routers/proxy.py` — add the Bedrock embeddings handler and a dedicated route:

```python
"""Proxy router for Isol8-provided external tool APIs.

Routes tool calls from user containers through our backend,
keeping real API keys server-side. Users authenticate with
their gateway_token.
"""

import json as json_module
import logging
from decimal import Decimal

import boto3
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

# Bedrock Titan Embed v2 pricing: $0.00002 per 1K input tokens
EMBEDDING_COST_PER_TOKEN = Decimal("0.00000002")
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024

_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime", region_name=settings.AWS_REGION
        )
    return _bedrock_client


async def _call_bedrock_embed(text: str) -> dict:
    """Call Bedrock Titan Embed v2 and return the response dict."""
    client = _get_bedrock_client()
    body = json_module.dumps({
        "inputText": text,
        "dimensions": EMBEDDING_DIMENSIONS,
        "normalize": True,
    })
    response = client.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    return json_module.loads(response["body"].read())


async def _authenticate_proxy_request(
    request: Request,
) -> tuple:
    """Validate gateway token, return (container, billing_account, db_session)."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization")
    token = auth_header[7:]

    session_factory = get_session_factory()
    db = session_factory()
    session = await db.__aenter__()

    result = await session.execute(
        select(Container).where(Container.gateway_token == token)
    )
    container = result.scalar_one_or_none()
    if not container:
        await db.__aexit__(None, None, None)
        raise HTTPException(status_code=401, detail="Invalid gateway token")

    result = await session.execute(
        select(BillingAccount).where(
            BillingAccount.clerk_user_id == container.user_id
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        await db.__aexit__(None, None, None)
        raise HTTPException(status_code=403, detail="No billing account")

    return container, account, session, db


@router.post("/embeddings/embeddings")
async def proxy_embeddings(request: Request):
    """OpenAI-compatible embeddings endpoint backed by Bedrock Titan."""
    container, account, session, db = await _authenticate_proxy_request(request)

    try:
        body = await request.json()
        input_data = body.get("input", "")

        # Normalize to list
        texts = input_data if isinstance(input_data, list) else [input_data]

        embeddings = []
        total_tokens = 0

        for i, text in enumerate(texts):
            result = await _call_bedrock_embed(text)
            embeddings.append({
                "object": "embedding",
                "index": i,
                "embedding": result["embedding"],
            })
            total_tokens += result.get("inputTextTokenCount", 0)

        # Record usage
        try:
            usage_service = UsageService(session)
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
            logger.exception(
                "Failed to record embedding usage for user %s", container.user_id
            )

        return {
            "object": "list",
            "data": embeddings,
            "model": body.get("model", "titan-embed-v2"),
            "usage": {
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens,
            },
        }
    finally:
        await db.__aexit__(None, None, None)


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
        result = await db.execute(
            select(Container).where(Container.gateway_token == token)
        )
        container = result.scalar_one_or_none()
        if not container:
            raise HTTPException(status_code=401, detail="Invalid gateway token")

        # Get billing account
        result = await db.execute(
            select(BillingAccount).where(
                BillingAccount.clerk_user_id == container.user_id
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=403, detail="No billing account")

        # Forward request to upstream
        upstream_url = f"{UPSTREAM_URLS[service]}/{path}"
        body = await request.body()

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

        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            media_type=upstream_resp.headers.get("content-type"),
        )
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/routers/test_proxy_embeddings.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/routers/proxy.py backend/tests/unit/routers/test_proxy_embeddings.py
git commit -m "feat: add Bedrock Titan embeddings proxy with OpenAI-compatible format"
```

---

### Task 2: Mount Proxy Router in main.py

**Files:**
- Modify: `backend/main.py:23-34` (imports) and `backend/main.py:196` (router registration)

**Context:** The proxy router exists but is NOT mounted in `main.py`. It needs to be registered at `/api/v1/proxy`.

**Step 1: Write the failing test**

Create `backend/tests/unit/routers/test_proxy_mounted.py`:

```python
"""Test that proxy router is mounted."""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_proxy_route_exists():
    """The proxy prefix is reachable (returns 401 not 404)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/proxy/embeddings/embeddings",
            json={"model": "test", "input": "hello"},
        )
    # 401 = route exists but auth failed; 404 = not mounted
    assert resp.status_code != 404
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/routers/test_proxy_mounted.py -v`
Expected: FAIL with 404

**Step 3: Add proxy router to main.py**

Add to imports (after line 30):
```python
    proxy,
```

Add after line 201 (after settings_keys router):
```python
# Tool proxy (Perplexity search, embeddings, etc.)
app.include_router(proxy.router, prefix="/api/v1/proxy", tags=["proxy"])
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/routers/test_proxy_mounted.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/main.py backend/tests/unit/routers/test_proxy_mounted.py
git commit -m "feat: mount proxy router at /api/v1/proxy"
```

---

### Task 3: Enable memory-lancedb in OpenClaw Config

**Files:**
- Modify: `backend/core/containers/config.py:12-162`
- Test: `backend/tests/unit/containers/test_config.py`

**Context:** `write_openclaw_config()` generates the `openclaw.json` for each user container. We need to add a `plugins` section that enables memory-lancedb with the Bedrock embedding proxy as the baseUrl. The gateway_token is reused as the embedding API key (same auth mechanism as search proxy).

**Step 1: Write the failing test**

Add to `backend/tests/unit/containers/test_config.py`:

```python
    def test_memory_lancedb_plugin_enabled(self):
        """memory-lancedb plugin is configured with embedding proxy."""
        config = json.loads(write_openclaw_config(gateway_token="tok_abc"))
        plugins = config["plugins"]
        assert plugins["slots"]["memory"] == "memory-lancedb"
        entry = plugins["entries"]["memory-lancedb"]
        assert entry["enabled"] is True
        embed = entry["config"]["embedding"]
        assert embed["apiKey"] == "tok_abc"
        assert "proxy/embeddings" in embed["baseUrl"]
        assert embed["dimensions"] == 1024

    def test_memory_lancedb_auto_capture_enabled(self):
        """memory-lancedb has autoCapture and autoRecall enabled."""
        config = json.loads(write_openclaw_config(gateway_token="tok_abc"))
        entry = config["plugins"]["entries"]["memory-lancedb"]
        assert entry["config"]["autoCapture"] is True
        assert entry["config"]["autoRecall"] is True

    def test_memory_lancedb_disabled_without_token(self):
        """memory-lancedb not enabled without gateway token (no proxy auth)."""
        config = json.loads(write_openclaw_config(gateway_token=""))
        plugins = config.get("plugins", {})
        entries = plugins.get("entries", {})
        lancedb = entries.get("memory-lancedb", {})
        assert lancedb.get("enabled") is not True
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/containers/test_config.py::TestWriteOpenclawConfig::test_memory_lancedb_plugin_enabled -v`
Expected: FAIL (no plugins key in config)

**Step 3: Add plugins section to write_openclaw_config**

In `backend/core/containers/config.py`, add the `plugins` block to the config dict (after the `hooks` section, before `browser`):

```python
        "plugins": {
            "slots": {
                "memory": "memory-lancedb" if gateway_token else "memory-core",
            },
            "entries": {
                "memory-lancedb": {
                    "enabled": bool(gateway_token),
                    "config": {
                        "embedding": {
                            "apiKey": gateway_token or "disabled",
                            "model": "titan-embed-v2",
                            "baseUrl": f"{proxy_base_url}/embeddings",
                            "dimensions": 1024,
                        },
                        "autoCapture": True,
                        "autoRecall": True,
                        "captureMaxChars": 2000,
                    },
                },
            },
        },
```

**Step 4: Run all config tests**

Run: `cd backend && python -m pytest tests/unit/containers/test_config.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/core/containers/config.py backend/tests/unit/containers/test_config.py
git commit -m "feat: enable memory-lancedb plugin with Bedrock embedding proxy"
```

---

### Task 4: Add boto3 Dependency (if missing)

**Files:**
- Check: `backend/requirements.txt`

**Step 1: Check if boto3 is already in requirements**

Run: `grep boto3 backend/requirements.txt`

**Step 2: Add if missing**

If not present, add `boto3` to `backend/requirements.txt` and install:

```bash
cd backend && pip install boto3
```

**Step 3: Commit (if changed)**

```bash
git add backend/requirements.txt
git commit -m "chore: add boto3 for Bedrock embeddings proxy"
```

---

### Task 5: Run Full Test Suite

**Step 1: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS (including the 178+ existing tests)

**Step 2: Fix any failures**

If existing tests break (e.g., config tests now expect plugins key), update them.

**Step 3: Final commit if needed**

```bash
git add -u
git commit -m "fix: update tests for memory-lancedb config changes"
```

---

## Notes

- **Titan Embed v2 pricing:** $0.00002/1K tokens (~$0.02/M tokens). At 1000 embedding calls/day with ~100 tokens each, cost is ~$0.002/day per user. Negligible.
- **Dimensions:** 1024 (Titan v2 default). Smaller than OpenAI's 1536 but quality is comparable for retrieval.
- **memorySearch coexistence:** The built-in `memorySearch` (local GGUF, indexes markdown files) remains enabled alongside memory-lancedb. They serve different purposes: file search vs. conversational memory.
- **Existing containers:** Will need re-provisioning (PATCH to `/debug/provision`) to pick up the new config. New containers get it automatically.
