"""
OpenClaw configuration generator for per-user containers.

Generates openclaw.json with the provider block determined by the
user's signup choice (provider_choice). Each container gets a gateway
auth token so it can bind to LAN (required for Docker port mapping).
"""

import asyncio
import base64
import fcntl
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from core.config import settings

logger = logging.getLogger(__name__)

# Mirror of openclaw-version.json#tag at the repo root. Used as the
# `meta.lastTouchedVersion` value openclaw expects in our generated
# config (defeats `missing-meta-vs-last-good` auto-restore in
# src/config/io.observe-recovery.ts:425). Must match what openclaw
# itself self-writes (io.ts:879 uses `VERSION` from package.json).
# A drift test in tests/unit/containers/test_config.py asserts this
# stays in sync with openclaw-version.json on every CI run.
OPENCLAW_UPSTREAM_VERSION = "2026.4.23"


# ``fcntl.lockf`` serializes ACROSS processes but not across threads within a
# single Python process. ``ensure_node_paired_entry`` runs via
# ``asyncio.to_thread``, so two concurrent first-connects for different
# members of the same org land in different threads of the SAME process and
# can each acquire the fcntl lock simultaneously — the RMW then races and
# the last ``os.rename`` drops the other member's newly added device entry.
#
# Guard each owner's paired.json RMW with a dedicated ``threading.Lock``.
# One lock per owner keeps concurrency across different orgs; the guard
# dict itself is protected by a tiny master lock.
_PAIRED_THREAD_LOCKS: dict[str, threading.Lock] = {}
_PAIRED_THREAD_LOCKS_GUARD = threading.Lock()


def _paired_thread_lock(owner_id: str) -> threading.Lock:
    with _PAIRED_THREAD_LOCKS_GUARD:
        lock = _PAIRED_THREAD_LOCKS.get(owner_id)
        if lock is None:
            lock = threading.Lock()
            _PAIRED_THREAD_LOCKS[owner_id] = lock
        return lock


# =============================================================================
# Node device identity helpers
# =============================================================================


def _base64url_encode(data: bytes) -> str:
    """RFC 7515 base64url encoding (no padding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_node_device_identity() -> dict:
    """Generate a new Ed25519 keypair for node device identity.

    Returns dict with: device_id, public_key_b64, private_key_pem.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    raw_pub = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

    device_id = hashlib.sha256(raw_pub).hexdigest()
    public_key_b64 = _base64url_encode(raw_pub)
    private_key_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode("ascii")

    return {
        "device_id": device_id,
        "public_key_b64": public_key_b64,
        "private_key_pem": private_key_pem,
    }


def load_node_device_identity(private_key_pem: str) -> dict:
    """Reconstruct device identity from a stored PEM private key."""
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_pem_private_key,
    )

    private_key = load_pem_private_key(private_key_pem.encode("ascii"), password=None)
    raw_pub = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    device_id = hashlib.sha256(raw_pub).hexdigest()
    public_key_b64 = _base64url_encode(raw_pub)

    return {
        "device_id": device_id,
        "public_key_b64": public_key_b64,
        "private_key_pem": private_key_pem,
    }


def _build_node_paired_entry(device_id: str, public_key_b64: str) -> dict:
    """One `devices/paired.json` entry for the in-container node role."""
    now_ms = int(time.time() * 1000)
    return {
        "deviceId": device_id,
        "publicKey": public_key_b64,
        "role": "node",
        "roles": ["node"],
        "scopes": [],
        "approvedScopes": [],
        "createdAtMs": now_ms,
        "approvedAtMs": now_ms,
    }


