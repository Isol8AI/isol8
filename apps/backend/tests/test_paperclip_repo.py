"""Tests for paperclip_repo using moto's DynamoDB mock."""

from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from core.repositories.paperclip_repo import PaperclipCompany, PaperclipRepo

TABLE_NAME = "test-paperclip-companies"


@pytest.fixture
def repo():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "scheduled_purge_at", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by-status-purge-at",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "scheduled_purge_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                },
            ],
        )
        yield PaperclipRepo(table_name=TABLE_NAME, region="us-east-1")


def _make_company(user_id="u1", status="active", **kwargs):
    now = datetime.now(timezone.utc)
    return PaperclipCompany(
        user_id=user_id,
        company_id=kwargs.get("company_id", f"co_{user_id}"),
        board_api_key_encrypted="enc_key",
        service_token_encrypted="enc_token",
        status=status,
        created_at=kwargs.get("created_at", now),
        updated_at=kwargs.get("updated_at", now),
        last_error=kwargs.get("last_error"),
        scheduled_purge_at=kwargs.get("scheduled_purge_at"),
    )


def test_put_and_get_round_trips(repo):
    company = _make_company(user_id="user_123")
    repo.put(company)
    retrieved = repo.get("user_123")
    assert retrieved is not None
    assert retrieved.company_id == "co_user_123"
    assert retrieved.status == "active"


def test_get_returns_none_for_missing(repo):
    assert repo.get("user_does_not_exist") is None


def test_update_status_transitions_to_disabled(repo):
    repo.put(_make_company(user_id="user_456"))
    purge_at = datetime(2026, 5, 27, tzinfo=timezone.utc)
    repo.update_status("user_456", status="disabled", scheduled_purge_at=purge_at)
    retrieved = repo.get("user_456")
    assert retrieved.status == "disabled"
    assert retrieved.scheduled_purge_at == purge_at


def test_update_status_records_last_error(repo):
    repo.put(_make_company(user_id="user_x"))
    repo.update_status("user_x", status="failed", last_error="api timeout")
    retrieved = repo.get("user_x")
    assert retrieved.status == "failed"
    assert retrieved.last_error == "api timeout"


def test_delete_removes_row(repo):
    repo.put(_make_company(user_id="user_789"))
    repo.delete("user_789")
    assert repo.get("user_789") is None


def test_scan_purge_due_returns_overdue_disabled(repo):
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=1)
    future = now + timedelta(days=10)
    # disabled and overdue -> should be returned
    repo.put(_make_company(user_id="overdue", status="disabled", scheduled_purge_at=past))
    # disabled but not yet due -> should NOT be returned
    repo.put(_make_company(user_id="not_yet", status="disabled", scheduled_purge_at=future))
    # active -> should NOT be returned (different status)
    repo.put(_make_company(user_id="still_active", status="active"))
    due = repo.scan_purge_due(now)
    user_ids = {c.user_id for c in due}
    assert user_ids == {"overdue"}
