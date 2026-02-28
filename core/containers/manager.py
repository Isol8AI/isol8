"""
Docker container lifecycle manager for per-user OpenClaw instances.

Each user gets an isolated Docker container running `openclaw gateway run`.
Containers are mapped to unique ports in the 19000-19999 range and persist
their workspace via Docker named volumes.

Thread safety:
  - provision/stop/remove: protected by self._lock
  - get_container_port: lock-free (reads from cache dict)
"""

import logging
import os
import secrets
import threading
from typing import Optional

import docker
from docker.errors import DockerException, NotFound, APIError

from core.containers.config import write_openclaw_config

logger = logging.getLogger(__name__)

# Default OpenClaw gateway port inside each container (always the same internally)
_INTERNAL_GATEWAY_PORT = 18789

# Health check polling
_HEALTH_POLL_INTERVAL = 1.0
_STARTUP_TIMEOUT = 120.0


class ContainerError(Exception):
    """Raised when container operations fail."""

    def __init__(self, message: str, user_id: str = ""):
        super().__init__(message)
        self.user_id = user_id


class ContainerInfo:
    """Lightweight container state for caching."""

    __slots__ = ("user_id", "port", "container_id", "status", "gateway_token")

    def __init__(self, user_id: str, port: int, container_id: str, status: str, gateway_token: str = ""):
        self.user_id = user_id
        self.port = port
        self.container_id = container_id
        self.status = status
        self.gateway_token = gateway_token


