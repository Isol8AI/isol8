"""
Proxy for the OpenClaw built-in control UI.

Serves the control-UI SPA through the backend so that:
  1. The SPA derives its WebSocket URL from the proxy origin (no CORS / mixed-content).
  2. The gateway auth token is injected server-side during the WS handshake —
     credentials never reach the browser.

Auth flow:
  - Root page requires ?token= (Clerk JWT). On success, creates a short-lived
    in-memory session and serves the page with a <base> tag so assets resolve
    through the session path.
  - Sub-resources (JS/CSS) use the session ID from the URL path.
  - WebSocket: the SPA connects to the root path and sends the Clerk JWT
    (from ?token=) as its "gateway token" in the OpenClaw connect message.
    The proxy validates the JWT, resolves the container, and replaces it
    with the real gateway token before forwarding upstream.

Routes:
  GET  /api/v1/control-ui/?token=...              → root page (creates session)
  GET  /api/v1/control-ui/s/{session}/{path}       → sub-resources via session
  WS   /api/v1/control-ui/                         → WebSocket relay (auth via connect msg)
"""

import asyncio
import json
import logging
import secrets
import time

import httpx
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from websockets import connect as ws_connect

from core.auth import AuthContext, _decode_token, _extract_org_claims, resolve_owner_id
from core.containers import get_ecs_manager
from core.containers.ecs_manager import GATEWAY_PORT

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


async def _resolve_user_container(owner_id: str):
    """Look up the owner's running container. Returns (container, ip) or raises."""
    ecs = get_ecs_manager()
    container, ip = await ecs.resolve_running_container(owner_id)
    if not container or not ip:
        raise HTTPException(status_code=404, detail="No running container")
    return container, ip


async def _validate_clerk_token(token: str) -> AuthContext:
    """Validate a Clerk JWT and return an AuthContext."""
    try:
        payload = await _decode_token(token)
        org = _extract_org_claims(payload)
        return AuthContext(
            user_id=payload["sub"],
            org_id=org["org_id"],
            org_role=org["org_role"],
            org_slug=org["org_slug"],
            org_permissions=org["org_permissions"],
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---------------------------------------------------------------------------
# HTTP proxy — root page (creates session)
# ---------------------------------------------------------------------------


@router.get("/")
@router.get("/index.html")
async def proxy_root(
    token: str = Query(default=None),
    ws_url: str = Query(default=None),
):
    """Serve the control UI root page. Requires ?token= (Clerk JWT).

    Creates a session and injects the basePath with session ID so all
    subsequent requests (sub-resources + WebSocket) authenticate via URL path.

    If ws_url is provided (WebSocket API Gateway URL), injects a localStorage
    override so the SPA connects its WebSocket through the API Gateway instead
    of directly to this proxy.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token parameter")

    auth = await _validate_clerk_token(token)
    owner_id = resolve_owner_id(auth)
    container, ip = await _resolve_user_container(owner_id)

    # Create session
    session_id = secrets.token_urlsafe(24)
    _sessions[session_id] = _Session(
        user_id=owner_id,
        ip=ip,
        gateway_token=container["gateway_token"],
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

    # If a WebSocket API Gateway URL is provided, inject localStorage override
    # so the SPA's WebSocket goes through the API Gateway (which supports WS)
    # instead of trying api-dev.isol8.co (which is HTTP-only and returns 400).
    ws_override_script = ""
    if ws_url:
        gateway_url_js = json.dumps(f"{ws_url}?token={token}")
        ws_override_script = (
            "<script>"
            "(function(){"
            'var k="openclaw.control.settings.v1",s={};'
            "try{s=JSON.parse(localStorage.getItem(k))||{}}catch(e){}"
            f"s.gatewayUrl={gateway_url_js};"
            "localStorage.setItem(k,JSON.stringify(s))"
            "})()"
            "</script>"
        )

    html = html.replace(
        "<head>",
        f"<head>{base_tag}{base_path_script}{ws_override_script}",
        1,
    )

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
# WebSocket proxy — auth via OpenClaw connect message
# ---------------------------------------------------------------------------
#
# The SPA connects WebSocket to its own page origin (the root proxy path).
# It sends the Clerk JWT (from ?token=) as the "gateway token" in the
# OpenClaw connect message.  The proxy:
#   1. Mimics the gateway's connect.challenge
#   2. Receives the browser's connect (with Clerk JWT)
#   3. Validates the JWT → resolves the user's container
#   4. Opens upstream WS and authenticates with the REAL gateway token
#   5. Forwards the hello-ok and relays bidirectionally
# ---------------------------------------------------------------------------


@router.websocket("/")
async def proxy_websocket(ws: WebSocket):
    """WebSocket proxy that authenticates via the Clerk JWT in the OpenClaw
    connect message, then relays to the real gateway."""
    await ws.accept()

    owner_id = None
    try:
        # --- Phase 1: Browser handshake (we pretend to be the gateway) ---

        # Send connect.challenge to the browser
        await ws.send_text(json.dumps({"event": "connect.challenge"}))

        # Receive the browser's connect message (contains Clerk JWT as auth token)
        raw = await asyncio.wait_for(ws.receive_text(), timeout=15)
        browser_connect = json.loads(raw)

        if browser_connect.get("method") != "connect":
            await ws.close(code=4002, reason="Expected connect message")
            return

        clerk_token = browser_connect.get("params", {}).get("auth", {}).get("token", "")
        if not clerk_token:
            await ws.close(code=4001, reason="Missing auth token")
            return

        # Validate Clerk JWT and resolve container
        auth = await _validate_clerk_token(clerk_token)
        owner_id = resolve_owner_id(auth)
        container, ip = await _resolve_user_container(owner_id)

        # --- Phase 2: Upstream handshake (real gateway) ---

        upstream_uri = f"ws://{ip}:{GATEWAY_PORT}"
        async with ws_connect(upstream_uri, open_timeout=15, close_timeout=5) as upstream:
            # Receive connect.challenge from real gateway
            gw_raw = await asyncio.wait_for(upstream.recv(), timeout=10)
            gw_challenge = json.loads(gw_raw)
            if gw_challenge.get("event") != "connect.challenge":
                await ws.close(code=4002, reason="Unexpected gateway handshake")
                return

            # Forward browser's connect message but replace auth token
            upstream_connect = dict(browser_connect)
            upstream_connect.setdefault("params", {})["auth"] = {"token": container["gateway_token"]}
            await upstream.send(json.dumps(upstream_connect))

            # Receive hello-ok from gateway and forward to browser
            resp_raw = await asyncio.wait_for(upstream.recv(), timeout=10)
            resp = json.loads(resp_raw)
            if not resp.get("ok"):
                err = resp.get("error", {}).get("message", "handshake failed")
                await ws.close(code=4002, reason=f"Gateway connect failed: {err}")
                return

            await ws.send_text(resp_raw)

            # --- Phase 3: Bidirectional relay ---

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
        logger.warning("Control UI WebSocket proxy error for owner %s: %s", owner_id, e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
