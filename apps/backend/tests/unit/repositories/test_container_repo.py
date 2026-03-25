"""Tests for container DynamoDB repository."""

import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def dynamodb_table():
    """Create a moto DynamoDB containers table with GSIs."""
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")
        table = client.create_table(
            TableName="test-containers",
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "gateway_token", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "gateway-token-index",
                    "KeySchema": [{"AttributeName": "gateway_token", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "status-index",
                    "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.meta.client.get_waiter("table_exists").wait(TableName="test-containers")

        with (
            patch("core.dynamodb._table_prefix", "test-"),
            patch("core.dynamodb._dynamodb_resource", client),
        ):
            yield table


@pytest.mark.asyncio
async def test_upsert_creates_new(dynamodb_table):
    from core.repositories import container_repo

    result = await container_repo.upsert(
        "user_1",
        {
            "gateway_token": "tok_abc",
            "status": "provisioning",
        },
    )
    assert result["user_id"] == "user_1"
    assert result["gateway_token"] == "tok_abc"
    assert "id" in result
    assert "created_at" in result


@pytest.mark.asyncio
async def test_upsert_preserves_id_and_created_at(dynamodb_table):
    from core.repositories import container_repo

    first = await container_repo.upsert(
        "user_1",
        {
            "gateway_token": "tok_abc",
            "status": "provisioning",
        },
    )

    second = await container_repo.upsert(
        "user_1",
        {
            "gateway_token": "tok_abc",
            "status": "running",
        },
    )

    assert second["id"] == first["id"]
    assert second["created_at"] == first["created_at"]
    assert second["status"] == "running"


@pytest.mark.asyncio
async def test_get_by_user_id(dynamodb_table):
    from core.repositories import container_repo

    await container_repo.upsert(
        "user_2",
        {
            "gateway_token": "tok_def",
            "status": "running",
        },
    )
    item = await container_repo.get_by_user_id("user_2")
    assert item is not None
    assert item["status"] == "running"


@pytest.mark.asyncio
async def test_get_by_user_id_nonexistent(dynamodb_table):
    from core.repositories import container_repo

    item = await container_repo.get_by_user_id("ghost")
    assert item is None


@pytest.mark.asyncio
async def test_get_by_gateway_token(dynamodb_table):
    from core.repositories import container_repo

    await container_repo.upsert(
        "user_3",
        {
            "gateway_token": "tok_ghi",
            "status": "running",
        },
    )
    item = await container_repo.get_by_gateway_token("tok_ghi")
    assert item is not None
    assert item["user_id"] == "user_3"


@pytest.mark.asyncio
async def test_get_by_gateway_token_nonexistent(dynamodb_table):
    from core.repositories import container_repo

    item = await container_repo.get_by_gateway_token("nope")
    assert item is None


@pytest.mark.asyncio
async def test_get_by_status(dynamodb_table):
    from core.repositories import container_repo

    await container_repo.upsert("user_a", {"gateway_token": "t1", "status": "running"})
    await container_repo.upsert("user_b", {"gateway_token": "t2", "status": "stopped"})
    await container_repo.upsert("user_c", {"gateway_token": "t3", "status": "running"})

    running = await container_repo.get_by_status("running")
    assert len(running) == 2
    user_ids = {item["user_id"] for item in running}
    assert user_ids == {"user_a", "user_c"}


@pytest.mark.asyncio
async def test_update_status(dynamodb_table):
    from core.repositories import container_repo

    await container_repo.upsert("user_s", {"gateway_token": "ts", "status": "provisioning"})
    result = await container_repo.update_status("user_s", "running", "gateway_healthy")
    assert result is not None
    assert result["status"] == "running"
    assert result["substatus"] == "gateway_healthy"


@pytest.mark.asyncio
async def test_update_status_nonexistent(dynamodb_table):
    from core.repositories import container_repo

    result = await container_repo.update_status("ghost", "running")
    assert result is None


@pytest.mark.asyncio
async def test_update_fields(dynamodb_table):
    from core.repositories import container_repo

    await container_repo.upsert("user_f", {"gateway_token": "tf", "status": "running"})
    result = await container_repo.update_fields("user_f", {"task_arn": "arn:aws:ecs:task/123"})
    assert result is not None
    assert result["task_arn"] == "arn:aws:ecs:task/123"


@pytest.mark.asyncio
async def test_delete(dynamodb_table):
    from core.repositories import container_repo

    await container_repo.upsert("user_d", {"gateway_token": "td", "status": "running"})
    await container_repo.delete("user_d")
    item = await container_repo.get_by_user_id("user_d")
    assert item is None


@pytest.mark.asyncio
async def test_upsert_org_container(dynamodb_table):
    """Org containers store owner_type and org_id fields."""
    from core.repositories import container_repo

    result = await container_repo.upsert(
        "org_456",
        {
            "gateway_token": "tok_org",
            "status": "provisioning",
            "owner_type": "org",
            "org_id": "org_456",
        },
    )
    assert result["user_id"] == "org_456"
    assert result["owner_type"] == "org"
    assert result["org_id"] == "org_456"


@pytest.mark.asyncio
async def test_get_by_owner_id_alias(dynamodb_table):
    """get_by_owner_id is an alias for get_by_user_id."""
    from core.repositories import container_repo

    await container_repo.upsert(
        "org_456",
        {"gateway_token": "tok_org", "status": "running", "owner_type": "org"},
    )
    item = await container_repo.get_by_owner_id("org_456")
    assert item is not None
    assert item["owner_type"] == "org"