class ContainerManager:
    """Manages per-user Docker containers running OpenClaw gateway."""

    def __init__(
        self,
        containers_root: str = "/var/lib/isol8/containers",
        openclaw_image: str = "openclaw:local",
        port_range_start: int = 19000,
        port_range_end: int = 19999,
    ):
        self._containers_root = containers_root
        self._openclaw_image = openclaw_image
        self._port_start = port_range_start
        self._port_end = port_range_end
        self._lock = threading.Lock()

        # In-memory cache: user_id -> ContainerInfo
        self._cache: dict[str, ContainerInfo] = {}

        # Connect to Docker daemon
        try:
            self._docker = docker.from_env()
            self._docker.ping()
            logger.info("Docker connection established")
        except DockerException as e:
            logger.error("Failed to connect to Docker: %s", e)
            self._docker = None

    @property
    def available(self) -> bool:
        """Check if Docker is available."""
        return self._docker is not None

    def _container_name(self, user_id: str) -> str:
        """Docker container name for a user."""
        # Sanitize user_id for Docker naming (Clerk IDs like "user_2abc...")
        safe = user_id.replace("_", "-").lower()
        return f"isol8-user-{safe}"

    def _volume_name(self, user_id: str) -> str:
        """Docker volume name for a user's workspace."""
        safe = user_id.replace("_", "-").lower()
        return f"isol8-workspace-{safe}"

    def _env_for_container(self, gateway_token: str) -> dict[str, str]:
        """Environment variables passed to each user container.

        Uses AWS_CONTAINER_CREDENTIALS_FULL_URI so the AWS SDK inside
        the container auto-refreshes credentials from our vending endpoint.
        """
        region = os.environ.get("AWS_REGION", "us-east-1")
        env: dict[str, str] = {
            "AWS_REGION": region,
            "AWS_DEFAULT_REGION": region,
            "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://172.17.0.1:8000/internal/credentials",
            "AWS_CONTAINER_AUTHORIZATION_TOKEN": gateway_token,
            # OpenClaw's credential detection only checks for env vars like
            # AWS_ACCESS_KEY_ID or AWS_PROFILE before invoking the SDK chain.
            # Setting AWS_PROFILE=default signals credentials are available,
            # so the SDK proceeds to find them via the container credential URI.
            "AWS_PROFILE": "default",
        }
        brave_key = os.environ.get("BRAVE_API_KEY", "")
        if brave_key:
            env["BRAVE_API_KEY"] = brave_key
        return env

    # =========================================================================
    # Port allocation
    # =========================================================================

    def _allocate_port(self) -> int:
        """Find the next available port in the range.

        Must be called under self._lock.
        """
        used_ports = {info.port for info in self._cache.values()}
        for port in range(self._port_start, self._port_end + 1):
            if port not in used_ports:
                return port
        raise ContainerError("No available ports in range")

    # =========================================================================
    # Public API
    # =========================================================================

    def get_container_port(self, user_id: str) -> Optional[int]:
        """Get the host port for a user's container (lock-free cache read).

        Returns None if the user has no container.
        """
        info = self._cache.get(user_id)
        if info and info.status == "running":
            return info.port
        return None

    def get_container_info(self, user_id: str) -> Optional[ContainerInfo]:
        """Get full container info for a user."""
        return self._cache.get(user_id)

    def provision_container(
        self,
        user_id: str,
        brave_api_key: str = "",
    ) -> ContainerInfo:
        """Provision a new container for a user.

        Creates Docker volume, writes openclaw.json config, starts container.

        Args:
            user_id: Clerk user ID.
            brave_api_key: Optional Brave API key for web search.

        Returns:
            ContainerInfo with port and status.

        Raises:
            ContainerError: If Docker is unavailable or provisioning fails.
        """
        if not self._docker:
            raise ContainerError("Docker not available", user_id)

        with self._lock:
            # Check if already provisioned
            existing = self._cache.get(user_id)
            if existing and existing.status == "running":
                logger.info("Container already running for user=%s on port=%d", user_id, existing.port)
                return existing

            port = existing.port if existing else self._allocate_port()
            container_name = self._container_name(user_id)
            volume_name = self._volume_name(user_id)

            try:
                # Create Docker volume (idempotent)
                self._docker.volumes.create(name=volume_name)
                logger.info("Volume %s ready", volume_name)

                # Generate a gateway auth token (required for --bind lan)
                gateway_token = secrets.token_urlsafe(32)

                # Write openclaw.json to volume via temporary container
                region = os.environ.get("AWS_REGION", "us-east-1")
                brave_key = brave_api_key or os.environ.get("BRAVE_API_KEY", "")
                config_json = write_openclaw_config(
                    region=region,
                    brave_api_key=brave_key,
                    gateway_token=gateway_token,
                )
                self._write_config_to_volume(volume_name, config_json)

                # Remove old container if it exists (stopped/dead)
                try:
                    old = self._docker.containers.get(container_name)
                    old.remove(force=True)
                except NotFound:
                    pass

                # Start the container
                container = self._docker.containers.run(
                    image=self._openclaw_image,
                    name=container_name,
                    command=[
                        "node",
                        "openclaw.mjs",
                        "gateway",
                        "--port",
                        str(_INTERNAL_GATEWAY_PORT),
                        "--bind",
                        "lan",
                        "--allow-unconfigured",
                    ],
                    environment=self._env_for_container(gateway_token=gateway_token),
                    volumes={
                        volume_name: {
                            "bind": "/home/node/.openclaw",
                            "mode": "rw",
                        },
                    },
                    ports={f"{_INTERNAL_GATEWAY_PORT}/tcp": ("127.0.0.1", port)},
                    labels={"isol8.user_id": user_id},
                    detach=True,
                    restart_policy={"Name": "unless-stopped"},
                    mem_limit="2g",
                    cpu_period=100000,
                    cpu_quota=200000,  # 2 CPU cores max
                )

                info = ContainerInfo(
                    user_id=user_id,
                    port=port,
                    container_id=container.id,
                    status="running",
                    gateway_token=gateway_token,
                )
                self._cache[user_id] = info
                logger.info(
                    "Provisioned container for user=%s: name=%s port=%d id=%s",
                    user_id,
                    container_name,
                    port,
                    container.short_id,
                )
                return info

            except (DockerException, APIError) as e:
                logger.error("Failed to provision container for user=%s: %s", user_id, e)
                raise ContainerError(f"Container provisioning failed: {e}", user_id)

    def stop_container(self, user_id: str) -> bool:
        """Stop a user's container gracefully. Volume is preserved.

        Returns True if stopped, False if not found.
        """
        if not self._docker:
            return False

        with self._lock:
            container_name = self._container_name(user_id)
            try:
                container = self._docker.containers.get(container_name)
                container.stop(timeout=10)
                logger.info("Stopped container for user=%s", user_id)

                info = self._cache.get(user_id)
                if info:
                    info.status = "stopped"
                return True

            except NotFound:
                logger.debug("No container found for user=%s", user_id)
                return False
            except (DockerException, APIError) as e:
                logger.error("Failed to stop container for user=%s: %s", user_id, e)
                return False

    def remove_container(self, user_id: str, keep_volume: bool = True) -> bool:
        """Remove a user's container and optionally its volume.

        Args:
            user_id: Clerk user ID.
            keep_volume: If True, preserve the workspace volume (default).

        Returns True if removed, False if not found.
        """
        if not self._docker:
            return False

        with self._lock:
            container_name = self._container_name(user_id)
            volume_name = self._volume_name(user_id)

            # Remove container
            try:
                container = self._docker.containers.get(container_name)
                container.remove(force=True)
                logger.info("Removed container for user=%s", user_id)
            except NotFound:
                pass
            except (DockerException, APIError) as e:
                logger.error("Failed to remove container for user=%s: %s", user_id, e)

            # Remove volume if requested
            if not keep_volume:
                try:
                    vol = self._docker.volumes.get(volume_name)
                    vol.remove(force=True)
                    logger.info("Removed volume for user=%s", user_id)
                except NotFound:
                    pass
                except (DockerException, APIError) as e:
                    logger.error("Failed to remove volume for user=%s: %s", user_id, e)

            # Clear cache
            self._cache.pop(user_id, None)
            return True

    def ensure_running(self, user_id: str) -> Optional[int]:
        """Ensure a user's container is running, restart if needed.

        Returns the port if running, None if no container exists.
        """
        if not self._docker:
            return None

        info = self._cache.get(user_id)
        if not info:
            return None

        container_name = self._container_name(user_id)
        try:
            container = self._docker.containers.get(container_name)
            if container.status == "running":
                return info.port

            # Container exists but stopped — restart it
            container.start()
            info.status = "running"
            logger.info("Restarted container for user=%s on port=%d", user_id, info.port)
            return info.port

        except NotFound:
            # Container was deleted externally — re-provision
            logger.warning("Container missing for user=%s, re-provisioning", user_id)
            self._cache.pop(user_id, None)
            try:
                new_info = self.provision_container(user_id)
                return new_info.port
            except ContainerError:
                return None

        except (DockerException, APIError) as e:
            logger.error("Failed to ensure container for user=%s: %s", user_id, e)
            return None

    def is_healthy(self, user_id: str) -> bool:
        """Check if a user's container gateway is responding."""
        info = self._cache.get(user_id)
        if not info or info.status != "running":
            return False

        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{info.port}/v1/chat/completions",
                method="OPTIONS",
            )
            if info.gateway_token:
                req.add_header("Authorization", f"Bearer {info.gateway_token}")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status < 500
        except urllib.error.HTTPError as e:
            return e.code < 500
        except Exception:
            return False

    def list_containers(self) -> list[ContainerInfo]:
        """List all cached container states."""
        return list(self._cache.values())

    def get_container_logs(self, user_id: str, tail: int = 100) -> str:
        """Get recent logs from a user's container.

        Args:
            user_id: Clerk user ID.
            tail: Number of log lines to retrieve.

        Returns:
            Log output as string.

        Raises:
            ContainerError: If container not found or logs retrieval fails.
        """
        if not self._docker:
            raise ContainerError("Docker not available", user_id)

        container_name = self._container_name(user_id)
        try:
            container = self._docker.containers.get(container_name)
            logs = container.logs(tail=tail, timestamps=True)
            return logs.decode("utf-8", errors="replace")
        except NotFound:
            raise ContainerError(f"Container not found for user {user_id}", user_id)
        except (DockerException, APIError) as e:
            raise ContainerError(f"Logs failed: {e}", user_id)

    def exec_command(self, user_id: str, command: list[str]) -> str:
        """Execute a command inside a user's container.

        Args:
            user_id: Clerk user ID.
            command: Command and arguments, e.g. ["openclaw", "agent", "list"].

        Returns:
            Command stdout as string.

        Raises:
            ContainerError: If container not found or command fails.
        """
        if not self._docker:
            raise ContainerError("Docker not available", user_id)

        container_name = self._container_name(user_id)
        info = self._cache.get(user_id)
        gateway_token = info.gateway_token if info else ""
        try:
            container = self._docker.containers.get(container_name)
            exit_code, output = container.exec_run(
                command,
                environment=self._env_for_container(gateway_token=gateway_token),
            )
            result = output.decode("utf-8", errors="replace")

            if exit_code != 0:
                logger.warning(
                    "Command failed in container user=%s cmd=%s exit=%d: %s",
                    user_id,
                    command,
                    exit_code,
                    result[:200],
                )
                raise ContainerError(f"Command exited with code {exit_code}: {result[:200]}", user_id)

            return result

        except NotFound:
            raise ContainerError(f"Container not found for user {user_id}", user_id)
        except (DockerException, APIError) as e:
            raise ContainerError(f"Exec failed: {e}", user_id)

    # =========================================================================
    # Reconciliation (startup)
    # =========================================================================

    def reconcile(self, db_tokens: Optional[dict[str, str]] = None) -> None:
        """Rebuild in-memory cache from running Docker containers.

        Called on application startup to re-discover existing containers.

        Args:
            db_tokens: Optional mapping of user_id -> gateway_token from the
                       database, used to restore auth tokens that are only
                       persisted in the containers table.
        """
        if not self._docker:
            logger.warning("Docker not available, skipping reconciliation")
            return

        tokens = db_tokens or {}

        try:
            containers = self._docker.containers.list(
                all=True,
                filters={"name": "isol8-user-"},
            )
        except (DockerException, APIError) as e:
            logger.error("Failed to list containers: %s", e)
            return

        for container in containers:
            name = container.name
            # Extract user_id from name: isol8-user-{sanitized_id}
            if not name.startswith("isol8-user-"):
                continue

            # Get port mapping
            port = self._extract_port(container)
            if not port:
                continue

            # Reverse sanitize: "isol8-user-user-2abc" -> approximate user_id
            # We store the original user_id in a container label for reliability
            user_id = container.labels.get("isol8.user_id", "")
            if not user_id:
                # Fallback: reverse the sanitization (best effort)
                raw = name.removeprefix("isol8-user-")
                user_id = raw.replace("-", "_", 1)  # first dash back to underscore

            info = ContainerInfo(
                user_id=user_id,
                port=port,
                container_id=container.id,
                status=container.status,
                gateway_token=tokens.get(user_id, ""),
            )
            self._cache[user_id] = info
            logger.info(
                "Reconciled container: user=%s port=%d status=%s token=%s",
                user_id,
                port,
                container.status,
                "yes" if info.gateway_token else "no",
            )

        logger.info("Reconciled %d containers", len(self._cache))

    def _extract_port(self, container) -> Optional[int]:
        """Extract the host port mapped to the gateway port."""
        try:
            ports = container.ports or {}
            gateway_port_key = f"{_INTERNAL_GATEWAY_PORT}/tcp"
            bindings = ports.get(gateway_port_key, [])
            if bindings:
                return int(bindings[0]["HostPort"])
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        return None

    # =========================================================================
    # Helpers
    # =========================================================================

    def _write_config_to_volume(self, volume_name: str, config_json: str) -> None:
        """Write openclaw.json into a Docker volume using a temp container.

        Uses base64 encoding to safely pass JSON through shell without
        escaping issues. Chowns the volume to UID 1000 (node user) so the
        OpenClaw container can create subdirectories (workspace, canvas, cron).
        """
        import base64

        encoded = base64.b64encode(config_json.encode()).decode()
        try:
            self._docker.containers.run(
                image="alpine:latest",
                command=[
                    "sh",
                    "-c",
                    f"echo '{encoded}' | base64 -d > /workspace/openclaw.json && chown -R 1000:1000 /workspace",
                ],
                volumes={volume_name: {"bind": "/workspace", "mode": "rw"}},
                remove=True,
            )
        except (DockerException, APIError) as e:
            logger.error("Failed to write config to volume %s: %s", volume_name, e)
            raise ContainerError(f"Config write failed: {e}")
