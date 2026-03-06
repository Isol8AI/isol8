"""
ECS Fargate service manager for per-user OpenClaw gateways.

Each subscriber gets a dedicated ECS Service (desiredCount 0/1) that
runs an OpenClaw gateway container with a per-user EFS access point
for data isolation. Task IPs are discovered via the ECS describe_tasks
API.
"""

import hashlib
import json
import logging
import urllib.request
import urllib.error

import boto3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
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

    def __init__(self):
        self._ecs = boto3.client("ecs", region_name=settings.AWS_REGION)
        self._efs = boto3.client("efs", region_name=settings.AWS_REGION)
        self._cluster = settings.ECS_CLUSTER_ARN
        self._task_def = settings.ECS_TASK_DEFINITION
        self._subnets = [s.strip() for s in settings.ECS_SUBNETS.split(",") if s.strip()]
        self._security_groups = [settings.ECS_SECURITY_GROUP_ID]
        self._cloud_map_service_arn = settings.CLOUD_MAP_SERVICE_ARN
        self._efs_file_system_id = settings.EFS_FILE_SYSTEM_ID

    def _service_name(self, user_id: str) -> str:
        """Generate deterministic, collision-resistant service name from user_id.

        ECS service names must be <= 255 chars. We use a SHA-256 hash
        truncated to 12 hex chars (48 bits) for uniqueness while keeping
        names short and readable.
        """
        uid_hash = hashlib.sha256(user_id.encode()).hexdigest()[:12]
        return f"openclaw-{uid_hash}"

    # ------------------------------------------------------------------
    # Per-user EFS access points
    # ------------------------------------------------------------------

    def _create_access_point(self, user_id: str) -> str:
        """Create a per-user EFS access point rooted at /users/{user_id}.

        The access point enforces POSIX UID/GID 1000 (matching the
        OpenClaw container's node user) and creates the root directory
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
    # Service lifecycle
    # ------------------------------------------------------------------

    async def create_user_service(self, user_id: str, gateway_token: str, db: AsyncSession) -> str:
        """Create an ECS Service for a user with per-user EFS isolation.

        1. Upserts the Container DB record (status=provisioning) so frontend can poll
        2. Creates a per-user EFS access point → substatus=efs_created
        3. Registers a per-user task definition revision → substatus=task_registered
        4. Creates the ECS service → substatus=service_created

        On failure, sets status=error, substatus=None, and rolls back AWS resources.

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
            container.access_point_id = access_point_id
            container.substatus = "efs_created"
            await db.commit()

            # Step 2: Register per-user task definition with that access point
            task_def_arn = self._register_task_definition(access_point_id)
            container.task_definition_arn = task_def_arn
            container.substatus = "task_registered"
            await db.commit()

            # Step 3: Create ECS service with per-user task definition
            create_kwargs = dict(
                cluster=self._cluster,
                serviceName=service_name,
                taskDefinition=task_def_arn,
                desiredCount=1,
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
            container.substatus = "service_created"
            await db.commit()
        except EcsManagerError:
            # Mark container as error in DB
            container.status = "error"
            container.substatus = None
            await db.commit()
            # Rollback already-created AWS resources
            if task_def_arn:
                self._deregister_task_definition(task_def_arn)
            if access_point_id:
                self._delete_access_point(access_point_id)
            raise
        except Exception as e:
            # Mark container as error in DB
            container.status = "error"
            container.substatus = None
            await db.commit()
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
            container.substatus = "gateway_healthy"
            container.status = "running"
            await db.commit()
            logger.info(
                "Container %s for user %s transitioned to running",
                container.service_name,
                user_id,
            )

            # One-time post-provisioning: install skill CLIs and skill-vetter
            if container.gateway_token:
                self._install_skill_prerequisites(ip, container.gateway_token)

        return container, ip

    def _call_gateway_rpc(self, ip: str, gateway_token: str, method: str, params: dict) -> dict:
        """Send a JSON-RPC request to the gateway.

        Args:
            ip: Task private IP.
            gateway_token: Bearer token for auth.
            method: RPC method name.
            params: RPC parameters.

        Returns:
            Parsed JSON response, or empty dict on failure.
        """
        body = json.dumps({"method": method, "params": params}).encode()
        req = urllib.request.Request(
            f"http://{ip}:{GATEWAY_PORT}/rpc",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {gateway_token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except Exception as e:
            logger.warning("Gateway RPC %s failed: %s", method, e)
            return {}

    def _install_skill_prerequisites(self, ip: str, gateway_token: str) -> None:
        """Install mcporter + clawhub CLIs and skill-vetter skill.

        Best-effort: logs failures but does not raise. Called once when a
        container first transitions to running.
        """
        logger.info("Installing skill prerequisites on %s", ip)
        try:
            self._call_gateway_rpc(
                ip,
                gateway_token,
                "skills.install",
                {
                    "name": "mcporter",
                    "installId": "node",
                    "timeoutMs": 120000,
                },
            )
            self._call_gateway_rpc(
                ip,
                gateway_token,
                "skills.install",
                {
                    "name": "clawhub",
                    "installId": "node",
                    "timeoutMs": 120000,
                },
            )
            # Install skill-vetter from ClawHub for security vetting
            self._call_gateway_rpc(
                ip,
                gateway_token,
                "exec.run",
                {
                    "command": "clawhub",
                    "args": ["install", "spclaudehome/skill-vetter", "--no-input"],
                },
            )
            logger.info("Skill prerequisites installed on %s", ip)
        except Exception as e:
            logger.warning("Skill prerequisites install failed on %s: %s", ip, e)

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
