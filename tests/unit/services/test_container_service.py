"""Tests for ContainerService database operations."""

import pytest

from core.services.container_service import ContainerService


class TestContainerService:
    """Test ContainerService CRUD operations."""

    @pytest.fixture
    def service(self, db_session):
        """Create service instance."""
        return ContainerService(db_session)

    @pytest.mark.asyncio
    async def test_get_container_not_found(self, service, test_user):
        """Test getting non-existent container returns None."""
        result = await service.get_container(user_id=test_user.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_create_container(self, service, test_user):
        """Test creating a container record."""
        container = await service.create_container(
            user_id=test_user.id,
            port=19000,
            container_id="abc123",
            status="running",
        )
        assert container is not None
        assert container.user_id == test_user.id
        assert container.port == 19000
        assert container.container_id == "abc123"
        assert container.status == "running"

    @pytest.mark.asyncio
    async def test_create_container_default_status(self, service, test_user):
        """Test container defaults to provisioning status."""
        container = await service.create_container(
            user_id=test_user.id,
            port=19000,
        )
        assert container.status == "provisioning"
        assert container.container_id is None

    @pytest.mark.asyncio
    async def test_get_container(self, service, test_user):
        """Test getting an existing container."""
        await service.create_container(
            user_id=test_user.id,
            port=19000,
            status="running",
        )

        container = await service.get_container(user_id=test_user.id)
        assert container is not None
        assert container.port == 19000

    @pytest.mark.asyncio
    async def test_update_status(self, service, test_user):
        """Test updating container status."""
        await service.create_container(
            user_id=test_user.id,
            port=19000,
            status="provisioning",
        )

        updated = await service.update_status(
            user_id=test_user.id,
            status="running",
            container_id="docker_abc123",
        )

        assert updated is not None
        assert updated.status == "running"
        assert updated.container_id == "docker_abc123"

    @pytest.mark.asyncio
    async def test_update_status_not_found(self, service, test_user):
        """Test updating non-existent container returns None."""
        result = await service.update_status(
            user_id="nonexistent_user",
            status="running",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_container(self, service, test_user):
        """Test deleting a container record."""
        await service.create_container(
            user_id=test_user.id,
            port=19000,
        )

        deleted = await service.delete_container(user_id=test_user.id)
        assert deleted is True

        # Verify it's gone
        result = await service.get_container(user_id=test_user.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_container(self, service, test_user):
        """Test deleting non-existent container returns False."""
        deleted = await service.delete_container(user_id="nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_containers(self, service, test_user, other_user):
        """Test listing all containers."""
        await service.create_container(user_id=test_user.id, port=19000, status="running")
        await service.create_container(user_id=other_user.id, port=19001, status="stopped")

        containers = await service.list_containers()
        assert len(containers) == 2

    @pytest.mark.asyncio
    async def test_list_containers_by_status(self, service, test_user, other_user):
        """Test filtering containers by status."""
        await service.create_container(user_id=test_user.id, port=19000, status="running")
        await service.create_container(user_id=other_user.id, port=19001, status="stopped")

        running = await service.list_containers(status="running")
        assert len(running) == 1
        assert running[0].user_id == test_user.id

        stopped = await service.list_containers(status="stopped")
        assert len(stopped) == 1
        assert stopped[0].user_id == other_user.id

    @pytest.mark.asyncio
    async def test_get_next_available_port(self, service, test_user, other_user):
        """Test port allocation finds next available port."""
        # No containers — first port
        port = await service.get_next_available_port()
        assert port == 19000

        # Create container on 19000
        await service.create_container(user_id=test_user.id, port=19000)

        # Next available should be 19001
        port = await service.get_next_available_port()
        assert port == 19001

    @pytest.mark.asyncio
    async def test_get_next_available_port_gaps(self, service, test_user, other_user):
        """Test port allocation fills gaps."""
        # Create containers on 19000 and 19002 (gap at 19001)
        await service.create_container(user_id=test_user.id, port=19000)
        await service.create_container(user_id=other_user.id, port=19002)

        # Should find 19001
        port = await service.get_next_available_port()
        assert port == 19001
