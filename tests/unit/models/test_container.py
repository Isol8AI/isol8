"""Tests for the Container model."""

import pytest
from sqlalchemy import select

from models.container import Container


class TestContainerModel:
    """Test Container model CRUD and constraints."""

    @pytest.mark.asyncio
    async def test_create_container(self, db_session, test_user):
        """Test creating a container record."""
        container = Container(
            user_id=test_user.id,
            port=19000,
            container_id="abc123def456",
            status="running",
        )
        db_session.add(container)
        await db_session.flush()

        assert container.id is not None
        assert container.user_id == test_user.id
        assert container.port == 19000
        assert container.container_id == "abc123def456"
        assert container.status == "running"
        assert container.created_at is not None

    @pytest.mark.asyncio
    async def test_container_default_status(self, db_session, test_user):
        """Test default status is 'provisioning'."""
        container = Container(
            user_id=test_user.id,
            port=19001,
        )
        db_session.add(container)
        await db_session.flush()

        assert container.status == "provisioning"

    @pytest.mark.asyncio
    async def test_container_nullable_docker_id(self, db_session, test_user):
        """Test container_id can be null (before Docker container is created)."""
        container = Container(
            user_id=test_user.id,
            port=19002,
            status="provisioning",
        )
        db_session.add(container)
        await db_session.flush()

        assert container.container_id is None

    @pytest.mark.asyncio
    async def test_unique_user_constraint(self, db_session, test_user):
        """Test one container per user constraint."""
        c1 = Container(user_id=test_user.id, port=19000, status="running")
        db_session.add(c1)
        await db_session.flush()

        c2 = Container(user_id=test_user.id, port=19001, status="running")
        db_session.add(c2)

        with pytest.raises(Exception):  # IntegrityError
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_unique_port_constraint(self, db_session, test_user, other_user):
        """Test unique port constraint."""
        c1 = Container(user_id=test_user.id, port=19000, status="running")
        db_session.add(c1)
        await db_session.flush()

        c2 = Container(user_id=other_user.id, port=19000, status="running")
        db_session.add(c2)

        with pytest.raises(Exception):  # IntegrityError
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_different_users_different_ports(self, db_session, test_user, other_user):
        """Test multiple users can have containers on different ports."""
        c1 = Container(user_id=test_user.id, port=19000, status="running")
        c2 = Container(user_id=other_user.id, port=19001, status="running")
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
            port=19000,
            container_id="abc123",
            status="running",
        )
        db_session.add(container)
        await db_session.flush()

        result = await db_session.execute(select(Container).where(Container.user_id == test_user.id))
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.port == 19000

    @pytest.mark.asyncio
    async def test_update_status(self, db_session, test_user):
        """Test updating container status."""
        container = Container(
            user_id=test_user.id,
            port=19000,
            status="provisioning",
        )
        db_session.add(container)
        await db_session.flush()

        container.status = "running"
        container.container_id = "new_docker_id"
        await db_session.flush()

        result = await db_session.execute(select(Container).where(Container.user_id == test_user.id))
        found = result.scalar_one()
        assert found.status == "running"
        assert found.container_id == "new_docker_id"

    @pytest.mark.asyncio
    async def test_repr(self, db_session, test_user):
        """Test string representation."""
        container = Container(
            user_id=test_user.id,
            port=19000,
            status="running",
        )
        repr_str = repr(container)
        assert "user_id=" in repr_str
        assert "port=19000" in repr_str
        assert "status=running" in repr_str
