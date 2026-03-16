"""Tests for audit log model."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from models.audit_log import AuditLog, AuditEventType


class TestAuditEventType:
    """Tests for AuditEventType enum."""

    def test_event_type_values(self):
        """AuditEventType enum has expected string values."""
        assert AuditEventType.USER_SIGNED_IN.value == "user_signed_in"
        assert AuditEventType.USER_SIGNED_OUT.value == "user_signed_out"
        assert AuditEventType.AGENT_CREATED.value == "agent_created"
        assert AuditEventType.AGENT_DELETED.value == "agent_deleted"

    def test_event_type_is_string_enum(self):
        """AuditEventType values can be used as strings."""
        assert isinstance(AuditEventType.USER_SIGNED_IN, str)
        assert AuditEventType.USER_SIGNED_IN == "user_signed_in"


class TestAuditLogCreate:
    """Tests for AuditLog creation."""

    def test_create_basic_log(self):
        """Can create basic audit log entry."""
        log = AuditLog.create(
            id="log_123",
            event_type=AuditEventType.USER_SIGNED_IN,
            actor_user_id="user_456",
        )

        assert log.id == "log_123"
        assert log.event_type == AuditEventType.USER_SIGNED_IN
        assert log.actor_user_id == "user_456"
        assert log.target_user_id is None
        assert log.event_data is None

    def test_create_log_with_all_fields(self):
        """Can create audit log with all fields."""
        log = AuditLog.create(
            id="log_123",
            event_type=AuditEventType.AGENT_CREATED,
            actor_user_id="user_456",
            target_user_id="user_789",
            event_data={"agent_name": "luna"},
        )

        assert log.actor_user_id == "user_456"
        assert log.target_user_id == "user_789"
        assert log.event_data == {"agent_name": "luna"}


class TestAuditLogApiResponse:
    """Tests for AuditLog API response formatting."""

    def test_to_api_response(self):
        """to_api_response formats correctly."""
        log = AuditLog.create(
            id="log_123",
            event_type=AuditEventType.AGENT_CREATED,
            actor_user_id="user_456",
            event_data={"agent_name": "luna"},
        )
        log.created_at = datetime(2024, 1, 15, 10, 30, 0)

        response = log.to_api_response()

        assert response["id"] == "log_123"
        assert response["event_type"] == "agent_created"
        assert response["actor_user_id"] == "user_456"
        assert response["target_user_id"] is None
        assert response["event_data"] == {"agent_name": "luna"}
        assert response["created_at"] == "2024-01-15T10:30:00"

    def test_to_api_response_minimal(self):
        """to_api_response works with minimal data."""
        log = AuditLog.create(
            id="log_123",
            event_type=AuditEventType.USER_SIGNED_OUT,
        )
        log.created_at = datetime.utcnow()

        response = log.to_api_response()

        assert response["id"] == "log_123"
        assert response["event_type"] == "user_signed_out"
        assert response["actor_user_id"] is None
        assert response["event_data"] is None


class TestAuditLogPersistence:
    """Tests for AuditLog database persistence."""

    @pytest.mark.asyncio
    async def test_audit_log_persistence(self, db_session, test_user):
        """Audit log can be persisted and retrieved."""
        log = AuditLog.create(
            id=str(uuid.uuid4()),
            event_type=AuditEventType.USER_SIGNED_IN,
            actor_user_id=test_user.id,
        )
        db_session.add(log)
        await db_session.flush()

        result = await db_session.execute(select(AuditLog).where(AuditLog.id == log.id))
        fetched = result.scalar_one()

        assert fetched.event_type == AuditEventType.USER_SIGNED_IN
        assert fetched.actor_user_id == test_user.id
        assert fetched.created_at is not None

    @pytest.mark.asyncio
    async def test_audit_log_with_event_data_persistence(self, db_session, test_user):
        """Audit log with event_data persists correctly."""
        log = AuditLog.create(
            id=str(uuid.uuid4()),
            event_type=AuditEventType.AGENT_CREATED,
            actor_user_id=test_user.id,
            event_data={"agent_name": "luna"},
        )
        db_session.add(log)
        await db_session.flush()

        result = await db_session.execute(select(AuditLog).where(AuditLog.id == log.id))
        fetched = result.scalar_one()

        assert fetched.event_data["agent_name"] == "luna"

    @pytest.mark.asyncio
    async def test_multiple_audit_logs_query(self, db_session, test_user):
        """Can query multiple audit logs by actor."""
        log1 = AuditLog.create(
            id=str(uuid.uuid4()),
            event_type=AuditEventType.AGENT_CREATED,
            actor_user_id=test_user.id,
        )
        log2 = AuditLog.create(
            id=str(uuid.uuid4()),
            event_type=AuditEventType.AGENT_DELETED,
            actor_user_id=test_user.id,
        )
        db_session.add(log1)
        db_session.add(log2)
        await db_session.flush()

        result = await db_session.execute(
            select(AuditLog).where(AuditLog.actor_user_id == test_user.id).order_by(AuditLog.created_at)
        )
        logs = result.scalars().all()

        assert len(logs) == 2
        assert logs[0].event_type == AuditEventType.AGENT_CREATED
        assert logs[1].event_type == AuditEventType.AGENT_DELETED
