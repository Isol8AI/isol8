"""Extract a running OpenClaw container's in-container config files to EFS.

CONTEXT
-------
Prior to the workspace-normalization fix, custom agents in prod had
`workspace: "/home/node/agents/<id>"` in openclaw.json — which resolves
to a container-local path OUTSIDE the EFS mount at /home/node/.openclaw/.
That means when OpenClaw seeds SOUL.md and siblings on agent creation,
they land in ephemeral container storage and are lost on container
restart. Any user edits via the (old) AgentFilesTab likewise lived only
in ephemeral storage.

This script reads those files out of the running container via the
OpenClaw gateway (`agents.files.get` RPC) and writes them to EFS at the
NEW location (`workspaces/{agent_id}/{filename}`) BEFORE we patch
openclaw.json. The migration script then sees the files already present
at the new location and skips re-seeding.

USAGE
-----
Run this INSIDE the backend ECS task via execute-command:

    aws ecs execute-command --cluster <cluster> --task <backend-task-id> \\
        --container backend --interactive \\
        --command "/bin/sh -c 'cd /app && python3 scripts/extract-ephemeral-config-files.py <owner_id>'"

Where `<owner_id>` is the user_id or org_id directory name under
/mnt/efs/users/.

The script is idempotent: if a file already exists on EFS at the target
location, it is NOT overwritten (preserves any already-migrated content).

DRY-RUN
-------
By default the script prints what it would do but does NOT write. Add
`--apply` as the second argument to actually write files.

    python3 scripts/extract-ephemeral-config-files.py <owner_id>           # dry run
    python3 scripts/extract-ephemeral-config-files.py <owner_id> --apply   # execute
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path

# Path setup so we can import backend modules when run from /app
SCRIPT_DIR = Path(__file__).resolve().parent
APP_ROOT = SCRIPT_DIR.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from websockets import connect as ws_connect  # noqa: E402

from core.containers import get_ecs_manager, get_workspace  # noqa: E402

GATEWAY_PORT = 18789
WS_TIMEOUT = 15

CONFIG_ALLOWLIST = [
    "SOUL.md",
    "MEMORY.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "AGENTS.md",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract-config")


async def _handshake(ws, token: str) -> None:
    """Complete OpenClaw gateway connect handshake (protocol 3.0).

    Mirrors the handshake in apps/backend/routers/container_rpc.py.
    """
    # Step 1: receive connect.challenge (sent unprompted by gateway)
    raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
    challenge = json.loads(raw)
    if challenge.get("event") != "connect.challenge":
        raise RuntimeError(f"Expected connect.challenge, got: {challenge.get('event', 'unknown')}")

    # Step 2: send connect request
    connect_msg = {
        "type": "req",
        "id": str(uuid.uuid4()),
        "method": "connect",
        "params": {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": "extract-ephemeral-config-files",
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
    resp_raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
    resp = json.loads(resp_raw)
    if not resp.get("ok"):
        err = resp.get("error", {}).get("message", "unknown error")
        raise RuntimeError(f"Gateway connect failed: {err}")


async def _rpc(ws, method: str, params: dict) -> dict:
    """Send an RPC request and return the payload."""
    req_id = str(uuid.uuid4())
    await ws.send(
        json.dumps(
            {
                "type": "req",
                "id": req_id,
                "method": method,
                "params": params,
            }
        )
    )
    # Skip broadcast events until our response arrives
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
        data = json.loads(raw)
        if data.get("type") == "res" and data.get("id") == req_id:
            if not data.get("ok"):
                err = data.get("error", {}).get("message", "unknown error")
                raise RuntimeError(f"RPC {method} failed: {err}")
            return data.get("payload", {})


async def extract_for_user(owner_id: str, apply: bool) -> None:
    """Extract config files for every agent in the user's running container."""
    ecs_manager = get_ecs_manager()
    workspace = get_workspace()

    container, ip = await ecs_manager.resolve_running_container(owner_id)
    if not container:
        log.error("no container for %s", owner_id)
        return
    if not ip:
        log.error("no IP for %s (gateway still starting?)", owner_id)
        return

    token = container["gateway_token"]
    log.info("connecting to %s at %s", owner_id, ip)

    user_root = workspace.user_path(owner_id)

    async with ws_connect(f"ws://{ip}:{GATEWAY_PORT}", open_timeout=WS_TIMEOUT, close_timeout=5) as ws:
        await _handshake(ws, token)
        log.info("handshake ok")

        agents_resp = await _rpc(ws, "agents.list", {})
        agent_entries = agents_resp.get("agents", [])
        log.info("found %d agents: %s", len(agent_entries), [a.get("id") for a in agent_entries])

        for agent in agent_entries:
            agent_id = agent.get("id")
            if not agent_id:
                continue

            target_dir = user_root / "workspaces" / agent_id
            log.info("agent=%s target=%s", agent_id, target_dir)

            try:
                files_resp = await _rpc(ws, "agents.files.list", {"agentId": agent_id})
            except RuntimeError as exc:
                log.warning("agents.files.list failed for %s: %s", agent_id, exc)
                continue

            files_present = {f.get("name") for f in files_resp.get("files", [])}
            log.info("  %d files visible to gateway: %s", len(files_present), sorted(files_present))

            for filename in CONFIG_ALLOWLIST:
                if filename not in files_present:
                    continue

                dest = target_dir / filename
                if dest.exists():
                    log.info("  SKIP (exists on EFS): %s", dest)
                    continue

                try:
                    get_resp = await _rpc(
                        ws,
                        "agents.files.get",
                        {"agentId": agent_id, "name": filename},
                    )
                except RuntimeError as exc:
                    log.warning("  agents.files.get %s/%s failed: %s", agent_id, filename, exc)
                    continue

                content = get_resp.get("file", {}).get("content")
                if content is None:
                    log.warning("  empty content for %s/%s — skipping", agent_id, filename)
                    continue

                if apply:
                    # Use the Workspace write helper so chown + chmod match the
                    # access-point convention (UID 1000).
                    relpath = str(dest.relative_to(user_root))
                    workspace.write_file(owner_id, relpath, content)
                    log.info("  WROTE: %s (%d bytes)", dest, len(content.encode("utf-8")))
                else:
                    log.info("  WOULD WRITE: %s (%d bytes)", dest, len(content.encode("utf-8")))


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0

    owner_id = sys.argv[1]
    apply = "--apply" in sys.argv[2:]

    log.info("owner_id=%s apply=%s", owner_id, apply)
    asyncio.run(extract_for_user(owner_id, apply))
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
