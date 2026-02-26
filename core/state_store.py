"""Temporary in-memory store for uploaded encrypted agent state.

When agent state tarballs exceed API Gateway's 32KB WebSocket frame limit,
the client uploads state via REST and sends a reference UUID over WebSocket.
The backend retrieves the state by reference before forwarding to the enclave.

Entries are single-use (deleted on retrieval) and expire after 60 seconds.
"""

import asyncio
import time
import uuid
from typing import Any, Dict, Optional

_store: Dict[str, Dict[str, Any]] = {}
_lock = asyncio.Lock()
_TTL_SECONDS = 60


async def store_state(payload: dict) -> str:
    """Store an encrypted state payload and return a reference UUID."""
    ref = str(uuid.uuid4())
    async with _lock:
        # Cleanup expired entries
        now = time.monotonic()
        expired = [k for k, v in _store.items() if now - v["created_at"] > _TTL_SECONDS]
        for k in expired:
            del _store[k]

        _store[ref] = {"payload": payload, "created_at": now}
    return ref


async def retrieve_state(ref: str) -> Optional[dict]:
    """Retrieve and delete an encrypted state payload by reference UUID.

    Returns None if not found or expired.
    """
    async with _lock:
        entry = _store.pop(ref, None)
    if entry is None:
        return None
    if time.monotonic() - entry["created_at"] > _TTL_SECONDS:
        return None
    return entry["payload"]
