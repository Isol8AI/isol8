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
from sqlalchemy.ext.asyncio import AsyncSession
from websockets import connect as ws_connect

from core.auth import AuthContext, get_current_user
from core.config import settings
from core.containers import get_ecs_manager
from core.containers.ecs_manager import GATEWAY_PORT
from core.database import get_db

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
    ip: str,
    token: str,
    method: str,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Open a short-lived WebSocket to the gateway, send RPC call, return response."""
    uri = f"ws://{ip}:{GATEWAY_PORT}"

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


@router.get(
    "/status",
    summary="Get container metadata for current user",
    description=(
        "Returns the user's container status and metadata. "
        "Sensitive fields (gateway_token, task_arn, access_point_id) are excluded."
    ),
    operation_id="container_status",
    responses={
        404: {"description": "No container for this user"},
    },
)
async def container_status(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ecs_manager = get_ecs_manager()
    container = await ecs_manager.get_service_status(auth.user_id, db)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")

    return {
        "service_name": container.service_name,
        "status": container.status,
        "substatus": container.substatus,
        "created_at": container.created_at.isoformat() if container.created_at else None,
        "updated_at": container.updated_at.isoformat() if container.updated_at else None,
        "region": settings.AWS_REGION,
    }


@router.post(
    "/gateway/restart",
    summary="Restart the OpenClaw gateway on the user's container",
    description=(
        "Sends a config.apply RPC to the user's running gateway container, "
        "which triggers a gateway process restart. "
        "Use this when the WebSocket connection is down but the container is running."
    ),
    operation_id="gateway_restart",
    responses={
        404: {"description": "No running container for this user"},
        502: {"description": "Gateway is not responding"},
    },
)
async def gateway_restart(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ecs_manager = get_ecs_manager()
    container, ip = await ecs_manager.resolve_running_container(auth.user_id, db)
    if not container:
        raise HTTPException(status_code=404, detail="No running container")
    if not ip:
        raise HTTPException(status_code=502, detail="Container gateway is starting up")

    try:
        await _call_gateway_rpc(
            ip=ip,
            token=container.gateway_token,
            method="config.apply",
            params={},
        )
    except ConnectionRefusedError:
        raise HTTPException(status_code=502, detail="Gateway is not responding")
    except TimeoutError:
        raise HTTPException(status_code=502, detail="Gateway restart timed out")
    except Exception as e:
        logger.error("Gateway restart failed for user %s: %s", auth.user_id, e)
        raise HTTPException(status_code=502, detail="Gateway restart failed")

    return {"ok": True}


@router.post(
    "/rpc",
    summary="[Deprecated] Proxy RPC call to user's OpenClaw container",
    description=(
        "DEPRECATED: Use the WebSocket connection at /api/v1/ws with "
        "{type: 'req', id, method, params} messages instead. "
        "This HTTP fallback will be removed in a future release."
    ),
    deprecated=True,
    operation_id="container_rpc",
    responses={
        404: {"description": "No running container for this user"},
        502: {"description": "Gateway connection or RPC call failed"},
    },
)
async def container_rpc(
    body: RpcRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = auth.user_id

    # Look up container and discover task IP
    ecs_manager = get_ecs_manager()
    container, ip = await ecs_manager.resolve_running_container(user_id, db)
    if not container:
        raise HTTPException(
            status_code=404,
            detail="No running container. Subscribe to access the control panel.",
        )
    if not ip:
        raise HTTPException(status_code=502, detail="Container gateway is starting up")

    try:
        result = await _call_gateway_rpc(
            ip=ip,
            token=container.gateway_token,
            method=body.method,
            params=body.params,
        )
    except ConnectionRefusedError:
        logger.error("Gateway refused connection for user %s at %s", user_id, ip)
        raise HTTPException(status_code=502, detail="Container gateway is not responding")
    except TimeoutError:
        logger.error("Gateway timeout for user %s at %s", user_id, ip)
        raise HTTPException(status_code=502, detail="Container gateway timed out")
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from gateway for user %s: %s", user_id, e)
        raise HTTPException(status_code=502, detail="Invalid response from container gateway")
    except Exception as e:
        logger.error("RPC call failed for user %s: %s", user_id, e)
        raise HTTPException(status_code=502, detail="Gateway RPC call failed")

    return {"result": result}
