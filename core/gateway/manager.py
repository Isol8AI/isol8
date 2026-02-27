"""
OpenClaw Gateway Manager for EC2.

Manages the persistent OpenClaw gateway process (`openclaw gateway run`)
and per-agent workspace directories on disk. Agent state is stored as
plain files — no encryption, no tarballs.

Thread safety:
  - start/stop/ensure_running: protected by self._lock
  - create_agent_workspace/delete_agent_workspace: lock-free (per-agent dirs)
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default gateway port (loopback only)
DEFAULT_GATEWAY_PORT = 18789

# Default workspace directory (persistent EBS on EC2)
DEFAULT_WORKSPACE = "/var/lib/isol8/gateway-workspace"

# Health check polling interval during startup
_HEALTH_POLL_INTERVAL = 0.5

# Maximum time to wait for gateway to become healthy on startup.
# Cold Node.js startup takes ~35s (module loading, JIT).
_STARTUP_TIMEOUT = 90.0

# Maximum restart attempts in ensure_running()
_MAX_RESTART_ATTEMPTS = 3

# Watchdog interval — how often to check if the gateway process is alive.
_WATCHDOG_INTERVAL = 30.0


class GatewayUnavailableError(Exception):
    """Raised when the gateway cannot be started or recovered."""


class GatewayManager:
    """Manages the OpenClaw gateway lifecycle and per-agent workspaces on disk."""

    def __init__(
        self,
        port: int = DEFAULT_GATEWAY_PORT,
        workspace: str = DEFAULT_WORKSPACE,
    ):
        self._port = port
        self._workspace = Path(workspace)
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._started = False
        self._env: Optional[dict] = None
        self._watchdog: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    @property
    def workspace_path(self) -> Path:
        return self._workspace

    def start(self, env: dict) -> None:
        """Start the OpenClaw gateway process."""
        with self._lock:
            if self._started and self._process and self._process.poll() is None:
                logger.info("Gateway already running, skipping start")
                return
            self._start_internal(env)
            self._start_watchdog()

    def stop(self) -> None:
        """Stop the gateway process gracefully."""
        with self._lock:
            self._stop_internal()

    def _stop_internal(self) -> None:
        """Internal stop (caller must hold self._lock)."""
        if self._process is None:
            return

        logger.info("Stopping gateway...")
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
            logger.info("Gateway stopped gracefully")
        except (ProcessLookupError, PermissionError):
            logger.info("Gateway process already gone")
        except subprocess.TimeoutExpired:
            self._kill_process()
            logger.info("Gateway force killed")

        self._process = None
        self._started = False

    def _kill_process(self) -> None:
        """Force kill the gateway process."""
        if self._process:
            try:
                self._process.kill()
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self._process.wait(timeout=2)
            except Exception:
                pass

    def is_healthy(self) -> bool:
        """Check if the gateway is running and responsive."""
        if not self._started or self._process is None:
            return False
        if self._process.poll() is not None:
            return False
        return self._check_health()

    def _check_health(self) -> bool:
        """HTTP health check against the gateway."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/chat/completions",
                method="OPTIONS",
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status < 500
        except urllib.error.HTTPError as e:
            return e.code < 500
        except Exception:
            return False

    def ensure_running(self, env: dict) -> None:
        """Ensure the gateway is running and healthy, restart if needed."""
        self._env = env

        # Fast path: process alive and healthy
        if self._started and self._process and self._process.poll() is None:
            if self._check_health():
                return

        with self._lock:
            # Re-check under lock
            if self._started and self._process and self._process.poll() is None:
                if self._check_health():
                    return

            for attempt in range(1, _MAX_RESTART_ATTEMPTS + 1):
                logger.info("Gateway restart attempt %d/%d", attempt, _MAX_RESTART_ATTEMPTS)
                self._stop_internal()
                try:
                    self._start_internal(env)
                    self._start_watchdog()
                    return
                except GatewayUnavailableError:
                    logger.warning("Gateway restart attempt %d failed", attempt)

            raise GatewayUnavailableError(f"Gateway failed to recover after {_MAX_RESTART_ATTEMPTS} attempts")

    def _start_internal(self, env: dict) -> None:
        """Internal start (caller must hold self._lock or be in start())."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        agents_dir = self._workspace / "agents"
        agents_dir.mkdir(exist_ok=True)

        self._write_config(env)

        proc_env = os.environ.copy()
        proc_env.update(env)
        proc_env["OPENCLAW_STATE_DIR"] = str(self._workspace)
        proc_env["OPENCLAW_HOME"] = str(self._workspace)

        # On EC2, IAM role credentials are available via instance metadata.
        # No credential file management needed — the AWS SDK picks them up automatically.

        cmd = [
            "openclaw",
            "gateway",
            "run",
            "--port",
            str(self._port),
            "--bind",
            "loopback",
            "--allow-unconfigured",
            "--verbose",
        ]

        logger.info("Starting gateway: %s", " ".join(cmd))
        logger.info("Gateway workspace: %s", self._workspace)

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=proc_env,
            cwd=str(self._workspace),
        )

        threading.Thread(
            target=self._drain_output,
            args=(self._process.stdout,),
            daemon=True,
        ).start()

        start_time = time.monotonic()
        while time.monotonic() - start_time < _STARTUP_TIMEOUT:
            if self._process.poll() is not None:
                raise GatewayUnavailableError(
                    f"Gateway exited with code {self._process.returncode}"
                )
            if self._check_health():
                self._started = True
                self._env = env
                elapsed = time.monotonic() - start_time
                logger.info("Gateway started on port %d (took %.1fs)", self._port, elapsed)
                return
            time.sleep(_HEALTH_POLL_INTERVAL)

        self._kill_process()
        raise GatewayUnavailableError(f"Gateway failed to become healthy within {_STARTUP_TIMEOUT}s")

    # =========================================================================
    # Agent workspace management
    # =========================================================================

    def create_agent_workspace(
        self,
        agent_id: str,
        soul_content: Optional[str] = None,
    ) -> Path:
        """
        Create a workspace directory for an agent.

        Args:
            agent_id: Unique agent identifier (UUID from DB).
            soul_content: Optional SOUL.md content for the agent.

        Returns:
            Path to the agent's workspace directory.
        """
        agent_dir = self._workspace / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        if soul_content:
            (agent_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")

        # Create standard subdirectories
        (agent_dir / "sessions").mkdir(exist_ok=True)
        (agent_dir / "memory").mkdir(exist_ok=True)

        logger.info("Created agent workspace: agents/%s/", agent_id)
        return agent_dir

    def delete_agent_workspace(self, agent_id: str) -> bool:
        """
        Delete an agent's workspace directory.

        Args:
            agent_id: Unique agent identifier.

        Returns:
            True if deleted, False if not found.
        """
        agent_dir = self._workspace / "agents" / agent_id
        workspace_link = self._workspace / f"workspace-{agent_id}"

        deleted = False
        if agent_dir.exists():
            shutil.rmtree(str(agent_dir), ignore_errors=True)
            deleted = True

        if workspace_link.is_symlink():
            workspace_link.unlink()
        elif workspace_link.exists():
            shutil.rmtree(str(workspace_link))

        if deleted:
            logger.info("Deleted agent workspace: agents/%s/", agent_id)
        return deleted

    def agent_workspace_exists(self, agent_id: str) -> bool:
        """Check if an agent workspace directory exists."""
        return (self._workspace / "agents" / agent_id).exists()

    def get_agent_id(self, agent_id: str) -> str:
        """Return the agent_id used as the gateway's x-openclaw-agent-id header."""
        return agent_id

    def update_soul_content(self, agent_id: str, soul_content: str) -> None:
        """Update an agent's SOUL.md file."""
        agent_dir = self._workspace / "agents" / agent_id
        if not agent_dir.exists():
            agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")

    # =========================================================================
    # Config
    # =========================================================================

    def _write_config(self, env: dict) -> None:
        """Write openclaw.json config for the gateway."""
        region = env.get("AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))
        brave_key = env.get("BRAVE_API_KEY", os.environ.get("BRAVE_API_KEY", ""))

        config = {
            "gateway": {
                "mode": "local",
                "auth": {"mode": "none"},
                "http": {
                    "endpoints": {
                        "chatCompletions": {"enabled": True},
                    },
                },
            },
            "models": {
                "providers": {
                    "amazon-bedrock": {
                        "baseUrl": f"https://bedrock-runtime.{region}.amazonaws.com",
                        "api": "bedrock-converse-stream",
                        "auth": "aws-sdk",
                        "models": [
                            {
                                "id": "us.anthropic.claude-opus-4-5-20251101-v1:0",
                                "name": "Claude Opus 4.5",
                                "contextWindow": 200000,
                                "maxTokens": 16384,
                                "reasoning": False,
                                "input": ["text", "image"],
                                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                            },
                        ],
                    },
                },
                "bedrockDiscovery": {"enabled": False},
            },
            "agents": {
                "defaults": {
                    "model": {
                        "primary": "amazon-bedrock/us.anthropic.claude-opus-4-5-20251101-v1:0",
                    },
                    "memorySearch": {
                        "enabled": True,
                        "provider": "bedrock",
                        "model": "amazon.nova-2-multimodal-embeddings-v1:0",
                        "sources": ["memory", "sessions"],
                        "store": {
                            "driver": "sqlite",
                            "path": str(self._workspace / "agents" / "{agentId}" / "memory" / "index.sqlite"),
                        },
                        "sync": {"watch": False, "onSessionStart": True, "onSearch": True},
                        "query": {
                            "maxResults": 20,
                            "hybrid": {"enabled": True, "vectorWeight": 0.7, "textWeight": 0.3},
                        },
                    },
                },
            },
            "tools": {
                "web": {
                    "search": {"enabled": bool(brave_key), "provider": "brave"},
                    "fetch": {"enabled": True},
                },
                "media": {"image": {"enabled": False}, "audio": {"enabled": False}, "video": {"enabled": False}},
            },
            "browser": {"enabled": False},
            "update": {"checkOnStart": False},
        }

        config_path = self._workspace / "openclaw.json"
        config_path.write_text(json.dumps(config, indent=2))
        logger.info("Wrote gateway config to %s", config_path)

    # =========================================================================
    # Watchdog & output drain
    # =========================================================================

    def _start_watchdog(self) -> None:
        """Start the watchdog thread if not already running."""
        if self._watchdog and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog.start()

    def _watchdog_loop(self) -> None:
        """Periodically check gateway health and restart if dead."""
        while True:
            time.sleep(_WATCHDOG_INTERVAL)
            try:
                if not self._started or self._process is None:
                    continue

                process_alive = self._process.poll() is None
                healthy = process_alive and self._check_health()

                if healthy:
                    continue

                if not process_alive:
                    logger.warning(
                        "Watchdog: gateway exited (code %s), restarting",
                        self._process.returncode,
                    )
                else:
                    logger.warning("Watchdog: gateway alive but unhealthy, restarting")

                env = self._env
                if not env:
                    logger.warning("Watchdog: no cached env, cannot restart")
                    continue

                with self._lock:
                    if self._process and self._process.poll() is None and self._check_health():
                        continue
                    self._stop_internal()
                    try:
                        self._start_internal(env)
                        logger.info("Watchdog: restart successful")
                    except GatewayUnavailableError as e:
                        logger.error("Watchdog: restart failed: %s", e)

            except Exception as e:
                logger.error("Watchdog: unexpected error: %s", e)

    @staticmethod
    def _drain_output(pipe) -> None:
        """Drain subprocess stdout/stderr to logs."""
        try:
            for line in pipe:
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.debug("[OpenClaw] %s", text)
        except Exception:
            pass