def ensure_node_paired_entry(
    efs_mount_path: str,
    owner_id: str,
    device_id: str,
    public_key_b64: str,
) -> bool:
    """Idempotently append a ``node`` entry to ``<owner>/devices/paired.json``.

    OpenClaw's connect handler rejects role="node" handshakes whose
    ``device.id`` isn't in the container's trust store (the paired.json file
    under ``devices/``). Per-member desktop nodes each have a distinct
    Ed25519 key, so each distinct member's ``device.id`` must be registered
    here before its first handshake will succeed.

    This function is safe to call on every ``_load_node_key`` — it's a no-op
    if the ``device_id`` is already present. It's also safe to run
    concurrently for different members.

    **Locking (two layers):**

    - ``fcntl.lockf`` on a SIBLING file (``paired.json.lock``) serializes
      ACROSS processes. Not on ``paired.json`` itself because we rewrite
      via tempfile + ``rename``: an fcntl lock is bound to the inode, and
      rename replaces it — the lock on the old inode is orphaned while a
      concurrent writer opens the new inode and acquires an independent
      lock. The sibling lock file's inode never changes.

    - A per-owner ``threading.Lock`` serializes WITHIN the process. fcntl
      locks are process-scoped, not thread-scoped, so two asyncio-to-thread
      workers for different members of the same org could both pass
      ``fcntl.lockf`` simultaneously and race the RMW. Dropping this lock
      caused intermittent lost entries under concurrent onboarding.

    Both locks are acquired in the same order (thread → fcntl) so there's
    no deadlock potential — the process-scope lock is always taken first.

    Atomicity: the rewrite uses temp-file + rename to avoid leaving the
    file half-written if the process dies mid-write. The tempfile is
    chowned to uid/gid 1000 when running as root so the in-container
    OpenClaw agent (running as ``node``) can read it.

    Returns True if a new entry was added, False if it was already present.
    """
    paired_path = os.path.join(efs_mount_path, owner_id, "devices", "paired.json")
    paired_dir = os.path.dirname(paired_path)
    lock_path = paired_path + ".lock"
    os.makedirs(paired_dir, exist_ok=True)

    # Ensure the lock file exists (atomic create-or-open; no truncation).
    # This file is never written to — it's just an inode we can lock.
    lock_create_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    if os.getuid() == 0:
        try:
            os.chown(lock_path, 1000, 1000)
        except OSError:
            pass
    os.close(lock_create_fd)

    # Thread-local first (process-scoped fcntl can't see sibling threads),
    # then fcntl on the sibling lock file (for cross-process).
    with _paired_thread_lock(owner_id):
        lock_fd = None
        try:
            lock_fd = open(lock_path, "r+", encoding="utf-8")
            fcntl.lockf(lock_fd, fcntl.LOCK_EX)

            # Read the current paired.json (creating an empty dict if missing —
            # normally ensure_device_identities writes it at provision time
            # with the operator entry, but recovery paths may not have it).
            try:
                with open(paired_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except FileNotFoundError:
                content = ""
            entries = json.loads(content) if content.strip() else {}
            if not isinstance(entries, dict):
                logger.warning(
                    "paired.json for owner %s was not a dict (got %s); resetting",
                    owner_id,
                    type(entries).__name__,
                )
                entries = {}

            if device_id in entries:
                return False  # Already registered — no-op.

            entries[device_id] = _build_node_paired_entry(device_id, public_key_b64)

            fd, tmp_path = tempfile.mkstemp(dir=paired_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2)
                if os.getuid() == 0:
                    try:
                        os.chown(tmp_path, 1000, 1000)
                    except OSError:
                        pass
                os.rename(tmp_path, paired_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            logger.info(
                "Registered node device_id %s in paired.json for owner %s",
                device_id[:16],
                owner_id,
            )
            return True
        finally:
            if lock_fd:
                try:
                    fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                finally:
                    lock_fd.close()


def build_device_paired_json(
    node_device_id: str,
    node_public_key_b64: str,
    *,
    operator_entry: dict | None = None,
) -> str:
    """Build the combined `devices/paired.json` content for a per-user container.

    The paired.json file is the container's trust store — it maps each
    pre-approved device public key to a role + scope list, and the gateway
    rejects any connect request whose signed device identity isn't in this
    file (see OpenClaw 4.5 `handshake-auth-helpers.ts:244-281`).

    We write TWO entries per container by default:
    - **node** — the in-container agent's loopback identity (role: "node",
      no scopes — the node role has its own RPC surface, see
      `method-scopes.ts:NODE_ROLE_METHODS`).
    - **operator** — our Python backend's remote identity, used to make
      scoped RPCs like `sessions.list` and `chat.send` against the gateway
      from outside the container. Required since OpenClaw 4.5; without it
      the backend's self-declared scopes are silently cleared.

    The operator entry is passed in pre-built (from
    `core.crypto.operator_device.build_paired_operator_entry`) so this
    module doesn't need to import the crypto helpers. Pass `None` for
    pre-4.5 behavior (node-only paired.json).
    """
    entries = {
        node_device_id: _build_node_paired_entry(node_device_id, node_public_key_b64),
    }
    if operator_entry is not None:
        entries[operator_entry["deviceId"]] = operator_entry
    return json.dumps(entries, indent=2)


def _build_exec_policy() -> dict:
    """Backend-controlled exec approval policy.

    Returns the fragment that lives under ``tools`` (so callers can
    spread it into a ``tools`` dict). Kept as its own helper so the
    initial ``write_openclaw_config`` write and the ``PATCH /debug/
    provision`` deep-merge path produce identical policy — one source
    of truth.

    * security="allowlist": unknown commands are gated by an approval.
    * ask="on-miss": emit exec.approval.requested on allowlist misses
      so the in-chat approval card (#305) can decide.

    Without this OpenClaw defaults to security="deny", which blocks
    every exec call silently (openclaw/src/agents/exec-defaults.ts:98).
    """
    return {
        "exec": {
            "security": "allowlist",
            "ask": "on-miss",
        },
    }


def _provider_block(
    *,
    provider_choice: str,
    user_id: str,
    byo_provider: str | None,
) -> tuple[dict, dict, dict]:
    """Build (models.providers, agents.defaults.model, plugins.entries) for the
    user's signup choice.

    Per spec §4.2 (flat-fee pivot, 2026-04). API keys are NEVER embedded in
    openclaw.json — they're injected via ECS task definition secrets at task
    start. The Bedrock branch enables plugin discovery (the plugin queries
    bedrock:ListFoundationModels at startup) since we no longer ship a
    static per-tier catalog.

    Returns:
        ``(providers_config, default_model, plugin_entries)``.
    """
    if provider_choice == "chatgpt_oauth":
        # OpenClaw's openai-codex provider has no JSON config knob for the
        # auth.json directory — it reads the CODEX_HOME env var (default
        # ${HOME}/.codex). The per-user CODEX_HOME pointing at the EFS-staged
        # auth.json is set in ecs_manager._provider_environment_for_user().
        # We deliberately omit any provider entry so the bundled provider
        # plugin's defaults apply; writing an empty {} would still trip the
        # base-schema validator that requires `baseUrl` + `models`.
        return (
            {},
            {"primary": "openai-codex/gpt-5.5", "fallbacks": ["openai-codex/gpt-5.5"]},
            {},
        )
    if provider_choice == "byo_key":
        if byo_provider == "openai":
            return ({}, {"primary": "openai/gpt-5.4", "fallbacks": ["openai/gpt-5.4"]}, {})
        if byo_provider == "anthropic":
            return (
                {},
                {
                    "primary": "anthropic/claude-opus-4-7",
                    "fallbacks": ["anthropic/claude-sonnet-4-6"],
                },
                {},
            )
        raise ValueError(f"byo_provider must be 'openai' or 'anthropic' for byo_key, got {byo_provider!r}")
    if provider_choice == "bedrock_claude":
        return (
            {},
            {
                "primary": "amazon-bedrock/anthropic.claude-opus-4-7",
                "fallbacks": ["amazon-bedrock/anthropic.claude-sonnet-4-6"],
            },
            {
                "amazon-bedrock": {
                    "config": {
                        "discovery": {"enabled": True, "region": settings.AWS_REGION},
                    },
                },
            },
        )
    raise ValueError(f"Unknown provider_choice: {provider_choice!r}")


def build_openclaw_config_dict(
    *,
    user_id: str,
    gateway_token: str,
    provider_choice: str,
    byo_provider: str | None = None,
) -> dict:
    """Build the openclaw.json config dict for a per-user container.

    Pure (no I/O) so it can be unit-tested without filesystem mocks.

    The provider block (``models.providers`` + ``agents.defaults.model`` +
    ``plugins.entries``) is selected by ``provider_choice``. Everything
    else (gateway, agents.defaults, agents.list, memory, tools, hooks,
    channels, browser, nodeHost, update) is the same across signup paths
    — these are sections OpenClaw refuses to start without (e.g.
    ``gateway.mode``).
    """
    # Reprovision flows pull gateway_token from the existing container row;
    # legacy rows missing the field would silently write
    # `{"mode":"token","token":null}`, leaving the gateway unauthable.
    # Fail fast — caller must regenerate via secrets.token_urlsafe before retry.
    if not gateway_token:
        raise ValueError("gateway_token must be a non-empty string")

    providers_config, default_model, plugin_entries = _provider_block(
        provider_choice=provider_choice,
        user_id=user_id,
        byo_provider=byo_provider,
    )

    # Token auth — shared secret between backend and container.
    # Trusted-proxy mode explicitly blocks loopback connections (OpenClaw #17761),
    # which breaks the local agent's ability to call its own gateway for node
    # discovery and other internal RPCs. Token mode works for both our backend
    # (VPC -> container) and the in-container agent (loopback -> container).
    # Network isolation (private VPC subnet) provides the transport boundary;
    # user identity is implicit since each container is per-user.
    auth = {
        "mode": "token",
        "token": gateway_token,
    }

    config = {
        # Synthetic meta defeats openclaw's "missing-meta-vs-last-good"
        # auto-restore in src/config/io.observe-recovery.ts:425. That
        # check treats every backend overwrite as anomalous (openclaw
        # adds its own meta after first boot; our overwrites strip it),
        # silently restoring from .bak and clobbering whatever we wrote.
        # Use the real upstream version so warnIfConfigFromFuture
        # (io.ts:885) parses it as semver and short-circuits cleanly.
        "meta": {"lastTouchedVersion": OPENCLAW_UPSTREAM_VERSION},
        "gateway": {
            "mode": "local",
            "bind": "lan",
            "auth": auth,
            "trustedProxies": ["10.0.0.0/8", "127.0.0.1", "::1"],
            "controlUi": {
                "enabled": False,
            },
            "http": {
                "endpoints": {
                    "chatCompletions": {"enabled": False},
                },
            },
        },
        "models": {
            "providers": providers_config,
        },
        "agents": {
            "defaults": {
                "model": default_model,
                # v2026.4.22's zod-schema.agent-defaults.ts requires these
                # three fields (no .optional()). Empty objects validate
                # because every nested field IS optional. Required for
                # config validation; behavior unchanged.
                "embeddedHarness": {},
                "contextLimits": {},
                "heartbeat": {},
                "workspace": "/home/node/.openclaw/workspaces",
                # Pin the embedding provider to Bedrock for every auth path:
                # the per-user task role has bedrock:InvokeModel via IAM, so
                # this works whether the user signed in with ChatGPT, brought
                # their own OpenAI/Anthropic key, or chose Bedrock-Claude.
                # Without an explicit provider, openclaw defaults to "local"
                # (GGUF file we don't ship) and qmd's first embed cycle hangs
                # ~3min (120s timeout + 60s backoff) before failing —
                # observed in the 02:21 cold-start trace.
                "memorySearch": {
                    "enabled": True,
                    "provider": "bedrock",
                    "model": "amazon.titan-embed-text-v2:0",
                },
                "llm": {
                    "idleTimeoutSeconds": 300,
                },
                # verboseDefault="full" keeps tool result/partialResult in
                # agent events so the frontend can show tool input + output.
                # OpenClaw defaults to "off" which strips those fields before
                # they reach our WebSocket subscriber.
                "verboseDefault": "full",
            },
            # Per-agent settings. reasoningDefault is not allowed in
            # agents.defaults (see openclaw zod-schema.agent-defaults.ts), so
            # we declare the implicit "main" agent explicitly here to opt it
            # into real-time thinking streams. User-created agents inherit it
            # via AgentCreateForm passing reasoningDefault: "stream" on
            # agents.create.
            "list": [
                {
                    "id": "main",
                    "default": True,
                    "reasoningDefault": "stream",
                    # Absolute path so path.resolve() returns it unchanged
                    # regardless of process cwd (agent exec tools run with
                    # cwd=workspaceDir, which breaks relative resolution).
                    "workspace": "/home/node/.openclaw/workspaces/main",
                },
            ],
        },
        "memory": {
            "backend": "qmd",
            "citations": "auto",
            "qmd": {
                "command": "/home/node/.npm-global/bin/qmd",
                "includeDefaultMemory": True,
                "searchMode": "search",
                "update": {
                    "interval": "5m",
                    "debounceMs": 15000,
                    "onBoot": True,
                    "waitForBootSync": False,
                },
                "limits": {
                    "maxResults": 6,
                    "timeoutMs": 4000,
                },
                "scope": {
                    "default": "deny",
                    "rules": [
                        {"action": "allow", "match": {"chatType": "direct"}},
                    ],
                },
            },
        },
        "tools": {
            "profile": "full",
            # Default-deny both canvas and nodes. node_proxy.py toggles
            # "nodes" back to enabled dynamically when a desktop node
            # pairs, and back to denied when the last one disconnects.
            # Leaving nodes always-allowed here would expose the tool
            # even to users without the desktop app.
            "deny": ["canvas", "nodes"],
            **_build_exec_policy(),
            "web": {
                "fetch": {"enabled": True},
            },
            "media": {
                "image": {"enabled": True},
                "audio": {"enabled": False},
                "video": {"enabled": False},
            },
        },
        "skills": {
            "install": {
                "nodeManager": "npm",
            },
        },
        "hooks": {
            "internal": {
                "entries": {
                    "command-logger": {"enabled": True},
                    "session-memory": {"enabled": True},
                },
            },
        },
        "plugins": {
            "slots": {},
            "entries": plugin_entries,
        },
        # Channels: we ship every supported provider as `enabled: true`
        # so the plugin is loaded into the gateway at startup.
        # OpenClaw's reload plan treats `channels.{id}` as a hot-reload
        # prefix ONLY when the channel plugin is already running — on
        # the very first enable of a never-before-loaded channel it
        # escalates to a full gateway restart (~6 min on Fargate).
        # Shipping the plugins hot at provision time means every
        # subsequent token/account change is a fast per-channel
        # restart, not a gateway restart. Plugins with no `accounts`
        # entries sit idle safely.
        "channels": {
            "telegram": {
                "enabled": True,
                "dmPolicy": "pairing",
            },
            "discord": {
                "enabled": True,
                "dmPolicy": "pairing",
            },
            "slack": {
                "enabled": True,
                "dmPolicy": "pairing",
            },
        },
        "session": {
            "dmScope": "per-account-channel-peer",
        },
        "web": {
            "enabled": True,
        },
        "browser": {
            # Enables OpenClaw's browser tool. Default profile is `user`
            # which attaches to the user's real signed-in Chrome 144+ via
            # chrome-devtools-mcp + CDP. No Chromium bundled in the
            # container image.
            "enabled": True,
            "defaultProfile": "user",
            "profiles": {
                "user": {
                    "driver": "existing-session",
                    # Required since OpenClaw bumped its config schema —
                    # `browser.profiles.*.color` is now a required string.
                    # Surfaces in the OpenClaw UI as the profile chip.
                    "color": "#0066FF",
                },
            },
        },
        "nodeHost": {
            "browserProxy": {
                # Auto-route browser tool calls to the paired desktop
                # node. The Isol8 Tauri app runs the sidecar
                # (openclaw/extensions/browser + chrome-devtools-mcp)
                # colocated with Chrome on the user's Mac.
                "enabled": True,
            },
        },
        "update": {"checkOnStart": False},
    }

    return config


async def write_openclaw_config(
    *,
    config_path: Path,
    gateway_token: str,
    provider_choice: str,
    user_id: str,
    byo_provider: str | None = None,
) -> None:
    """Write the user's openclaw.json with the full container config.

    Per spec §4.2 (flat-fee pivot, 2026-04). Tier gating is removed —
    one config shape per ``provider_choice``. The OPENAI/ANTHROPIC API
    keys are NEVER written into this file; they're injected via ECS
    task definition secrets at task start.

    Args:
        config_path: Where on disk to write the JSON file. Parent dirs
            are created if missing.
        gateway_token: Shared secret for container auth. Required because
            ``gateway.auth.mode = "token"``.
        provider_choice: One of ``"chatgpt_oauth"``, ``"byo_key"``,
            ``"bedrock_claude"``.
        user_id: Owner ID; surfaced for completeness — the chatgpt_oauth
            path no longer carries it into the config (auth.json directory
            is set via the CODEX_HOME env var on the per-user ECS task).
        byo_provider: ``"openai"`` or ``"anthropic"`` — required when
            ``provider_choice == "byo_key"``.

    Raises:
        ValueError: when ``provider_choice`` is unknown or
            ``byo_provider`` is missing/invalid for ``byo_key``.
    """
    config = build_openclaw_config_dict(
        user_id=user_id,
        gateway_token=gateway_token,
        provider_choice=provider_choice,
        byo_provider=byo_provider,
    )

    def _write() -> None:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2))

    await asyncio.to_thread(_write)


