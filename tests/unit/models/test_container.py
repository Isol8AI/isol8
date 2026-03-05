"""Tests for the Container model (ECS Fargate)."""

import pytest
from sqlalchemy import select

from models.container import Container


class TestContainerModel:
    """Test Container model CRUD and constraints."""

    @pytest.mark.asyncio
    async def test_create_container(self, db_session, test_user):
        """Test creating a container record with ECS Fargate fields."""
        container = Container(
            user_id=test_user.id,
            service_name="openclaw-user_tes",
            task_arn="arn:aws:ecs:us-east-1:123456789:task/cluster/abc123",
            gateway_token="tok-abc123",
            status="running",
        )
        db_session.add(container)
        await db_session.flush()

        assert container.id is not None
        assert container.user_id == test_user.id
        assert container.service_name == "openclaw-user_tes"
        assert container.task_arn == "arn:aws:ecs:us-east-1:123456789:task/cluster/abc123"
        assert container.gateway_token == "tok-abc123"
        assert container.status == "running"
        assert container.created_at is not None

    @pytest.mark.asyncio
    async def test_container_default_status(self, db_session, test_user):
        """Test default status is 'stopped'."""
        container = Container(
            user_id=test_user.id,
            gateway_token="tok-default",
        )
        db_session.add(container)
        await db_session.flush()

        assert container.status == "stopped"

    @pytest.mark.asyncio
    async def test_container_nullable_ecs_fields(self, db_session, test_user):
        """Test service_name and task_arn can be null (before ECS service is created)."""
        container = Container(
            user_id=test_user.id,
            gateway_token="tok-nullable",
            status="provisioning",
        )
        db_session.add(container)
        await db_session.flush()

        assert container.service_name is None
        assert container.task_arn is None

    @pytest.mark.asyncio
    async def test_unique_user_constraint(self, db_session, test_user):
        """Test one container per user constraint."""
        c1 = Container(user_id=test_user.id, gateway_token="tok-1", status="running")
        db_session.add(c1)
        await db_session.flush()

        c2 = Container(user_id=test_user.id, gateway_token="tok-2", status="running")
        db_session.add(c2)

        with pytest.raises(Exception):  # IntegrityError
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_unique_service_name_constraint(self, db_session, test_user, other_user):
        """Test unique service_name constraint."""
        c1 = Container(
            user_id=test_user.id,
            service_name="openclaw-shared",
            gateway_token="tok-svc1",
            status="running",
        )
        db_session.add(c1)
        await db_session.flush()

        c2 = Container(
            user_id=other_user.id,
            service_name="openclaw-shared",
            gateway_token="tok-svc2",
            status="running",
        )
        db_session.add(c2)

        with pytest.raises(Exception):  # IntegrityError
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_different_users_different_services(self, db_session, test_user, other_user):
        """Test multiple users can have containers with different service names."""
        c1 = Container(
            user_id=test_user.id,
            service_name="openclaw-user1",
            gateway_token="tok-u1",
            status="running",
        )
        c2 = Container(
            user_id=other_user.id,
            service_name="openclaw-user2",
            gateway_token="tok-u2",
            status="running",
        )
        db_session.add(c1)
        db_session.add(c2)
        await db_session.flush()

        result = await db_session.execute(select(Container))
        containers = list(result.scalars().all())
        assert len(containers) == 2

    @pytest.mark.asyncio
    async def test_query_by_user_id(self, db_session, test_user):
        """Test querying container by user_id."""
        container = Container(
            user_id=test_user.id,
            service_name="openclaw-query",
            gateway_token="tok-query",
            status="running",
        )
        db_session.add(container)
        await db_session.flush()

        result = await db_session.execute(select(Container).where(Container.user_id == test_user.id))
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.service_name == "openclaw-query"

    @pytest.mark.asyncio
    async def test_query_by_status(self, db_session, test_user):
        """Test querying containers by status."""
        container = Container(
            user_id=test_user.id,
            service_name="openclaw-status",
            gateway_token="tok-status",
            status="running",
        )
        db_session.add(container)
        await db_session.flush()

        result = await db_session.execute(select(Container).where(Container.status == "running"))
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.user_id == test_user.id

    @pytest.mark.asyncio
    async def test_update_status(self, db_session, test_user):
        """Test updating container status and task ARN."""
        container = Container(
            user_id=test_user.id,
            service_name="openclaw-update",
            gateway_token="tok-update",
            status="provisioning",
        )
        db_session.add(container)
        await db_session.flush()

        container.status = "running"
        container.task_arn = "arn:aws:ecs:us-east-1:123456789:task/cluster/new-task"
        await db_session.flush()

        result = await db_session.execute(select(Container).where(Container.user_id == test_user.id))
        found = result.scalar_one()
        assert found.status == "running"
        assert found.task_arn == "arn:aws:ecs:us-east-1:123456789:task/cluster/new-task"

    @pytest.mark.asyncio
    async def test_container_substatus(self, db_session, test_user):
        """Test substatus column can be set and read."""
        container = Container(
            user_id=test_user.id,
            gateway_token="tok-substatus",
            status="provisioning",
            substatus="efs_created",
        )
        db_session.add(container)
        await db_session.flush()

        result = await db_session.execute(select(Container).where(Container.user_id == test_user.id))
        found = result.scalar_one()
        assert found.substatus == "efs_created"

    @pytest.mark.asyncio
    async def test_container_substatus_nullable(self, db_session, test_user):
        """Test substatus defaults to None."""
        container = Container(
            user_id=test_user.id,
            gateway_token="tok-sub-null",
            status="running",
        )
        db_session.add(container)
        await db_session.flush()
        assert container.substatus is None

    @pytest.mark.asyncio
    async def test_repr(self, db_session, test_user):
        """Test string representation includes ECS fields."""
        container = Container(
            user_id=test_user.id,
            service_name="openclaw-repr",
            gateway_token="tok-repr",
            status="running",
        )
        repr_str = repr(container)
        assert "user_id=" in repr_str
        assert "service_name=openclaw-repr" in repr_str
        assert "status=running" in repr_str
