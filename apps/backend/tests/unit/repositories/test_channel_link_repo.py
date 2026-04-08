import pytest

import boto3
from moto import mock_aws


@pytest.fixture
def dynamodb_setup(monkeypatch):
    """Create the channel-links table in moto and point the repo at it."""
    monkeypatch.setenv("DYNAMODB_TABLE_PREFIX", "test-")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    with mock_aws():
        # Reset the cached resource/table prefix so the fixture's env vars take effect
        import importlib
        import core.dynamodb

        importlib.reload(core.dynamodb)

        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-channel-links",
            KeySchema=[
                {"AttributeName": "owner_id", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "owner_id", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "member_id", "AttributeType": "S"},
                {"AttributeName": "owner_provider_agent", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by-member",
                    "KeySchema": [
                        {"AttributeName": "member_id", "KeyType": "HASH"},
                        {"AttributeName": "owner_provider_agent", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName="test-channel-links")

        import core.repositories.channel_link_repo  # noqa: F401

        yield


@pytest.mark.asyncio
async def test_put_and_get_by_peer(dynamodb_setup):
    from core.repositories import channel_link_repo

    await channel_link_repo.put(
        owner_id="org_1",
        provider="telegram",
        agent_id="sales",
        peer_id="99999",
        member_id="user_bob",
        linked_via="settings",
    )
    link = await channel_link_repo.get_by_peer(
        owner_id="org_1",
        provider="telegram",
        agent_id="sales",
        peer_id="99999",
    )
    assert link is not None
    assert link["member_id"] == "user_bob"
    assert link["linked_via"] == "settings"
    assert link["provider"] == "telegram"
    assert link["agent_id"] == "sales"
    assert link["peer_id"] == "99999"


@pytest.mark.asyncio
async def test_get_by_peer_miss_returns_none(dynamodb_setup):
    from core.repositories import channel_link_repo

    result = await channel_link_repo.get_by_peer(
        owner_id="org_1",
        provider="telegram",
        agent_id="sales",
        peer_id="00000",
    )
    assert result is None


@pytest.mark.asyncio
async def test_query_by_member_across_orgs(dynamodb_setup):
    from core.repositories import channel_link_repo

    await channel_link_repo.put(
        owner_id="org_1",
        provider="telegram",
        agent_id="main",
        peer_id="111",
        member_id="user_bob",
        linked_via="wizard",
    )
    await channel_link_repo.put(
        owner_id="org_2",
        provider="discord",
        agent_id="main",
        peer_id="222",
        member_id="user_bob",
        linked_via="settings",
    )
    await channel_link_repo.put(
        owner_id="org_1",
        provider="telegram",
        agent_id="main",
        peer_id="333",
        member_id="user_alice",
        linked_via="wizard",
    )

    bob_links = await channel_link_repo.query_by_member("user_bob")
    assert len(bob_links) == 2
    orgs = {link["owner_id"] for link in bob_links}
    assert orgs == {"org_1", "org_2"}


@pytest.mark.asyncio
async def test_delete_link(dynamodb_setup):
    from core.repositories import channel_link_repo

    await channel_link_repo.put(
        owner_id="org_1",
        provider="telegram",
        agent_id="sales",
        peer_id="99999",
        member_id="user_bob",
        linked_via="settings",
    )
    await channel_link_repo.delete(
        owner_id="org_1",
        provider="telegram",
        agent_id="sales",
        peer_id="99999",
    )
    result = await channel_link_repo.get_by_peer(
        owner_id="org_1",
        provider="telegram",
        agent_id="sales",
        peer_id="99999",
    )
    assert result is None