def write_mcporter_config(servers: dict | None = None) -> str:
    """Generate a mcporter.json config string.

    Args:
        servers: Optional dict of server entries. Defaults to empty.

    Returns:
        JSON string of the mcporter config.
    """
    config = {"servers": servers or {}}
    return json.dumps(config, indent=2)


def merge_openclaw_config(
    existing_config: dict,
    updates: dict,
) -> dict:
    """Merge partial updates into an existing openclaw.json config dict.

    Performs a shallow merge at the top-level section keys (gateway, models,
    agents, tools, browser, update). Nested dicts within each section are
    deep-merged.

    Args:
        existing_config: Current openclaw.json as dict.
        updates: Partial config dict with sections to update.

    Returns:
        Merged config dict.
    """
    merged = dict(existing_config)
    for key, value in updates.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


async def read_openclaw_config_from_efs(owner_id: str) -> dict | None:
    """Read and parse openclaw.json directly from EFS.

    Works even when the container is scaled down (no gateway RPC needed).
    Returns None if the file doesn't exist yet.
    """
    import asyncio
    import json
    import os

    from core.config import settings

    config_path = os.path.join(settings.EFS_MOUNT_PATH, owner_id, "openclaw.json")
    if not os.path.exists(config_path):
        return None

    def _read():
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "Failed to parse openclaw.json for owner %s: %s",
                owner_id,
                e,
            )
            return None

    return await asyncio.to_thread(_read)
