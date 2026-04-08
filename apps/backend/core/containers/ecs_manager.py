"""
ECS Fargate service manager for per-user OpenClaw gateways.

Each subscriber gets a dedicated ECS Service (desiredCount 0/1) that
runs an OpenClaw gateway container with a per-user EFS access point
for data isolation. Task IPs are discovered via the ECS describe_tasks
API.
"""

import asyncio
import hashlib
import logging
import re
import secrets
import socket

import boto3

from core.config import settings
from core.containers.config import (
    build_device_paired_json,
    generate_node_device_identity,
    load_node_device_identity,
    write_mcporter_config,
    write_openclaw_config,
)
from core.containers.workspace import get_workspace
from core.repositories import container_repo

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

    def _create_access_point(self, user_id: str, owner_type: str = "personal") -> str:
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
                    {"Key": "owner_id", "Value": user_id},
                    {"Key": "owner_type", "Value": owner_type},
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

    async def _update_container(self, user_id: str, **fields) -> None:
        """Update container fields via the DynamoDB container repo."""
        await container_repo.update_fields(user_id, fields)

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------

    async def create_user_service(self, user_id: str, gateway_token: str, owner_type: str = "personal") -> str:
        """Create an ECS Service for a user with per-user EFS isolation.

        1. Upserts the Container DB record (status=provisioning) so frontend can poll
        2. Creates a per-user EFS access point -> substatus=efs_created
        3. Registers a per-user task definition revision -> substatus=task_registered
        4. Creates the ECS service -> substatus=service_created

        On failure, sets status=error, substatus=None, and rolls back AWS resources.

        Args:
            user_id: Clerk user ID.
            gateway_token: Auth token for the OpenClaw gateway HTTP API.

        Returns:
            The ECS service name.

        Raises:
            EcsManagerError: If any step fails.
        """
        service_name = self._service_name(user_id)
        access_point_id = None
        task_def_arn = None

        # Step 0: Upsert container record EARLY so frontend can start polling
        await container_repo.upsert(
            user_id,
            {
                "service_name": service_name,
                "gateway_token": gateway_token,
                "status": "provisioning",
                "substatus": None,
                "owner_type": owner_type,
            },
        )

        try:
            # Step 1: Create per-user EFS access point
            access_point_id = self._create_access_point(user_id, owner_type=owner_type)
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
            # does NOT start yet -- the caller writes config files (openclaw.json,
            # openclaw.json, mcporter.json) to EFS before calling start_user_service().
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
            # Mark container as error in DB
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
            # Mark container as error in DB
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

    async def stop_user_service(self, user_id: str) -> None:
        """Scale a user's ECS service to 0 (stopped).

        Args:
            user_id: Clerk user ID.

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

        container = await container_repo.get_by_owner_id(user_id)
        if container:
            await container_repo.update_status(user_id, "stopped")

        logger.info("Stopped ECS service %s for user %s", service_name, user_id)

    async def start_user_service(self, user_id: str) -> None:
        """Scale a user's ECS service to 1 (running) with forced new deployment.

        Args:
            user_id: Clerk user ID.

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

        container = await container_repo.get_by_owner_id(user_id)
        if container:
            await container_repo.update_status(user_id, "provisioning")

        logger.info("Started ECS service %s for user %s", service_name, user_id)

    async def resize_user_container(
        self,
        user_id: str,
        new_cpu: str | None = None,
        new_memory: str | None = None,
        new_image: str | None = None,
    ) -> str:
        """Update a user's container with new CPU/memory/image and force redeploy.

        Registers a new task definition revision with the updated values,
        then updates the ECS service to use it with forceNewDeployment.

        Args:
            user_id: Owner ID (user or org).
            new_cpu: New CPU value (e.g. "1024"). None = keep current.
            new_memory: New memory value (e.g. "2048"). None = keep current.
            new_image: New container image. None = keep current.

        Returns:
            The ARN of the new task definition revision.
        """
        container = await container_repo.get_by_owner_id(user_id)
        if not container:
            raise EcsManagerError(f"No container found for user {user_id}", user_id)

        current_task_def_arn = container.get("task_definition_arn")
        if not current_task_def_arn:
            raise EcsManagerError(f"No task definition ARN for user {user_id}", user_id)

        service_name = self._service_name(user_id)

        try:
            # Read the current per-user task definition
            desc_resp = await asyncio.to_thread(self._ecs.describe_task_definition, taskDefinition=current_task_def_arn)
            base = desc_resp["taskDefinition"]

            # Build updated kwargs
            reg_kwargs = dict(
                family=base["family"],
                taskRoleArn=base.get("taskRoleArn", ""),
                executionRoleArn=base.get("executionRoleArn", ""),
                networkMode=base.get("networkMode", "awsvpc"),
                containerDefinitions=base["containerDefinitions"],
                volumes=base.get("volumes", []),
                requiresCompatibilities=base.get("requiresCompatibilities", ["FARGATE"]),
                cpu=new_cpu or base.get("cpu", "256"),
                memory=new_memory or base.get("memory", "512"),
            )
            if base.get("runtimePlatform"):
                reg_kwargs["runtimePlatform"] = base["runtimePlatform"]

            # Update image if specified
            if new_image and reg_kwargs["containerDefinitions"]:
                for container_def in reg_kwargs["containerDefinitions"]:
                    container_def["image"] = new_image

            # Register new revision
            reg_resp = await asyncio.to_thread(self._ecs.register_task_definition, **reg_kwargs)
            new_task_def_arn = reg_resp["taskDefinition"]["taskDefinitionArn"]
            logger.info("Registered resized task definition %s for user %s", new_task_def_arn, user_id)

            # Update service to use new task def + force redeploy
            await asyncio.to_thread(
                self._ecs.update_service,
                cluster=self._cluster,
                service=service_name,
                taskDefinition=new_task_def_arn,
                forceNewDeployment=True,
            )

            # Update DB record
            await self._update_container(user_id, task_definition_arn=new_task_def_arn, status="provisioning")

            logger.info(
                "Resized container for user %s: cpu=%s memory=%s image=%s",
                user_id,
                new_cpu,
                new_memory,
                new_image,
            )
            return new_task_def_arn

        except EcsManagerError:
            raise
        except Exception as e:
            raise EcsManagerError(f"Failed to resize container: {e}", user_id)

    async def delete_user_service(self, user_id: str) -> None:
        """Remove a user's ECS service and per-user resources entirely.

        1. Scale to 0 and delete ECS service
        2. Deregister per-user task definition (if present)
        3. Delete per-user EFS access point (if present)
        4. Delete Container DB record

        Args:
            user_id: Clerk user ID.

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
        container = await container_repo.get_by_owner_id(user_id)
        if container:
            # Deregister per-user task definition
            if container.get("task_definition_arn"):
                self._deregister_task_definition(container["task_definition_arn"])

            # Delete per-user EFS access point
            if container.get("access_point_id"):
                self._delete_access_point(container["access_point_id"])

            await container_repo.delete(user_id)

        # Sweep channel_links rows for this owner
        try:
            from core.repositories import channel_link_repo

            link_count = await channel_link_repo.sweep_by_owner(user_id)
            if link_count:
                logger.info(
                    "Swept %d channel_link rows for deleted container (owner=%s)",
                    link_count,
                    user_id,
                )
        except Exception:
            # Non-fatal — the container is already gone, orphan rows are
            # cheap to keep. Log and continue.
            logger.exception(
                "Failed to sweep channel_link rows for owner %s after container delete",
                user_id,
            )

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

        Opens a TCP connection to the gateway port. If the connection
        succeeds, the gateway is listening and healthy.

        Args:
            ip: The task's private IPv4 address.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            with socket.create_connection((ip, GATEWAY_PORT), timeout=5):
                return True
        except Exception:
            return False

    async def resolve_running_container(self, user_id: str) -> tuple[dict | None, str | None]:
        """Look up a user's container and discover its task IP.

        Accepts containers in "provisioning" or "running" status.
        If a provisioning container's task is healthy, automatically
        transitions the status to "running".

        Args:
            user_id: Clerk user ID.

        Returns:
            Tuple of (container_dict, task_ip) or (None, None) if no active container.
        """
        container = await container_repo.get_by_owner_id(user_id)
        if not container or container.get("status") not in ("provisioning", "running"):
            return None, None

        ip = self.discover_ip(container["service_name"])
        if not ip:
            return container, None

        # Auto-transition provisioning -> running once the task is reachable.
        # Also opportunistically capture the task ARN if we don't already have
        # one on the row — previously this field was silently missing on every
        # container row because no code path wrote it.
        if container.get("status") == "provisioning" and self.is_healthy(ip):
            try:
                fields = {
                    "substatus": "gateway_healthy",
                    "status": "running",
                }
                if not container.get("task_arn"):
                    try:
                        list_resp = self._ecs.list_tasks(
                            cluster=self._cluster,
                            serviceName=container["service_name"],
                            desiredStatus="RUNNING",
                        )
                        task_arns = list_resp.get("taskArns", [])
                        if task_arns:
                            fields["task_arn"] = task_arns[0]
                    except Exception:
                        # Task ARN is a nice-to-have for observability,
                        # not load-bearing for the transition itself.
                        pass
                await container_repo.update_fields(user_id, fields)
                logger.info(
                    "Container %s for user %s transitioned to running",
                    container["service_name"],
                    user_id,
                )
                # Update local dict to reflect changes
                container["status"] = "running"
                container["substatus"] = "gateway_healthy"
                if "task_arn" in fields:
                    container["task_arn"] = fields["task_arn"]
            except Exception:
                logger.warning(
                    "Failed to persist running status for user %s, will retry on next poll",
                    user_id,
                )

        return container, ip

    async def get_service_status(self, user_id: str) -> dict | None:
        """Get the Container record for a user.

        Args:
            user_id: Clerk user ID.

        Returns:
            The container dict, or None if not found.
        """
        return await container_repo.get_by_owner_id(user_id)

    # ------------------------------------------------------------------
    # Full provisioning flow
    # ------------------------------------------------------------------

    def _service_exists(self, service_name: str) -> dict | None:
        """Check if an ECS service exists and return its description, or None."""
        try:
            resp = self._ecs.describe_services(
                cluster=self._cluster,
                services=[service_name],
            )
            services = resp.get("services", [])
            if services and services[0].get("status") != "INACTIVE":
                return services[0]
        except Exception:
            pass
        return None

    async def provision_user_container(self, user_id: str, owner_type: str = "personal", tier: str = "free") -> str:
        """Provision or recover a user's container.

        Handles all scenarios:
        1. No service exists -> full provisioning (create service, write configs, start)
        2. Service exists with 0 desired -> write configs, scale up to 1
        3. Service exists and running -> force new deployment (restart)
        4. Container in error state -> clean up and re-provision

        Preserves EFS data (agent files) across all scenarios.

        Args:
            user_id: Clerk user ID.

        Returns:
            The ECS service name.

        Raises:
            EcsManagerError: If any provisioning step fails.
        """
        service_name = self._service_name(user_id)

        # Check current state
        existing = await container_repo.get_by_owner_id(user_id)
        svc = self._service_exists(service_name)

        # --- Scenario: Service exists (ACTIVE or DRAINING) ---
        if svc and svc.get("status") == "ACTIVE":
            desired = svc.get("desiredCount", 0)
            running = svc.get("runningCount", 0)

            if desired == 0:
                # Service exists but stopped -- write fresh configs and scale up
                logger.info("Service %s exists with 0 desired, scaling up", service_name)
                gateway_token = existing.get("gateway_token") if existing else secrets.token_urlsafe(32)

                # Update gateway token and write configs
                if existing:
                    await container_repo.update_fields(
                        user_id,
                        {
                            "status": "provisioning",
                            "substatus": "restarting",
                        },
                    )

                try:
                    await self.write_user_configs(user_id, gateway_token, tier=tier)
                except Exception as e:
                    logger.warning("Config write failed during restart: %s (continuing anyway)", e)

                try:
                    await self.start_user_service(user_id)
                except EcsManagerError:
                    await self._update_container(user_id, status="error", substatus=None)
                    raise

                return service_name

            elif running > 0:
                # Service exists and running -- force new deployment
                logger.info(
                    "Service %s running (%d tasks), forcing new deployment",
                    service_name,
                    running,
                )
                if existing:
                    await container_repo.update_fields(
                        user_id,
                        {
                            "status": "provisioning",
                            "substatus": "redeploying",
                        },
                    )

                try:
                    self._ecs.update_service(
                        cluster=self._cluster,
                        service=service_name,
                        forceNewDeployment=True,
                    )
                except Exception as e:
                    await self._update_container(user_id, status="error", substatus=None)
                    raise EcsManagerError(f"Failed to force redeploy: {e}", user_id)

                return service_name

            else:
                # Desired > 0 but not running yet -- ECS is working on it, just wait
                logger.info(
                    "Service %s has %d desired, %d running -- ECS is starting",
                    service_name,
                    desired,
                    running,
                )
                if existing and existing.get("status") != "provisioning":
                    await container_repo.update_fields(
                        user_id,
                        {
                            "status": "provisioning",
                            "substatus": "starting",
                        },
                    )
                return service_name

        # --- Scenario: No service exists -- full provisioning ---
        logger.info("No active service for user %s, full provisioning", user_id)

        # Clean up stale DB record if in error state
        if existing and existing.get("status") == "error":
            if existing.get("task_definition_arn"):
                try:
                    self._deregister_task_definition(existing["task_definition_arn"])
                except Exception:
                    pass
            # Don't delete access point -- preserves user's EFS data
            await container_repo.update_fields(
                user_id,
                {
                    "task_definition_arn": None,
                    "status": "provisioning",
                    "substatus": None,
                },
            )

        # Step 1: Generate gateway token
        gateway_token = secrets.token_urlsafe(32)

        # Step 2: Create ECS service (desiredCount=0)
        service_name = await self.create_user_service(user_id, gateway_token, owner_type=owner_type)

        # Step 3: Write configs to EFS
        try:
            await self.write_user_configs(user_id, gateway_token, tier=tier)
        except Exception as e:
            await self._update_container(user_id, status="error", substatus=None)
            raise EcsManagerError(f"Failed to write configs for user {user_id}: {e}", user_id)

        # Step 4: Start the container
        try:
            await self.start_user_service(user_id)
        except EcsManagerError:
            await self._update_container(user_id, status="error", substatus=None)
            raise

        logger.info("Provisioned container %s for user %s", service_name, user_id)

        # Step 5: Eagerly drive the provisioning → running transition. The
        # previous design relied on the next call to `resolve_running_container`
        # to flip the status when the task became reachable, which left rows
        # stuck at `provisioning` forever if the user's first chat hit an
        # upstream error (e.g. a bad model id) before the poll path fired.
        # Now we fire-and-forget a background poller immediately so the row
        # transitions as soon as the ECS task reports healthy, independent of
        # user activity.
        asyncio.create_task(self._await_running_transition(user_id))

        return service_name

    async def _await_running_transition(
        self,
        user_id: str,
        *,
        max_attempts: int = 30,
        interval_s: float = 4.0,
    ) -> None:
        """Background poller that drives provisioning → running eagerly.

        Polls ECS for the task's private IP, then TCP-connects to the gateway
        port, then writes status=running once both succeed. Also stores the
        task ARN on the row (previously never written because the old code
        path only updated status, not task_arn).

        Exits quietly on timeout — the next user request will still retry
        via `resolve_running_container`, so this is strictly an optimization
        for the happy path.
        """
        for attempt in range(max_attempts):
            try:
                container = await container_repo.get_by_owner_id(user_id)
                if not container or container.get("status") != "provisioning":
                    # Already transitioned (or the row is gone) — nothing to do.
                    return

                service_name = container["service_name"]
                list_resp = self._ecs.list_tasks(
                    cluster=self._cluster,
                    serviceName=service_name,
                    desiredStatus="RUNNING",
                )
                task_arns = list_resp.get("taskArns", [])
                if not task_arns:
                    await asyncio.sleep(interval_s)
                    continue

                task_arn = task_arns[0]
                desc_resp = self._ecs.describe_tasks(
                    cluster=self._cluster,
                    tasks=[task_arn],
                )
                tasks = desc_resp.get("tasks", [])
                if not tasks or tasks[0].get("lastStatus") != "RUNNING":
                    await asyncio.sleep(interval_s)
                    continue

                ip = None
                for attachment in tasks[0].get("attachments", []):
                    if attachment.get("type") == "ElasticNetworkInterface":
                        for detail in attachment.get("details", []):
                            if detail.get("name") == "privateIPv4Address":
                                ip = detail.get("value")
                                break
                if not ip or not self.is_healthy(ip):
                    await asyncio.sleep(interval_s)
                    continue

                await container_repo.update_fields(
                    user_id,
                    {
                        "status": "running",
                        "substatus": "gateway_healthy",
                        "task_arn": task_arn,
                    },
                )
                logger.info(
                    "Eagerly transitioned container %s to running (user=%s, task=%s)",
                    service_name,
                    user_id,
                    task_arn.split("/")[-1],
                )
                return
            except Exception:
                logger.exception(
                    "Unexpected error in eager running transition for %s (attempt %d)",
                    user_id,
                    attempt,
                )
                await asyncio.sleep(interval_s)

        logger.warning(
            "Eager provisioning -> running transition timed out for user %s after %d attempts",
            user_id,
            max_attempts,
        )

    async def write_user_configs(self, user_id: str, gateway_token: str, tier: str = "free") -> None:
        """Write OpenClaw config files + pre-paired device trust store to EFS.

        Writes four files to the user's EFS workspace:

        - `openclaw.json` — the gateway config (models, channels, scopes, etc.)
        - `.mcporter/mcporter.json` — MCP server registry (currently empty)
        - `devices/.node-device-key.pem` — the node role's private key, read
          by the in-container agent for loopback authentication
        - `devices/paired.json` — the combined trust store (node + operator)

        Also ensures the operator Ed25519 private key is present in the
        container's DynamoDB row (KMS-encrypted).

        Callers that only need to refresh the device trust store (e.g. after
        a config patch that updated openclaw.json in-place) should call
        :meth:`ensure_device_identities` instead to avoid overwriting the
        openclaw.json that was just patched.
        """
        config_json = write_openclaw_config(
            region=settings.AWS_REGION,
            gateway_token=gateway_token,
            proxy_base_url=settings.PROXY_BASE_URL,
            tier=tier,
        )
        workspace = get_workspace()
        workspace.write_file(user_id, "openclaw.json", config_json)
        workspace.write_file(user_id, ".mcporter/mcporter.json", write_mcporter_config())
        await self.ensure_device_identities(user_id, gateway_token)

    async def ensure_device_identities(self, user_id: str, gateway_token: str) -> None:
        """Idempotently provision node + operator device identities.

        Separated from :meth:`write_user_configs` so callers can refresh the
        device trust store without touching openclaw.json — important for
        the redeploy path that patches openclaw.json in-place and just
        needs the operator entry backfilled after an OpenClaw 4.5 upgrade.

        What this writes:

        - `devices/.node-device-key.pem` (if not already on EFS)
        - `devices/paired.json` (always overwritten with the latest node +
          operator entries)
        - DynamoDB `containers` row `operator_device_id` + `operator_priv_key_enc`
          (latter is KMS-encrypted with encryption-context bound to owner_id)

        Safe to call repeatedly: reuses existing node PEM and existing
        KMS-encrypted operator seed when present. Only regenerates when the
        ciphertext is missing or undecryptable.
        """
        from core.crypto import kms_secrets
        from core.crypto.operator_device import (
            BACKEND_OPERATOR_SCOPES,
            build_paired_operator_entry,
            generate_operator_device,
            load_operator_device_from_seed,
        )

        workspace = get_workspace()

        # --- Node device identity -------------------------------------------
        # Reuse the existing key if the PEM is already on EFS (so the node's
        # in-container agent keeps the same identity across restarts),
        # otherwise generate fresh.
        try:
            existing_pem = workspace.read_file(user_id, "devices/.node-device-key.pem")
            node_identity = load_node_device_identity(existing_pem)
            logger.info("Reusing existing node device key for user %s", user_id)
        except Exception:
            node_identity = generate_node_device_identity()
            workspace.write_file(
                user_id,
                "devices/.node-device-key.pem",
                node_identity["private_key_pem"],
            )
            logger.info("Generated new node device key for user %s", user_id)

        # --- Operator device identity (OpenClaw 4.5 scoped-auth requirement) -
        # Bind the ciphertext to the owner_id via KMS encryption context — a
        # stolen row can't be replayed against a different container.
        kms_ctx = {"owner_id": user_id, "purpose": "operator-device-seed"}
        existing_container = await container_repo.get_by_owner_id(user_id)
        existing_enc_seed = existing_container.get("operator_priv_key_enc") if existing_container else None

        if existing_enc_seed:
            try:
                seed_bytes = kms_secrets.decrypt_bytes(existing_enc_seed, encryption_context=kms_ctx)
                operator_identity = load_operator_device_from_seed(seed_bytes)
                logger.info("Reusing existing operator device for user %s", user_id)
            except Exception as exc:
                # KMS decrypt failure or corrupted ciphertext — regenerate
                # rather than wedging the container. The old encrypted blob is
                # replaced below before the container boots, so the mismatch
                # never becomes visible to the gateway.
                logger.warning(
                    "Failed to decrypt existing operator device for user %s (%s); regenerating",
                    user_id,
                    exc,
                )
                operator_identity = generate_operator_device()
        else:
            operator_identity = generate_operator_device()
            logger.info("Generated new operator device for user %s", user_id)

        # Always re-encrypt and persist. This covers both "first provision"
        # and "we just regenerated after a decrypt failure" — the DynamoDB row
        # becomes the source of truth alongside the paired.json on EFS.
        enc_seed_b64 = kms_secrets.encrypt_bytes(operator_identity.private_key_seed, encryption_context=kms_ctx)
        await container_repo.update_fields(
            user_id,
            {
                "operator_device_id": operator_identity.device_id,
                "operator_priv_key_enc": enc_seed_b64,
            },
        )

        operator_entry = build_paired_operator_entry(
            operator_identity,
            gateway_token=gateway_token,
            scopes=BACKEND_OPERATOR_SCOPES,
        )

        paired_json = build_device_paired_json(
            node_identity["device_id"],
            node_identity["public_key_b64"],
            operator_entry=operator_entry,
        )
        workspace.write_file(user_id, "devices/paired.json", paired_json)
