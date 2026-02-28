"""
Generic RPC proxy to user's OpenClaw gateway container.

Single endpoint: POST /rpc accepts { method, params } and forwards
to the user's container via short-lived WebSocket connection.
Gateway tokens stay server-side — never exposed to the browser.
"""

import json
import logging
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


async def _call_gateway_rpc(
    port: int,
    token: str,
    method: str,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Open a short-lived WebSocket to the gateway, send RPC call, return response."""
    uri = f"ws://127.0.0.1:{port}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    message = json.dumps({"method": method, "params": params or {}})

    async with ws_connect(uri, additional_headers=headers, open_timeout=_WS_TIMEOUT, close_timeout=5) as ws:
        await ws.send(message)
        raw = await ws.recv()

    return json.loads(raw)


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
