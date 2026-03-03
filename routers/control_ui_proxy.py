"""
Proxy for the OpenClaw built-in control UI.

Serves the control-UI SPA through the backend so that:
  1. The SPA derives its WebSocket URL from the proxy origin (no CORS / mixed-content).
  2. The gateway auth token is injected server-side during the WS handshake —
     credentials never reach the browser.

Auth flow:
  - Root page requires ?token= (Clerk JWT). On success, creates a short-lived
    in-memory session and serves the page with basePath including the session ID.
  - All sub-resources and WebSocket connections use the session ID from the URL
    path — no cookies needed, works in cross-origin iframes.

Routes:
  GET  /api/v1/control-ui/?token=...              → root page (creates session)
  GET  /api/v1/control-ui/s/{session}/{path}       → sub-resources via session
  WS   /api/v1/control-ui/s/{session}              → WebSocket relay via session
"""

import asyncio
import json
import logging
import secrets
import time
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
_SESSION_TTL = 600  # 10 minutes


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------


class _Session:
    __slots__ = ("user_id", "ip", "gateway_token", "expires")

    def __init__(self, user_id: str, ip: str, gateway_token: str):
        self.user_id = user_id
        self.ip = ip
        self.gateway_token = gateway_token
        self.expires = time.time() + _SESSION_TTL


_sessions: dict[str, _Session] = {}


def _cleanup_sessions() -> None:
    """Remove expired sessions (called lazily)."""
    now = time.time()
    expired = [k for k, v in _sessions.items() if now > v.expires]
    for k in expired:
        del _sessions[k]


def _get_session(session_id: str) -> _Session | None:
    """Look up a valid session."""
    _cleanup_sessions()
    s = _sessions.get(session_id)
    if s and time.time() <= s.expires:
        return s
    return None


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
# HTTP proxy — root page (creates session)
# ---------------------------------------------------------------------------


@router.get("/")
@router.get("/index.html")
async def proxy_root(token: str = Query(default=None)):
    """Serve the control UI root page. Requires ?token= (Clerk JWT).

    Creates a session and injects the basePath with session ID so all
    subsequent requests (sub-resources + WebSocket) authenticate via URL path.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token parameter")

    user_id = await _validate_clerk_token(token)
    container, ip = await _resolve_user_container(user_id)

    # Create session
    session_id = secrets.token_urlsafe(24)
    _sessions[session_id] = _Session(
        user_id=user_id,
        ip=ip,
        gateway_token=container.gateway_token,
    )

    # Fetch root page from gateway
    upstream_url = f"http://{ip}:{GATEWAY_PORT}/"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        try:
            resp = await client.get(upstream_url)
        except httpx.ConnectError:
            raise HTTPException(status_code=502, detail="Gateway not reachable")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Gateway timeout")

    html = resp.text
    # Inject basePath with session ID so SPA constructs all URLs through our session.
    # <base> tag makes the browser resolve relative asset paths (./assets/...) through
    # the session route instead of the root page URL.
    base_path = f"/api/v1/control-ui/s/{session_id}"
    base_tag = f'<base href="{base_path}/">'
    base_path_script = f'<script>window.__OPENCLAW_CONTROL_UI_BASE_PATH__="{base_path}";</script>'
    html = html.replace("<head>", f"<head>{base_tag}{base_path_script}", 1)

    return HTMLResponse(content=html, status_code=resp.status_code)


# ---------------------------------------------------------------------------
# HTTP proxy — sub-resources via session
# ---------------------------------------------------------------------------


@router.get("/s/{session_id}/{path:path}")
async def proxy_static(session_id: str, path: str):
    """Proxy static assets using the session for auth + container resolution."""
    session = _get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    upstream_url = f"http://{session.ip}:{GATEWAY_PORT}/{path}" if path else f"http://{session.ip}:{GATEWAY_PORT}/"

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        try:
            resp = await client.get(upstream_url)
        except httpx.ConnectError:
            raise HTTPException(status_code=502, detail="Gateway not reachable")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Gateway timeout")

    content_type = resp.headers.get("content-type", "application/octet-stream")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type,
    )


# ---------------------------------------------------------------------------
# WebSocket proxy — bidirectional relay with handshake injection
# ---------------------------------------------------------------------------


@router.websocket("/s/{session_id}")
async def proxy_websocket(ws: WebSocket, session_id: str):
    """WebSocket proxy that uses session for auth, intercepts the OpenClaw
    handshake to inject the gateway token, then relays bidirectionally."""
    session = _get_session(session_id)
    if not session:
        await ws.close(code=4001, reason="Invalid or expired session")
        return

    upstream_uri = f"ws://{session.ip}:{GATEWAY_PORT}"

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
                    "auth": {"token": session.gateway_token},
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

            # Forward the hello-ok to the browser
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
        logger.warning("Control UI WebSocket proxy error for user %s: %s", session.user_id, e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
