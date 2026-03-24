"""Tests for API key DynamoDB repository."""

import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def dynamodb_table():
    """Create a moto DynamoDB api-keys table with composite key."""
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")
        table = client.create_table(
            TableName="test-api-keys",
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "tool_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "tool_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.meta.client.get_waiter("table_exists").wait(TableName="test-api-keys")

        with (
            patch("core.dynamodb._table_prefix", "test-"),
            patch("core.dynamodb._dynamodb_resource", client),
        ):
            yield table


@pytest.mark.asyncio
async def test_set_and_get_key(dynamodb_table):
    from core.repositories import api_key_repo

    result = await api_key_repo.set_key("user_1", "openai", "enc_abc123")
    assert result["user_id"] == "user_1"
    assert result["tool_id"] == "openai"
    assert result["encrypted_key"] == "enc_abc123"

    item = await api_key_repo.get_key("user_1", "openai")
    assert item is not None
    assert item["encrypted_key"] == "enc_abc123"


@pytest.mark.asyncio
async def test_get_key_nonexistent(dynamodb_table):
    from core.repositories import api_key_repo

    item = await api_key_repo.get_key("user_1", "nonexistent")
    assert item is None


@pytest.mark.asyncio
async def test_set_key_overwrites(dynamodb_table):
    from core.repositories import api_key_repo

    await api_key_repo.set_key("user_1", "openai", "enc_old")
    await api_key_repo.set_key("user_1", "openai", "enc_new")

    item = await api_key_repo.get_key("user_1", "openai")
    assert item["encrypted_key"] == "enc_new"


@pytest.mark.asyncio
async def test_list_keys_excludes_encrypted_key(dynamodb_table):
    from core.repositories import api_key_repo

    await api_key_repo.set_key("user_2", "openai", "enc_1")
    await api_key_repo.set_key("user_2", "anthropic", "enc_2")

    keys = await api_key_repo.list_keys("user_2")
    assert len(keys) == 2

    tool_ids = {k["tool_id"] for k in keys}
    assert tool_ids == {"openai", "anthropic"}

    for k in keys:
        assert "encrypted_key" not in k


@pytest.mark.asyncio
async def test_list_keys_empty(dynamodb_table):
    from core.repositories import api_key_repo

    keys = await api_key_repo.list_keys("user_empty")
    assert keys == []


@pytest.mark.asyncio
async def test_delete_key_existing(dynamodb_table):
    from core.repositories import api_key_repo

    await api_key_repo.set_key("user_3", "openai", "enc_del")
    result = await api_key_repo.delete_key("user_3", "openai")
    assert result is True

    item = await api_key_repo.get_key("user_3", "openai")
    assert item is None


@pytest.mark.asyncio
async def test_delete_key_nonexistent(dynamodb_table):
    from core.repositories import api_key_repo

    result = await api_key_repo.delete_key("user_3", "nonexistent")
    assert result is False
