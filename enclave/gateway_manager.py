"""
OpenClaw Gateway Manager for Nitro Enclave.

Manages the persistent OpenClaw gateway process (`openclaw gateway run`)
and per-request workspace directories. Replaces per-request subprocess
spawning with a long-lived gateway that supports concurrent requests
and memory search (vector embeddings).

Thread safety:
  - start/stop/ensure_running/update_credentials: protected by self._lock
  - prepare_workspace/collect_workspace: lock-free (per-request UUID dirs)
"""

import io
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)

# Default gateway port (loopback only, inside enclave)
DEFAULT_GATEWAY_PORT = 18789

# Default workspace base directory (tmpfs inside enclave)
DEFAULT_WORKSPACE = "/tmp/openclaw/gateway-workspace"

# Health check polling interval during startup
_HEALTH_POLL_INTERVAL = 0.5

# Maximum time to wait for gateway to become healthy on startup
_STARTUP_TIMEOUT = 30.0

# Maximum restart attempts in ensure_running()
_MAX_RESTART_ATTEMPTS = 3


class GatewayUnavailableError(Exception):
    """Raised when the gateway cannot be started or recovered."""


class GatewayManager:
    """Manages the OpenClaw gateway lifecycle and per-request workspaces."""

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

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def start(self, env: dict) -> None:
        """
        Start the OpenClaw gateway process.

        Called once at enclave startup, before any request threads.

        Args:
            env: Environment variables dict (must include AWS credentials).
        """
        with self._lock:
            if self._started and self._process and self._process.poll() is None:
                print("[Gateway] Already running, skipping start", flush=True)
                return

            # Create workspace directory
            self._workspace.mkdir(parents=True, exist_ok=True)
            agents_dir = self._workspace / "agents"
            agents_dir.mkdir(exist_ok=True)

            # Write openclaw.json config for the gateway
            self._write_config(env)

            # Write AWS credentials file for the gateway's AWS SDK
            self._write_credentials(env)

            # Build process environment
            proc_env = os.environ.copy()
            proc_env.update(env)
            proc_env["OPENCLAW_STATE_DIR"] = str(self._workspace)
            proc_env["OPENCLAW_HOME"] = str(self._workspace)
            # Ensure AWS SDK finds credentials file
            proc_env["AWS_SHARED_CREDENTIALS_FILE"] = str(self._workspace / ".aws" / "credentials")

            # Set proxy env vars for enclave networking.
            # Inside the enclave, vsock_tcp_bridge.py listens on 127.0.0.1:3128
            # and tunnels CONNECT requests through vsock to the parent's proxy.
            # The gateway's Node.js process needs these to reach Bedrock APIs.
            bridge_port = os.environ.get("VSOCK_BRIDGE_PORT", "3128")
            if int(bridge_port) > 0:
                proxy_url = f"http://127.0.0.1:{bridge_port}"
                proc_env["HTTP_PROXY"] = proxy_url
                proc_env["HTTPS_PROXY"] = proxy_url
                proc_env["http_proxy"] = proxy_url
                proc_env["https_proxy"] = proxy_url

            # Start gateway process
            # NOTE: --auth flag only accepts "token" or "password" on CLI.
            # Auth mode "none" is set in openclaw.json gateway config instead.
            cmd = [
                "openclaw",
                "gateway",
                "run",
                "--port",
                str(self._port),
                "--bind",
                "loopback",
                "--allow-unconfigured",
            ]

            print(f"[Gateway] Starting: {' '.join(cmd)}", flush=True)
            print(f"[Gateway] Workspace: {self._workspace}", flush=True)

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=proc_env,
                cwd=str(self._workspace),
            )

            # Start log drain thread
            threading.Thread(
                target=self._drain_output,
                args=(self._process.stdout,),
                daemon=True,
            ).start()

            # Poll until healthy
            start_time = time.monotonic()
            while time.monotonic() - start_time < _STARTUP_TIMEOUT:
                if self._process.poll() is not None:
                    raise GatewayUnavailableError(
                        f"Gateway process exited with code {self._process.returncode} during startup"
                    )
                if self._check_health():
                    self._started = True
                    print(
                        f"[Gateway] Started on port {self._port} (took {time.monotonic() - start_time:.1f}s)",
                        flush=True,
                    )
                    return
                time.sleep(_HEALTH_POLL_INTERVAL)

            # Timeout — kill the process
            self._kill_process()
            raise GatewayUnavailableError(f"Gateway failed to become healthy within {_STARTUP_TIMEOUT}s")

    def stop(self) -> None:
        """Stop the gateway process gracefully."""
        with self._lock:
            self._stop_internal()

    def _stop_internal(self) -> None:
        """Internal stop (caller must hold self._lock)."""
        if self._process is None:
            return

        print("[Gateway] Stopping...", flush=True)

        # SIGTERM first
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
            print("[Gateway] Stopped gracefully", flush=True)
        except subprocess.TimeoutExpired:
            # Force kill
            self._kill_process()
            print("[Gateway] Force killed", flush=True)

        self._process = None
        self._started = False

    def _kill_process(self) -> None:
        """Force kill the gateway process."""
        if self._process:
            try:
                self._process.kill()
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
            # 4xx errors mean the server is up (just rejected our OPTIONS)
            return e.code < 500
        except Exception:
            return False

    def ensure_running(self, env: dict) -> None:
        """
        Ensure the gateway is running and healthy. Restart if needed.

        Thread-safe: acquires self._lock.

        Args:
            env: Environment variables dict (AWS credentials).

        Raises:
            GatewayUnavailableError: If gateway cannot be recovered after retries.
        """
        # Fast path: already healthy (no lock needed for read)
        if self._started and self._process and self._process.poll() is None:
            if self._check_health():
                return

        with self._lock:
            # Re-check under lock
            if self._started and self._process and self._process.poll() is None:
                if self._check_health():
                    return

            # Need to restart
            for attempt in range(1, _MAX_RESTART_ATTEMPTS + 1):
                print(
                    f"[Gateway] Restart attempt {attempt}/{_MAX_RESTART_ATTEMPTS}",
                    flush=True,
                )
                self._stop_internal()
                try:
                    # Release lock temporarily for start (which acquires it)
                    # But we're already inside the lock, so call internal start
                    self._start_internal(env)
                    return
                except GatewayUnavailableError:
                    print(f"[Gateway] Restart attempt {attempt} failed", flush=True)

            raise GatewayUnavailableError(f"Gateway failed to recover after {_MAX_RESTART_ATTEMPTS} attempts")

    def _start_internal(self, env: dict) -> None:
        """Internal start (caller must hold self._lock or be in start())."""
        # Create workspace directory
        self._workspace.mkdir(parents=True, exist_ok=True)
        agents_dir = self._workspace / "agents"
        agents_dir.mkdir(exist_ok=True)

        self._write_config(env)
        self._write_credentials(env)

        proc_env = os.environ.copy()
        proc_env.update(env)
        proc_env["OPENCLAW_STATE_DIR"] = str(self._workspace)
        proc_env["OPENCLAW_HOME"] = str(self._workspace)
        proc_env["AWS_SHARED_CREDENTIALS_FILE"] = str(self._workspace / ".aws" / "credentials")

        # Set proxy env vars for enclave networking (same as start())
        bridge_port = os.environ.get("VSOCK_BRIDGE_PORT", "3128")
        if int(bridge_port) > 0:
            proxy_url = f"http://127.0.0.1:{bridge_port}"
            proc_env["HTTP_PROXY"] = proxy_url
            proc_env["HTTPS_PROXY"] = proxy_url
            proc_env["http_proxy"] = proxy_url
            proc_env["https_proxy"] = proxy_url

        cmd = [
            "openclaw",
            "gateway",
            "run",
            "--port",
            str(self._port),
            "--bind",
            "loopback",
            "--allow-unconfigured",
        ]

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
                raise GatewayUnavailableError(f"Gateway exited with code {self._process.returncode}")
            if self._check_health():
                self._started = True
                print(
                    f"[Gateway] Restarted on port {self._port} (took {time.monotonic() - start_time:.1f}s)",
                    flush=True,
                )
                return
            time.sleep(_HEALTH_POLL_INTERVAL)

        self._kill_process()
        raise GatewayUnavailableError("Gateway failed to become healthy on restart")

    def update_credentials(self, credentials: dict) -> None:
        """
        Update AWS credentials for the gateway.

        Thread-safe: acquires self._lock.

        Args:
            credentials: Dict with access_key_id, secret_access_key, session_token.
        """
        with self._lock:
            self._write_credentials(credentials)
            print("[Gateway] Credentials updated", flush=True)

    def prepare_workspace(self, tarball_bytes: bytes, agent_name: str) -> Tuple[str, str]:
        """
        Unpack an agent tarball into the gateway workspace.

        Thread-safe WITHOUT lock: each request gets a unique UUID directory.

        Args:
            tarball_bytes: Gzip tarball of agent state.
            agent_name: Original agent name in the tarball.

        Returns:
            Tuple of (request_id, workspace_path).
        """
        request_id = uuid4().hex[:16]

        # Unpack tarball to a temporary directory first
        tmp_dir = Path(tempfile.mkdtemp(dir=str(self._workspace), prefix="unpack_"))
        try:
            self._unpack_tarball(tarball_bytes, tmp_dir)

            # Move agents/{agent_name}/ → workspace/agents/{request_id}/
            source = tmp_dir / "agents" / agent_name
            target = self._workspace / "agents" / request_id

            if source.exists() and source.is_dir():
                shutil.move(str(source), str(target))
            else:
                # Tarball might have a flat structure — move everything
                target.mkdir(parents=True, exist_ok=True)
                for item in tmp_dir.iterdir():
                    if item.name == "agents":
                        # Check for any agent dir inside
                        for agent_dir in item.iterdir():
                            shutil.move(str(agent_dir), str(target))
                        break
                else:
                    # Flat structure: copy all to target
                    for item in tmp_dir.iterdir():
                        dest = target / item.name
                        if item.is_dir():
                            shutil.copytree(str(item), str(dest))
                        else:
                            shutil.copy2(str(item), str(dest))

            # Copy openclaw.json from tarball if present (agent-specific config)
            tarball_config = tmp_dir / "openclaw.json"
            if tarball_config.exists():
                # Merge agent-specific settings (like SOUL.md path) but keep
                # gateway-level config (models, tools, memorySearch)
                pass  # Gateway config takes precedence

            print(
                f"[Gateway] Prepared workspace: agents/{request_id}/ (from {agent_name})",
                flush=True,
            )
            return request_id, str(self._workspace)

        finally:
            # Clean up temp unpack directory
            shutil.rmtree(str(tmp_dir), ignore_errors=True)

    def collect_workspace(self, request_id: str, agent_name: str) -> bytes:
        """
        Pack the request workspace back into a tarball and clean up.

        Thread-safe WITHOUT lock: operates on unique request_id directory.

        Args:
            request_id: The UUID assigned during prepare_workspace().
            agent_name: The original agent name to restore in the tarball.

        Returns:
            Gzip tarball bytes of the updated agent state.
        """
        request_dir = self._workspace / "agents" / request_id

        if not request_dir.exists():
            raise FileNotFoundError(f"Workspace directory not found: agents/{request_id}/")

        # Create temp dir with correct structure: agents/{agent_name}/
        tmp_dir = Path(tempfile.mkdtemp(dir=str(self._workspace), prefix="pack_"))
        try:
            target = tmp_dir / "agents" / agent_name
            shutil.move(str(request_dir), str(target))

            # Copy gateway openclaw.json into tarball (minimal, for compatibility)
            gateway_config = self._workspace / "openclaw.json"
            if gateway_config.exists():
                shutil.copy2(str(gateway_config), str(tmp_dir / "openclaw.json"))

            tarball_bytes = self._pack_directory(tmp_dir)

            print(
                f"[Gateway] Collected workspace: agents/{request_id}/ → {len(tarball_bytes)} bytes (as {agent_name})",
                flush=True,
            )
            return tarball_bytes

        finally:
            # Clean up
            shutil.rmtree(str(tmp_dir), ignore_errors=True)
            # Also ensure request dir is gone (may have been moved)
            if request_dir.exists():
                shutil.rmtree(str(request_dir), ignore_errors=True)

    def _write_config(self, env: dict) -> None:
        """Write openclaw.json config for the gateway."""
        region = env.get("AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))
        brave_key = env.get("BRAVE_API_KEY", os.environ.get("BRAVE_API_KEY", ""))

        config = {
            "gateway": {"mode": "local", "auth": {"mode": "none"}},
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
                                "cost": {
                                    "input": 0,
                                    "output": 0,
                                    "cacheRead": 0,
                                    "cacheWrite": 0,
                                },
                            },
                        ],
                    },
                },
                "bedrockDiscovery": {"enabled": False},
            },
            "agents": {
                "defaults": {
                    "memorySearch": {
                        "enabled": True,
                        "provider": "bedrock",
                        "model": "amazon.nova-2-multimodal-embeddings-v1:0",
                        "sources": ["memory", "sessions"],
                        "store": {
                            "driver": "sqlite",
                            "path": str(self._workspace / "agents" / "{agentId}" / "memory" / "index.sqlite"),
                        },
                        "sync": {
                            "watch": False,
                            "onSessionStart": True,
                            "onSearch": True,
                        },
                        "query": {
                            "maxResults": 20,
                            "hybrid": {
                                "enabled": True,
                                "vectorWeight": 0.7,
                                "textWeight": 0.3,
                            },
                        },
                    },
                },
            },
            "tools": {
                "web": {
                    "search": {
                        "enabled": bool(brave_key),
                        "provider": "brave",
                    },
                    "fetch": {"enabled": True},
                },
                "media": {
                    "image": {"enabled": False},
                    "audio": {"enabled": False},
                    "video": {"enabled": False},
                },
            },
            "browser": {"enabled": False},
        }

        config_path = self._workspace / "openclaw.json"
        config_path.write_text(json.dumps(config, indent=2))
        print(f"[Gateway] Wrote config to {config_path}", flush=True)

    def _write_credentials(self, env: dict) -> None:
        """Write AWS credentials to INI file for the gateway's AWS SDK."""
        access_key = env.get("AWS_ACCESS_KEY_ID", "")
        secret_key = env.get("AWS_SECRET_ACCESS_KEY", "")
        session_token = env.get("AWS_SESSION_TOKEN", "")
        region = env.get("AWS_REGION", env.get("AWS_DEFAULT_REGION", "us-east-1"))

        if not access_key or not secret_key:
            return

        creds_dir = self._workspace / ".aws"
        creds_dir.mkdir(parents=True, exist_ok=True)

        # Write credentials file
        creds_content = f"[default]\naws_access_key_id = {access_key}\naws_secret_access_key = {secret_key}\n"
        if session_token:
            creds_content += f"aws_session_token = {session_token}\n"

        (creds_dir / "credentials").write_text(creds_content)

        # Write config file with region
        config_content = f"[default]\nregion = {region}\n"
        (creds_dir / "config").write_text(config_content)

    def _unpack_tarball(self, tarball_bytes: bytes, target_dir: Path) -> None:
        """Unpack a gzip tarball to a directory."""
        target_dir.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO(tarball_bytes)
        with tarfile.open(fileobj=buffer, mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    raise ValueError(f"Unsafe path in tarball: {member.name}")
            tar.extractall(target_dir)

    def _pack_directory(self, directory: Path) -> bytes:
        """Pack a directory into a gzip tarball."""
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for item in directory.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(directory)
                    tar.add(item, arcname=str(arcname))
        buffer.seek(0)
        return buffer.read()

    @staticmethod
    def _drain_output(pipe) -> None:
        """Drain subprocess stdout/stderr to enclave logs."""
        try:
            for line in pipe:
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    print(f"[Gateway] {text}", flush=True)
        except Exception:
            pass
