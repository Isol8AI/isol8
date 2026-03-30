"""Container recovery endpoint.

Single endpoint that inspects current container + gateway state
and dispatches the appropriate recovery action.
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

import websockets

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.containers import get_ecs_manager
from core.containers.ecs_manager import GATEWAY_PORT
from core.repositories import container_repo

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory per-owner lock to prevent concurrent recovery.
_recovery_locks: dict[str, asyncio.Lock] = {}


def _get_lock(owner_id: str) -> asyncio.Lock:
    if owner_id not in _recovery_locks:
        _recovery_locks[owner_id] = asyncio.Lock()
    return _recovery_locks[owner_id]


async def _call_gateway_rpc(ip: str, token: str, method: str, params: dict | None = None) -> dict:
    """Short-lived WebSocket RPC call to a gateway container."""
    uri = f"ws://{ip}:{GATEWAY_PORT}"
    async with websockets.connect(uri, open_timeout=5, close_timeout=2) as ws:
        challenge = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if challenge.get("event") != "connect.challenge":
            raise RuntimeError("Unexpected handshake message")

        req_id = str(uuid.uuid4())
        await ws.send(
            json.dumps(
                {
                    "type": "req",
                    "id": req_id,
                    "method": "connect",
                    "params": {"token": token},
                }
            )
        )
        connect_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if not connect_resp.get("payload", {}).get("ok"):
            raise RuntimeError("Handshake rejected")

        rpc_id = str(uuid.uuid4())
        await ws.send(
            json.dumps(
                {
                    "type": "req",
                    "id": rpc_id,
                    "method": method,
                    "params": params or {},
                }
            )
        )
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("type") == "res" and msg.get("id") == rpc_id:
                return msg.get("payload", {})


@router.post(
    "/recover",
    summary="Recover container or gateway",
    description=(
        "Inspects current container and gateway state, then takes the "
        "appropriate recovery action. Idempotent and safe to call repeatedly."
    ),
    operation_id="container_recover",
    responses={
        404: {"description": "No container for this user"},
    },
)
async def container_recover(
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)
    lock = _get_lock(owner_id)

    if lock.locked():
        return {
            "action": "already_recovering",
            "state": "RECOVERING",
            "reason": "Recovery already in progress",
        }

    async with lock:
        ecs_manager = get_ecs_manager()

        # 1. Try to resolve a running container
        container, ip = await ecs_manager.resolve_running_container(owner_id)

        if not container:
            container = await ecs_manager.get_service_status(owner_id)

        if not container:
            raise HTTPException(status_code=404, detail="No container found")

        status = container.get("status", "unknown")

        # 2. Container is stopped or error -> full re-provision
        if status in ("stopped", "error"):
            reason = container.get("last_error", f"Container is {status}")
            logger.info("Recovering owner %s: reprovision (status=%s)", owner_id, status)
            try:
                await ecs_manager.provision_user_container(owner_id)
            except Exception as e:
                logger.error("Recovery reprovision failed for %s: %s", owner_id, e)
                raise HTTPException(status_code=502, detail="Re-provisioning failed")
            return {
                "action": "reprovision",
                "state": "CONTAINER_DOWN",
                "reason": reason,
            }

        # 3. Container is running -> check gateway health
        token = container.get("gateway_token", "")
        if not ip:
            logger.warning("Owner %s: running container but no IP, reprovisioning", owner_id)
            try:
                await ecs_manager.provision_user_container(owner_id)
            except Exception:
                raise HTTPException(status_code=502, detail="Re-provisioning failed")
            return {
                "action": "reprovision",
                "state": "CONTAINER_DOWN",
                "reason": "Container running but unreachable",
            }

        # Try gateway health check
        try:
            health = await _call_gateway_rpc(ip, token, "health")
            if health.get("ok"):
                return {
                    "action": "none",
                    "state": "HEALTHY",
                    "reason": "System is healthy",
                }
        except Exception:
            pass  # Gateway is down, proceed to restart

        # 4. Gateway is down -> try restart via update.run RPC
        logger.info("Recovering owner %s: gateway restart", owner_id)
        try:
            await _call_gateway_rpc(ip, token, "update.run")
            return {
                "action": "gateway_restart",
                "state": "GATEWAY_DOWN",
                "reason": "Gateway not responding — restarting",
            }
        except Exception:
            logger.warning("Owner %s: gateway restart failed, escalating to reprovision", owner_id)
            await container_repo.update_error(owner_id, "Gateway restart failed — reprovisioning")
            try:
                await ecs_manager.provision_user_container(owner_id)
            except Exception:
                raise HTTPException(status_code=502, detail="Re-provisioning failed")
            return {
                "action": "reprovision",
                "state": "GATEWAY_DOWN",
                "reason": "Gateway restart failed — reprovisioning",
            }
