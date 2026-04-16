"""Extract a running OpenClaw container's in-container config files to EFS.

CONTEXT
-------
Prior to the workspace-normalization fix, custom agents in prod had
`workspace: "/home/node/agents/<id>"` in openclaw.json — a container-local
path OUTSIDE the EFS mount at /home/node/.openclaw/. Anything OpenClaw
seeded or the user edited there lives only in ephemeral container
storage and is lost on container restart.

This script reads those files out of the running container via the
backend's existing GatewayConnectionPool (which handles the signed
device handshake) and writes them to EFS at the NEW location
(`workspaces/{agent_id}/{filename}`) BEFORE we patch openclaw.json.
The migration script then sees the files already present at the new
location and skips re-seeding.

USAGE
-----
Runs INSIDE the backend ECS task via execute-command:

    aws ecs execute-command --cluster <cluster> --task <backend-task-id> \\
        --container backend --interactive \\
        --command "/bin/sh -c 'cd /app && PYTHONPATH=/app uv run python /tmp/extract.py <owner_id>'"

Idempotent: skips files already present on EFS at the target location.

By default, dry-run. Add `--apply` as the second argument to actually write.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path

# Ensure /app is importable when run from /tmp
SCRIPT_DIR = Path(__file__).resolve().parent
APP_ROOT = Path("/app")
for p in (str(APP_ROOT), str(SCRIPT_DIR.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.containers import get_ecs_manager, get_gateway_pool, get_workspace  # noqa: E402

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


async def _rpc(pool, owner_id: str, ip: str, token: str, method: str, params: dict):
    return await pool.send_rpc(
        user_id=owner_id,
        req_id=str(uuid.uuid4()),
        method=method,
        params=params,
        ip=ip,
        token=token,
    )


async def extract_for_user(owner_id: str, apply: bool) -> None:
    """Extract config files for every agent in the user's running container."""
    ecs_manager = get_ecs_manager()
    workspace = get_workspace()
    pool = get_gateway_pool()

    container, ip = await ecs_manager.resolve_running_container(owner_id)
    if not container:
        log.error("no container for %s", owner_id)
        return
    if not ip:
        log.error("no IP for %s (gateway still starting?)", owner_id)
        return

    token = container["gateway_token"]
    user_root = workspace.user_path(owner_id)
    log.info("connected pool entry for %s @ %s", owner_id, ip)

    agents_resp = await _rpc(pool, owner_id, ip, token, "agents.list", {})
    agent_entries = agents_resp.get("agents", [])
    log.info("%d agents: %s", len(agent_entries), [a.get("id") for a in agent_entries])

    for agent in agent_entries:
        agent_id = agent.get("id")
        if not agent_id:
            continue

        # Skip main: its workspace was always the bare workspaces/ root,
        # which IS on EFS. Its SOUL.md / etc. already exist at
        # workspaces/SOUL.md and the migration script (Step 1) moves them
        # into workspaces/main/. Extracting main here would create a stale
        # duplicate at workspaces/main/ before Step 1 runs, then Step 1
        # would SKIP-on-exists and leave the original orphaned.
        if agent_id == "main":
            log.info("agent=main: skipping (data already on EFS, migration handles it)")
            continue

        target_dir = user_root / "workspaces" / agent_id
        log.info("agent=%s target=%s", agent_id, target_dir)

        try:
            files_resp = await _rpc(pool, owner_id, ip, token, "agents.files.list", {"agentId": agent_id})
        except Exception as exc:  # noqa: BLE001
            log.warning("  agents.files.list failed for %s: %s", agent_id, exc)
            continue

        present = {f.get("name") for f in files_resp.get("files", [])}
        log.info("  files visible to gateway: %s", sorted(present))

        for filename in CONFIG_ALLOWLIST:
            if filename not in present:
                continue

            dest = target_dir / filename
            if dest.exists():
                log.info("  SKIP (exists on EFS): %s", dest)
                continue

            try:
                get_resp = await _rpc(
                    pool, owner_id, ip, token,
                    "agents.files.get", {"agentId": agent_id, "name": filename},
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("  agents.files.get %s/%s failed: %s", agent_id, filename, exc)
                continue

            content = (get_resp.get("file") or {}).get("content")
            if content is None:
                log.warning("  empty content for %s/%s — skipping", agent_id, filename)
                continue

            size = len(content.encode("utf-8"))
            if apply:
                relpath = str(dest.relative_to(user_root))
                workspace.write_file(owner_id, relpath, content)
                log.info("  WROTE: %s (%d bytes)", dest, size)
            else:
                log.info("  WOULD WRITE: %s (%d bytes)", dest, size)


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0

    owner_id = sys.argv[1]
    apply = "--apply" in sys.argv[2:]

    log.info("owner_id=%s apply=%s", owner_id, apply)
    try:
        asyncio.run(extract_for_user(owner_id, apply))
    except Exception:
        log.exception("extract failed")
        return 1
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
