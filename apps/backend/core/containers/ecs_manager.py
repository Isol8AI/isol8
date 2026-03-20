"""
ECS Fargate service manager for per-user OpenClaw gateways.

Each subscriber gets a dedicated ECS Service (desiredCount 0/1) that
runs an OpenClaw gateway container with a per-user EFS access point
for data isolation. Task IPs are discovered via the ECS describe_tasks
API.
"""

import hashlib
import logging
import re
import secrets
import urllib.request
import urllib.error

import boto3
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from core.containers.config import (
    write_mcporter_config,
    write_openclaw_config,
    write_paired_devices_config,
)
from core.containers.device_identity import generate_device_identity
from core.containers.workspace import get_workspace
from core.database import async_session_factory
from models.container import Container

logger = logging.getLogger(__name__)

GATEWAY_PORT = 18789


class EcsManagerError(Exception):
    """Raised when ECS operations fail."""

    def __init__(self, message: str, user_id: str = ""):
        super().__init__(message)
        self.user_id = user_id


class EcsManager:
    """Manages per-user ECS Fargate services for OpenClaw gateways."""

    def __init__(self, session_factory: async_sessionmaker | None = None):
        self._ecs = boto3.client("ecs", region_name=settings.AWS_REGION)
        self._efs = boto3.client("efs", region_name=settings.AWS_REGION)
        self._cluster = settings.ECS_CLUSTER_ARN
        self._task_def = settings.ECS_TASK_DEFINITION
        self._subnets = [s.strip() for s in settings.ECS_SUBNETS.split(",") if s.strip()]
        self._security_groups = [settings.ECS_SECURITY_GROUP_ID]
        self._cloud_map_service_arn = settings.CLOUD_MAP_SERVICE_ARN
        self._efs_file_system_id = settings.EFS_FILE_SYSTEM_ID
        self._session_factory = session_factory

    def _service_name(self, user_id: str) -> str:
        """Generate deterministic, collision-resistant service name from user_id.

        ECS service names must be <= 255 chars. Format: openclaw-{user_id}-{hash}
        so services are identifiable in the ECS console. The hash suffix
        guarantees uniqueness even if user_id is truncated.
        """
        uid_hash = hashlib.sha256(user_id.encode()).hexdigest()[:12]
        # Sanitize user_id for ECS naming (alphanumeric, hyphens, underscores only)
        safe_uid = re.sub(r"[^a-zA-Z0-9_-]", "", user_id)[:40]
        return f"openclaw-{safe_uid}-{uid_hash}"

    # ------------------------------------------------------------------
    # Per-user EFS access points
    # ------------------------------------------------------------------

    def _create_access_point(self, user_id: str) -> str:
        """Create a per-user EFS access point rooted at /users/{user_id}.

        The access point enforces POSIX UID/GID 0 (matching the
        container's root user) and creates the root directory
        with 0755 permissions if it doesn't exist.

        Args:
            user_id: Clerk user ID.

        Returns:
            The access point ID (e.g. "fsap-0abc123...").

        Raises:
            EcsManagerError: If the EFS API call fails.
        """
        try:
            resp = self._efs.create_access_point(
                FileSystemId=self._efs_file_system_id,
                PosixUser={"Uid": 1000, "Gid": 1000},
                RootDirectory={
                    "Path": f"/users/{user_id}",
                    "CreationInfo": {
                        "OwnerUid": 1000,
                        "OwnerGid": 1000,
                        "Permissions": "0755",
                    },
                },
                Tags=[
                    {"Key": "Name", "Value": f"isol8-{user_id}"},
                    {"Key": "user_id", "Value": user_id},
                    {"Key": "ManagedBy", "Value": "isol8-backend"},
                ],
            )
            access_point_id = resp["AccessPointId"]
            logger.info("Created EFS access point %s for user %s", access_point_id, user_id)
            return access_point_id
        except Exception as e:
            raise EcsManagerError(
                f"Failed to create EFS access point for user {user_id}: {e}",
                user_id,
            )

    def _delete_access_point(self, access_point_id: str) -> None:
        """Delete an EFS access point. Idempotent (ignores not-found)."""
        try:
            self._efs.delete_access_point(AccessPointId=access_point_id)
            logger.info("Deleted EFS access point %s", access_point_id)
        except self._efs.exceptions.AccessPointNotFound:
            logger.warning("Access point %s already deleted", access_point_id)
        except Exception as e:
            logger.error("Failed to delete access point %s: %s", access_point_id, e)

    # ------------------------------------------------------------------
    # Per-user task definition revisions
    # ------------------------------------------------------------------

    def _register_task_definition(self, access_point_id: str) -> str:
        """Clone the base task definition with a per-user EFS access point.

        Reads the Terraform-managed base task definition, replaces the
        EFS volume's access point ID with the per-user one, and registers
        a new revision in the same family.

        Args:
            access_point_id: The per-user EFS access point ID.

        Returns:
            The ARN of the newly registered task definition revision.

        Raises:
            EcsManagerError: If the ECS API calls fail.
        """
        try:
            # Read the base task definition
            desc_resp = self._ecs.describe_task_definition(taskDefinition=self._task_def)
            base = desc_resp["taskDefinition"]

            # Clone volumes with per-user access point
            volumes = []
            for vol in base.get("volumes", []):
                vol_copy = dict(vol)
                efs_config = vol_copy.get("efsVolumeConfiguration")
                if efs_config:
                    efs_copy = dict(efs_config)
                    auth_config = dict(efs_copy.get("authorizationConfig", {}))
                    auth_config["accessPointId"] = access_point_id
                    efs_copy["authorizationConfig"] = auth_config
                    vol_copy["efsVolumeConfiguration"] = efs_copy
                volumes.append(vol_copy)

            # Register new revision in the same family
            reg_kwargs = dict(
                family=base["family"],
                taskRoleArn=base.get("taskRoleArn", ""),
                executionRoleArn=base.get("executionRoleArn", ""),
                networkMode=base.get("networkMode", "awsvpc"),
                containerDefinitions=base["containerDefinitions"],
                volumes=volumes,
                requiresCompatibilities=base.get("requiresCompatibilities", ["FARGATE"]),
                cpu=base.get("cpu", "256"),
                memory=base.get("memory", "512"),
            )
            # runtimePlatform is optional; passing None causes ParamValidationError
            if base.get("runtimePlatform"):
                reg_kwargs["runtimePlatform"] = base["runtimePlatform"]

            reg_resp = self._ecs.register_task_definition(**reg_kwargs)
            task_def_arn = reg_resp["taskDefinition"]["taskDefinitionArn"]
            logger.info("Registered per-user task definition %s", task_def_arn)
            return task_def_arn
        except Exception as e:
            raise EcsManagerError(
                f"Failed to register per-user task definition: {e}",
                user_id="",
            )

    def _deregister_task_definition(self, task_definition_arn: str) -> None:
        """Deregister a per-user task definition revision. Idempotent."""
        try:
            self._ecs.deregister_task_definition(taskDefinition=task_definition_arn)
            logger.info("Deregistered task definition %s", task_definition_arn)
        except Exception as e:
            logger.error("Failed to deregister task definition %s: %s", task_definition_arn, e)

    # ------------------------------------------------------------------
    # Safe DB helpers
    # ------------------------------------------------------------------

    def _get_session_factory(self) -> async_sessionmaker:
        """Return the session factory, using the module-level default if not set at init."""
        if self._session_factory is None:
            self._session_factory = async_session_factory
        return self._session_factory

    async def _update_container(self, user_id: str, **fields) -> None:
        """Update container fields using a fresh session.

        Uses the session factory to create an isolated session for each
        update, avoiding 7s2a errors when pgbouncer drops connections
        between long-running boto3 calls.
        """
        factory = self._get_session_factory()
        async with factory() as db:
            await db.execute(update(Container).where(Container.user_id == user_id).values(**fields))
            await db.commit()

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------

    async def create_user_service(self, user_id: str, gateway_token: str, db: AsyncSession) -> str:
        """Create an ECS Service for a user with per-user EFS isolation.

        1. Upserts the Container DB record (status=provisioning) so frontend can poll
        2. Creates a per-user EFS access point → substatus=efs_created
        3. Registers a per-user task definition revision → substatus=task_registered
        4. Creates the ECS service → substatus=service_created

        On failure, sets status=error, substatus=None, and rolls back AWS resources.

        Substatus updates use fresh sessions (via _update_container) to avoid
        7s2a errors when pgbouncer drops connections during slow AWS API calls.

        Args:
            user_id: Clerk user ID.
            gateway_token: Auth token for the OpenClaw gateway HTTP API.
            db: Async database session.

        Returns:
            The ECS service name.

        Raises:
            EcsManagerError: If any step fails.
        """
        service_name = self._service_name(user_id)
        access_point_id = None
        task_def_arn = None

        # Step 0: Upsert container record EARLY so frontend can start polling
        result = await db.execute(select(Container).where(Container.user_id == user_id))
        container = result.scalar_one_or_none()
        if container:
            container.service_name = service_name
            container.gateway_token = gateway_token
            container.status = "provisioning"
            container.substatus = None
        else:
            container = Container(
                user_id=user_id,
                service_name=service_name,
                gateway_token=gateway_token,
                status="provisioning",
                substatus=None,
            )
            db.add(container)
        await db.commit()

        try:
            # Step 1: Create per-user EFS access point
            access_point_id = self._create_access_point(user_id)
            await self._update_container(
                user_id,
                access_point_id=access_point_id,
                substatus="efs_created",
            )

            # Step 2: Register per-user task definition with that access point
            task_def_arn = self._register_task_definition(access_point_id)
            await self._update_container(
                user_id,
                task_definition_arn=task_def_arn,
                substatus="task_registered",
            )

            # Step 3: Create ECS service with desiredCount=0 so the container
            # does NOT start yet — the caller writes config files (openclaw.json,
            # paired.json) to EFS before calling start_user_service().
            create_kwargs = dict(
                cluster=self._cluster,
                serviceName=service_name,
                taskDefinition=task_def_arn,
                desiredCount=0,
                launchType="FARGATE",
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": self._subnets,
                        "securityGroups": self._security_groups,
                        "assignPublicIp": "DISABLED",
                    }
                },
                serviceRegistries=[{"registryArn": self._cloud_map_service_arn}],
            )
            # Only enable ECS Exec for non-production environments
            if settings.ENVIRONMENT != "prod":
                create_kwargs["enableExecuteCommand"] = True
            self._ecs.create_service(**create_kwargs)
            await self._update_container(user_id, substatus="service_created")
        except EcsManagerError:
            # Mark container as error in DB (fresh session — safe even if connection died)
            try:
                await self._update_container(user_id, status="error", substatus=None)
            except Exception:
                logger.error("Failed to mark container as error for user %s", user_id)
            # Rollback already-created AWS resources
            if task_def_arn:
                self._deregister_task_definition(task_def_arn)
            if access_point_id:
                self._delete_access_point(access_point_id)
            raise
        except Exception as e:
            # Mark container as error in DB (fresh session — safe even if connection died)
            try:
                await self._update_container(user_id, status="error", substatus=None)
            except Exception:
                logger.error("Failed to mark container as error for user %s", user_id)
            # Rollback already-created AWS resources
            if task_def_arn:
                self._deregister_task_definition(task_def_arn)
            if access_point_id:
                self._delete_access_point(access_point_id)
            logger.error(
                "Failed to create ECS service %s for user %s: %s",
                service_name,
                user_id,
                e,
            )
            raise EcsManagerError(f"Failed to create ECS service: {e}", user_id)

        logger.info("Created ECS service %s for user %s", service_name, user_id)
        return service_name

    async def stop_user_service(self, user_id: str, db: AsyncSession) -> None:
        """Scale a user's ECS service to 0 (stopped).

        Args:
            user_id: Clerk user ID.
            db: Async database session.

        Raises:
            EcsManagerError: If the ECS update_service call fails.
        """
        service_name = self._service_name(user_id)

        try:
            self._ecs.update_service(
                cluster=self._cluster,
                service=service_name,
                desiredCount=0,
            )
        except Exception as e:
            logger.error(
                "Failed to stop ECS service %s for user %s: %s",
                service_name,
                user_id,
                e,
            )
            raise EcsManagerError(f"Failed to stop ECS service: {e}", user_id)

        result = await db.execute(select(Container).where(Container.user_id == user_id))
        container = result.scalar_one_or_none()
        if container:
            container.status = "stopped"
            await db.commit()

        logger.info("Stopped ECS service %s for user %s", service_name, user_id)

    async def start_user_service(self, user_id: str, db: AsyncSession) -> None:
        """Scale a user's ECS service to 1 (running) with forced new deployment.

        Args:
            user_id: Clerk user ID.
            db: Async database session.

        Raises:
            EcsManagerError: If the ECS update_service call fails.
        """
        service_name = self._service_name(user_id)

        try:
            self._ecs.update_service(
                cluster=self._cluster,
                service=service_name,
                desiredCount=1,
                forceNewDeployment=True,
            )
        except Exception as e:
            logger.error(
                "Failed to start ECS service %s for user %s: %s",
                service_name,
                user_id,
                e,
            )
            raise EcsManagerError(f"Failed to start ECS service: {e}", user_id)

        result = await db.execute(select(Container).where(Container.user_id == user_id))
        container = result.scalar_one_or_none()
        if container:
            container.status = "provisioning"
            await db.commit()

        logger.info("Started ECS service %s for user %s", service_name, user_id)

    async def delete_user_service(self, user_id: str, db: AsyncSession) -> None:
        """Remove a user's ECS service and per-user resources entirely.

        1. Scale to 0 and delete ECS service
        2. Deregister per-user task definition (if present)
        3. Delete per-user EFS access point (if present)
        4. Delete Container DB record

        Args:
            user_id: Clerk user ID.
            db: Async database session.

        Raises:
            EcsManagerError: If the ECS API calls fail.
        """
        service_name = self._service_name(user_id)

        try:
            # Scale to 0 before deleting
            self._ecs.update_service(
                cluster=self._cluster,
                service=service_name,
                desiredCount=0,
            )
            self._ecs.delete_service(
                cluster=self._cluster,
                service=service_name,
                force=True,
            )
        except Exception as e:
            logger.error(
                "Failed to delete ECS service %s for user %s: %s",
                service_name,
                user_id,
                e,
            )
            raise EcsManagerError(f"Failed to delete ECS service: {e}", user_id)

        # Clean up per-user resources and delete container record from DB
        result = await db.execute(select(Container).where(Container.user_id == user_id))
        container = result.scalar_one_or_none()
        if container:
            # Deregister per-user task definition
            if container.task_definition_arn:
                self._deregister_task_definition(container.task_definition_arn)

            # Delete per-user EFS access point
            if container.access_point_id:
                self._delete_access_point(container.access_point_id)

            await db.delete(container)
            await db.commit()

        logger.info("Deleted ECS service %s for user %s", service_name, user_id)

    # ------------------------------------------------------------------
    # Discovery and health
    # ------------------------------------------------------------------

    def discover_ip(self, service_name: str) -> str | None:
        """Discover a task's private IP via ECS describe_tasks API.

        Lists running tasks for the given ECS service, then describes
        them to extract the private IPv4 address from the ENI attachment.
        This is more reliable than Cloud Map and ensures per-service
        isolation (each service's tasks are queried independently).

        Args:
            service_name: The ECS service name.

        Returns:
            The task's private IPv4 address, or None if no running task.
        """
        try:
            # List tasks for this specific service
            list_resp = self._ecs.list_tasks(
                cluster=self._cluster,
                serviceName=service_name,
                desiredStatus="RUNNING",
            )
            task_arns = list_resp.get("taskArns", [])
            if not task_arns:
                return None

            # Describe the first running task to get its ENI IP
            desc_resp = self._ecs.describe_tasks(
                cluster=self._cluster,
                tasks=[task_arns[0]],
            )
            tasks = desc_resp.get("tasks", [])
            if not tasks:
                return None

            # Extract private IP from ENI attachment
            for attachment in tasks[0].get("attachments", []):
                if attachment.get("type") == "ElasticNetworkInterface":
                    for detail in attachment.get("details", []):
                        if detail.get("name") == "privateIPv4Address":
                            return detail.get("value")
        except Exception as e:
            logger.error("ECS task discovery failed for %s: %s", service_name, e)
        return None

    def is_healthy(self, ip: str) -> bool:
        """Check if a gateway at the given IP is responding.

        Sends an HTTP OPTIONS request to the gateway's chat completions
        endpoint. Returns True if the gateway responds with a non-5xx
        status code.

        Args:
            ip: The task's private IPv4 address.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            req = urllib.request.Request(
                f"http://{ip}:{GATEWAY_PORT}/v1/chat/completions",
                method="OPTIONS",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status < 500
        except urllib.error.HTTPError as e:
            # 4xx responses are still "healthy" (gateway is running)
            return e.code < 500
        except Exception:
            return False

    async def resolve_running_container(self, user_id: str, db: AsyncSession) -> tuple[Container | None, str | None]:
        """Look up a user's container and discover its task IP.

        Accepts containers in "provisioning" or "running" status.
        If a provisioning container's task is healthy, automatically
        transitions the status to "running".

        Args:
            user_id: Clerk user ID.
            db: Async database session.

        Returns:
            Tuple of (Container, task_ip) or (None, None) if no active container.
        """
        result = await db.execute(
            select(Container).where(
                Container.user_id == user_id,
                Container.status.in_(["provisioning", "running"]),
            )
        )
        container = result.scalar_one_or_none()
        if not container:
            return None, None

        ip = self.discover_ip(container.service_name)
        if not ip:
            return container, None

        # Auto-transition provisioning → running once the task is reachable
        if container.status == "provisioning" and self.is_healthy(ip):
            try:
                container.substatus = "gateway_healthy"
                container.status = "running"
                await db.commit()
                logger.info(
                    "Container %s for user %s transitioned to running",
                    container.service_name,
                    user_id,
                )
            except Exception:
                # Connection may have been dropped during is_healthy() HTTP call.
                # Rollback so the session is usable; status transition will happen
                # on the next poll.
                await db.rollback()
                logger.warning(
                    "Failed to persist running status for user %s, will retry on next poll",
                    user_id,
                )

        return container, ip

    async def get_service_status(self, user_id: str, db: AsyncSession) -> Container | None:
        """Get the Container record for a user.

        Args:
            user_id: Clerk user ID.
            db: Async database session.

        Returns:
            The Container model instance, or None if not found.
        """
        result = await db.execute(select(Container).where(Container.user_id == user_id))
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Full provisioning flow
    # ------------------------------------------------------------------

    async def provision_user_container(self, user_id: str, db: AsyncSession) -> str:
        """Full provisioning flow: create service, write configs, start.

        Safe to call on error/failed containers — cleans up old state first.
        Only updates DB status after each step succeeds.

        Args:
            user_id: Clerk user ID.
            db: Async database session.

        Returns:
            The ECS service name.

        Raises:
            EcsManagerError: If any provisioning step fails.
        """
        # Step 0: If container exists in error state, clean up old AWS resources
        result = await db.execute(select(Container).where(Container.user_id == user_id))
        existing = result.scalar_one_or_none()
        if existing and existing.status == "error":
            if existing.task_definition_arn:
                self._deregister_task_definition(existing.task_definition_arn)
                existing.task_definition_arn = None
            if existing.access_point_id:
                self._delete_access_point(existing.access_point_id)
                existing.access_point_id = None
            # Delete ECS service if it exists (ignore errors — may not exist)
            try:
                service_name = self._service_name(user_id)
                self._ecs.update_service(
                    cluster=self._cluster,
                    service=service_name,
                    desiredCount=0,
                )
                self._ecs.delete_service(
                    cluster=self._cluster,
                    service=service_name,
                    force=True,
                )
            except Exception:
                pass  # Service may not exist yet
            existing.status = "provisioning"
            existing.substatus = None
            await db.commit()

        # Step 1: Generate gateway token
        gateway_token = secrets.token_urlsafe(32)

        # Step 2: Create ECS service (desiredCount=0)
        service_name = await self.create_user_service(user_id, gateway_token, db)

        # Step 3: Generate device identity and write configs to EFS
        try:
            identity = generate_device_identity()
            container_result = await db.execute(select(Container).where(Container.user_id == user_id))
            container_row = container_result.scalar_one_or_none()
            if container_row:
                container_row.device_private_key_pem = identity["private_key_pem"]
                await db.commit()

            config_json = write_openclaw_config(
                region=settings.AWS_REGION,
                gateway_token=gateway_token,
                proxy_base_url=settings.PROXY_BASE_URL,
            )
            workspace = get_workspace()
            workspace.write_file(user_id, "devices/paired.json", write_paired_devices_config(identity))
            workspace.write_file(user_id, "openclaw.json", config_json)
            workspace.write_file(user_id, ".mcporter/mcporter.json", write_mcporter_config())
        except Exception as e:
            await self._update_container(user_id, status="error", substatus=None)
            raise EcsManagerError(f"Failed to write configs for user {user_id}: {e}", user_id)

        # Step 4: Start the container
        try:
            await self.start_user_service(user_id, db)
        except EcsManagerError:
            await self._update_container(user_id, status="error", substatus=None)
            raise

        logger.info("Provisioned container %s for user %s", service_name, user_id)
        return service_name
