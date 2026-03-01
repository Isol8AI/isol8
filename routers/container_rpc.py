"""
Generic RPC proxy to user's OpenClaw gateway container.

Single endpoint: POST /rpc accepts { method, params } and forwards
to the user's container via short-lived WebSocket connection.
Gateway tokens stay server-side — never exposed to the browser.

The OpenClaw gateway requires a connect handshake before accepting
RPC calls: receive connect.challenge → send connect with auth token
→ receive hello-ok → then send RPC request.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from websockets import connect as ws_connect

from core.auth import AuthContext, get_current_user
from core.containers import get_container_manager

logger = logging.getLogger(__name__)

router = APIRouter()

_WS_TIMEOUT = 30  # seconds


class RpcRequest(BaseModel):
    method: str = Field(..., description="RPC method name (e.g. 'health', 'agents.list')")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Optional method parameters")


async def _openclaw_handshake(ws, token: str) -> None:
    """Complete the OpenClaw gateway connect handshake.

    1. Receive connect.challenge from gateway
    2. Send connect request with auth token
    3. Verify hello-ok response

    Raises:
        RuntimeError: If handshake fails.
    """
    # Step 1: receive connect.challenge
    raw = await asyncio.wait_for(ws.recv(), timeout=10)
    challenge = json.loads(raw)
    if challenge.get("event") != "connect.challenge":
        raise RuntimeError(f"Expected connect.challenge, got: {challenge.get('event', 'unknown')}")

    # Step 2: send connect
    connect_msg = {
        "type": "req",
        "id": str(uuid.uuid4()),
        "method": "connect",
        "params": {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": "cli",
                "version": "1.0.0",
                "platform": "linux",
                "mode": "cli",
            },
            "role": "operator",
            "scopes": ["operator.admin"],
            "auth": {"token": token},
        },
    }
    await ws.send(json.dumps(connect_msg))

    # Step 3: verify hello-ok
    resp_raw = await asyncio.wait_for(ws.recv(), timeout=10)
    resp = json.loads(resp_raw)
    if not resp.get("ok"):
        err = resp.get("error", {}).get("message", "unknown error")
        raise RuntimeError(f"Gateway connect failed: {err}")


async def _call_gateway_rpc(
    port: int,
    token: str,
    method: str,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Open a short-lived WebSocket to the gateway, send RPC call, return response."""
    uri = f"ws://127.0.0.1:{port}"

    async with ws_connect(uri, open_timeout=_WS_TIMEOUT, close_timeout=5) as ws:
        # Complete OpenClaw connect handshake first
        await _openclaw_handshake(ws, token)

        # Now send the actual RPC request
        req_id = str(uuid.uuid4())
        rpc_msg = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        await ws.send(json.dumps(rpc_msg))

        # Read messages until we get the matching RPC response.
        # The gateway may send event broadcasts (health, state) before
        # responding to our request — skip those.
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=_WS_TIMEOUT)
            data = json.loads(raw)
            if data.get("type") == "res" and data.get("id") == req_id:
                if not data.get("ok"):
                    err_msg = data.get("error", {}).get("message", "RPC call rejected")
                    raise RuntimeError(f"Gateway RPC error: {err_msg}")
                return data.get("payload", {})


@router.post(
    "/rpc",
    summary="Proxy RPC call to user's OpenClaw container",
    description=(
        "Forwards a JSON-RPC call to the user's dedicated OpenClaw container. "
        "Opens a short-lived WebSocket connection, sends the method call, "
        "and returns the response. Gateway tokens are never exposed to the browser."
    ),
    operation_id="container_rpc",
    responses={
        404: {"description": "No running container for this user"},
        502: {"description": "Gateway connection or RPC call failed"},
    },
)
async def container_rpc(
    body: RpcRequest,
    auth: AuthContext = Depends(get_current_user),
):
    cm = get_container_manager()
    info = cm.get_container_info(auth.user_id)

    if not info or info.status != "running":
        raise HTTPException(
            status_code=404,
            detail="No running container. Subscribe to access the control panel.",
        )

    try:
        result = await _call_gateway_rpc(
            port=info.port,
            token=info.gateway_token,
            method=body.method,
            params=body.params,
        )
    except ConnectionRefusedError:
        logger.error("Gateway refused connection for user %s on port %d", auth.user_id, info.port)
        raise HTTPException(status_code=502, detail="Container gateway is not responding")
    except TimeoutError:
        logger.error("Gateway timeout for user %s on port %d", auth.user_id, info.port)
        raise HTTPException(status_code=502, detail="Container gateway timed out")
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from gateway for user %s: %s", auth.user_id, e)
        raise HTTPException(status_code=502, detail="Invalid response from container gateway")
    except Exception as e:
        logger.error("RPC call failed for user %s: %s", auth.user_id, e)
        raise HTTPException(status_code=502, detail="Gateway RPC call failed")

    return {"result": result}
