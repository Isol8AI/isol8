"""
Proxy for the OpenClaw built-in control UI.

Serves the control-UI SPA through the backend so that:
  1. The SPA derives its WebSocket URL from the proxy origin (no CORS / mixed-content).
  2. The gateway auth token is injected server-side during the WS handshake —
     credentials never reach the browser.

HTTP GET  /api/v1/control-ui/{path}  → proxies static files from the gateway.
WS        /api/v1/control-ui         → bidirectional relay with handshake injection.
"""

import asyncio
import json
import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response

from core.auth import _decode_token
from core.containers import get_ecs_manager
from core.containers.ecs_manager import GATEWAY_PORT
from core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

_HTTP_TIMEOUT = 15.0  # seconds for upstream HTTP requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_user_container(user_id: str):
    """Look up the user's running container. Returns (container, ip) or raises."""
    async for db in get_db():
        ecs = get_ecs_manager()
        container, ip = await ecs.resolve_running_container(user_id, db)
        if not container or not ip:
            raise HTTPException(status_code=404, detail="No running container")
        return container, ip
    raise HTTPException(status_code=500, detail="Database unavailable")


async def _validate_clerk_token(token: str) -> str:
    """Validate a Clerk JWT and return the user_id (sub claim)."""
    try:
        payload = await _decode_token(token)
        return payload["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---------------------------------------------------------------------------
# HTTP proxy — static files
# ---------------------------------------------------------------------------


@router.get("/{path:path}")
async def proxy_static(path: str, token: str = Query(default=None)):
    """Proxy static assets from the OpenClaw control UI SPA.

    The root (index.html) requires a ?token= query parameter with a valid
    Clerk JWT so we can resolve the user's container.  Sub-resources (JS,
    CSS, fonts) are identical across containers and don't require auth.
    """
    is_root = path in ("", "index.html")

    if is_root and not token:
        raise HTTPException(status_code=401, detail="Missing token parameter")

    if is_root:
        user_id = await _validate_clerk_token(token)
        container, ip = await _resolve_user_container(user_id)
    else:
        # For sub-resources we still need a container IP to proxy from.
        # Accept optional token; if absent, return 401 so the iframe
        # can supply it.  In practice the browser sends these from the
        # same origin after the root page loads, but the SPA may request
        # assets before the iframe src is set.
        if token:
            user_id = await _validate_clerk_token(token)
            container, ip = await _resolve_user_container(user_id)
        else:
            raise HTTPException(status_code=401, detail="Missing token parameter")

    upstream_url = f"http://{ip}:{GATEWAY_PORT}/{path}" if path else f"http://{ip}:{GATEWAY_PORT}/"

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        try:
            resp = await client.get(upstream_url)
        except httpx.ConnectError:
            raise HTTPException(status_code=502, detail="Gateway not reachable")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Gateway timeout")

    content_type = resp.headers.get("content-type", "application/octet-stream")

    # For the root HTML page, inject the basePath script so the SPA
    # constructs its WebSocket URL relative to our proxy path.
    if is_root and "text/html" in content_type:
        html = resp.text
        base_path_script = '<script>window.__OPENCLAW_CONTROL_UI_BASE_PATH__="/api/v1/control-ui";</script>'
        html = html.replace("<head>", f"<head>{base_path_script}", 1)
        return HTMLResponse(content=html, status_code=resp.status_code)

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type,
    )


# ---------------------------------------------------------------------------
# WebSocket proxy — bidirectional relay with handshake injection
# ---------------------------------------------------------------------------


@router.websocket("")
async def proxy_websocket(ws: WebSocket, token: str = Query(default=None)):
    """WebSocket proxy that intercepts the OpenClaw handshake to inject the
    gateway auth token, then relays messages bidirectionally."""
    if not token:
        await ws.close(code=4001, reason="Missing token parameter")
        return

    try:
        user_id = await _validate_clerk_token(token)
    except HTTPException:
        await ws.close(code=4001, reason="Invalid or expired token")
        return

    try:
        container, ip = await _resolve_user_container(user_id)
    except HTTPException as e:
        await ws.close(code=4004, reason=e.detail)
        return

    gateway_token = container.gateway_token
    upstream_uri = f"ws://{ip}:{GATEWAY_PORT}"

    await ws.accept()

    try:
        from websockets import connect as ws_connect

        async with ws_connect(upstream_uri, open_timeout=15, close_timeout=5) as upstream:
            # --- Handshake interception ---
            # Step 1: Receive connect.challenge from gateway
            raw = await asyncio.wait_for(upstream.recv(), timeout=10)
            challenge = json.loads(raw)
            if challenge.get("event") != "connect.challenge":
                await ws.close(code=4002, reason="Unexpected gateway handshake")
                return

            # Step 2: Send connect with gateway auth token (injected server-side)
            connect_msg = {
                "type": "req",
                "id": str(uuid.uuid4()),
                "method": "connect",
                "params": {
                    "minProtocol": 3,
                    "maxProtocol": 3,
                    "client": {
                        "id": "control-ui-proxy",
                        "version": "1.0.0",
                        "platform": "linux",
                        "mode": "cli",
                    },
                    "role": "operator",
                    "scopes": ["operator.admin"],
                    "auth": {"token": gateway_token},
                },
            }
            await upstream.send(json.dumps(connect_msg))

            # Step 3: Verify hello-ok and forward to browser
            resp_raw = await asyncio.wait_for(upstream.recv(), timeout=10)
            resp = json.loads(resp_raw)
            if not resp.get("ok"):
                err = resp.get("error", {}).get("message", "handshake failed")
                await ws.close(code=4002, reason=f"Gateway connect failed: {err}")
                return

            # Forward the hello-ok to the browser so the control UI knows
            # the connection is established
            await ws.send_text(resp_raw)

            # --- Bidirectional relay ---
            async def browser_to_upstream():
                try:
                    while True:
                        data = await ws.receive_text()
                        await upstream.send(data)
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass

            async def upstream_to_browser():
                try:
                    async for msg in upstream:
                        if isinstance(msg, str):
                            await ws.send_text(msg)
                        elif isinstance(msg, bytes):
                            await ws.send_bytes(msg)
                except Exception:
                    pass

            # Run both directions concurrently; when either ends, cancel the other
            tasks = [
                asyncio.create_task(browser_to_upstream()),
                asyncio.create_task(upstream_to_browser()),
            ]
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
            except Exception:
                for t in tasks:
                    t.cancel()

    except Exception as e:
        logger.warning("Control UI WebSocket proxy error for user %s: %s", user_id, e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
