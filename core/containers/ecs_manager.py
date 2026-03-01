"""
ECS Fargate service manager for per-user OpenClaw gateways.

Each subscriber gets a dedicated ECS Service (desiredCount 0/1) that
runs an OpenClaw gateway container. Cloud Map handles service discovery
so the control plane can route requests to the correct task IP.
"""

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
        self._sd = boto3.client("servicediscovery", region_name=settings.AWS_REGION)
        self._cluster = settings.ECS_CLUSTER_ARN
        self._task_def = settings.ECS_TASK_DEFINITION
        self._subnets = [s.strip() for s in settings.ECS_SUBNETS.split(",") if s.strip()]
        self._security_groups = [settings.ECS_SECURITY_GROUP_ID]
        self._cloud_map_service_arn = settings.CLOUD_MAP_SERVICE_ARN
        self._namespace = settings.CLOUD_MAP_NAMESPACE_ID

    def _service_name(self, user_id: str) -> str:
        """Generate deterministic service name from user_id."""
        return f"openclaw-{user_id[:8]}"

    async def create_user_service(self, user_id: str, gateway_token: str, db: AsyncSession) -> str:
        """Create an ECS Service for a user.

        The gateway container starts with --allow-unconfigured, so no token
        override is needed at service creation time. The gateway_token is
        stored in the Container DB record for later use when routing
        requests through the HTTP client.

        Args:
            user_id: Clerk user ID.
            gateway_token: Auth token for the OpenClaw gateway HTTP API.
            db: Async database session.

        Returns:
            The ECS service name.

        Raises:
            EcsManagerError: If the ECS create_service call fails.
        """
        service_name = self._service_name(user_id)

        try:
            self._ecs.create_service(
                cluster=self._cluster,
                serviceName=service_name,
                taskDefinition=self._task_def,
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
                enableExecuteCommand=True,
            )
        except Exception as e:
            logger.error(
                "Failed to create ECS service %s for user %s: %s",
                service_name,
                user_id,
                e,
            )
            raise EcsManagerError(f"Failed to create ECS service: {e}", user_id)

        # Upsert container record
        result = await db.execute(select(Container).where(Container.user_id == user_id))
        container = result.scalar_one_or_none()
        if container:
            container.service_name = service_name
            container.gateway_token = gateway_token
            container.status = "provisioning"
        else:
            container = Container(
                user_id=user_id,
                service_name=service_name,
                gateway_token=gateway_token,
                status="provisioning",
            )
            db.add(container)
        await db.commit()

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
        """Remove a user's ECS service entirely.

        Scales to 0 first, then deletes the service and removes the
        Container DB record.

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

        # Delete container record from DB
        result = await db.execute(select(Container).where(Container.user_id == user_id))
        container = result.scalar_one_or_none()
        if container:
            await db.delete(container)
            await db.commit()

        logger.info("Deleted ECS service %s for user %s", service_name, user_id)

    def discover_ip(self, service_name: str) -> str | None:
        """Discover a task's private IP via Cloud Map service discovery.

        Args:
            service_name: The ECS service name registered in Cloud Map.

        Returns:
            The task's private IPv4 address, or None if not found.
        """
        try:
            response = self._sd.discover_instances(
                NamespaceName=self._namespace,
                ServiceName=service_name,
            )
            instances = response.get("Instances", [])
            if instances:
                attrs = instances[0].get("Attributes", {})
                return attrs.get("AWS_INSTANCE_IPV4")
        except Exception as e:
            logger.error("Cloud Map discovery failed for %s: %s", service_name, e)
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
