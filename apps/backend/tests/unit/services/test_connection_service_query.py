"""Unit tests for ConnectionService.query_by_user_id (the new GSI lookup)."""

from __future__ import annotations

import os
import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def ddb_table_with_gsi():
    """Stand up an in-memory DDB ws-connections table with the by-user-id GSI."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="ws-conn-test",
            KeySchema=[{"AttributeName": "connectionId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "connectionId", "AttributeType": "S"},
                {"AttributeName": "userId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by-user-id",
                    "KeySchema": [{"AttributeName": "userId", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield "ws-conn-test"


@pytest.mark.asyncio
async def test_query_by_user_id_returns_only_matching_user_conn_ids(ddb_table_with_gsi):
    from core.services.connection_service import ConnectionService

    svc = ConnectionService(table_name=ddb_table_with_gsi, region_name="us-east-1")
    svc.store_connection("conn_a1", "user_a", None)
    svc.store_connection("conn_a2", "user_a", None)
    svc.store_connection("conn_b1", "user_b", None)

    result = await svc.query_by_user_id("user_a")
    assert sorted(result) == ["conn_a1", "conn_a2"]

    result_b = await svc.query_by_user_id("user_b")
    assert result_b == ["conn_b1"]

    result_missing = await svc.query_by_user_id("user_nope")
    assert result_missing == []


@pytest.mark.asyncio
async def test_query_by_user_id_paginates(ddb_table_with_gsi):
    """Multiple page Query results aggregate into a single list."""
    from core.services.connection_service import ConnectionService

    svc = ConnectionService(table_name=ddb_table_with_gsi, region_name="us-east-1")
    for i in range(25):
        svc.store_connection(f"conn_{i:02d}", "user_p", None)

    result = await svc.query_by_user_id("user_p")
    assert len(result) == 25
    assert sorted(result) == sorted([f"conn_{i:02d}" for i in range(25)])
