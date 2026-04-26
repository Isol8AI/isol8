"""Unit tests for the credit ledger: balance, top-up, deduct, auto-reload."""

import boto3
import pytest
from moto import mock_aws

from core.services.credit_ledger import (
    InsufficientBalanceError,  # noqa: F401  # imported to verify the symbol is exported
    deduct,
    get_balance,
    set_auto_reload,
    should_auto_reload,
    top_up,
)


@pytest.fixture
def ledger_tables(monkeypatch):
    """Provision moto-mocked credits + credit-transactions tables."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-credits",
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        client.create_table(
            TableName="test-credit-txns",
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "tx_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "tx_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("CREDITS_TABLE", "test-credits")
        monkeypatch.setenv("CREDIT_TRANSACTIONS_TABLE", "test-credit-txns")
        yield


class TestBalance:
    @pytest.mark.asyncio
    async def test_zero_balance_for_new_user(self, ledger_tables):
        assert await get_balance("u_new") == 0

    @pytest.mark.asyncio
    async def test_balance_after_top_up(self, ledger_tables):
        await top_up("u_1", amount_microcents=10_000_000, stripe_payment_intent_id="pi_1")  # $10
        assert await get_balance("u_1") == 10_000_000


class TestTopUp:
    @pytest.mark.asyncio
    async def test_top_up_writes_transaction(self, ledger_tables):
        await top_up("u_1", amount_microcents=5_000_000, stripe_payment_intent_id="pi_2")
        client = boto3.client("dynamodb", region_name="us-east-1")
        items = client.scan(TableName="test-credit-txns")["Items"]
        assert len(items) == 1
        assert items[0]["type"]["S"] == "top_up"
        assert int(items[0]["amount_microcents"]["N"]) == 5_000_000
        assert items[0]["stripe_payment_intent_id"]["S"] == "pi_2"

    @pytest.mark.asyncio
    async def test_two_top_ups_accumulate(self, ledger_tables):
        await top_up("u_1", amount_microcents=3_000_000, stripe_payment_intent_id="pi_a")
        await top_up("u_1", amount_microcents=2_000_000, stripe_payment_intent_id="pi_b")
        assert await get_balance("u_1") == 5_000_000


class TestDeduct:
    @pytest.mark.asyncio
    async def test_deduct_reduces_balance(self, ledger_tables):
        await top_up("u_1", amount_microcents=10_000_000, stripe_payment_intent_id="pi_x")
        await deduct(
            "u_1",
            amount_microcents=2_000_000,
            chat_session_id="sess_1",
            raw_cost_microcents=1_428_571,  # 2M / 1.4 markup
            markup_multiplier=1.4,
        )
        assert await get_balance("u_1") == 8_000_000

    @pytest.mark.asyncio
    async def test_deduct_writes_transaction_with_markup_metadata(self, ledger_tables):
        await top_up("u_1", amount_microcents=10_000_000, stripe_payment_intent_id="pi_x")
        await deduct(
            "u_1",
            amount_microcents=2_000_000,
            chat_session_id="sess_1",
            raw_cost_microcents=1_428_571,
            markup_multiplier=1.4,
        )
        client = boto3.client("dynamodb", region_name="us-east-1")
        items = client.scan(TableName="test-credit-txns")["Items"]
        deduct_row = next(i for i in items if i["type"]["S"] == "deduct")
        assert int(deduct_row["amount_microcents"]["N"]) == -2_000_000
        assert int(deduct_row["raw_cost_microcents"]["N"]) == 1_428_571
        # DDB stores Decimal — moto roundtrips as string.
        assert float(deduct_row["markup_multiplier"]["N"]) == 1.4
        assert deduct_row["chat_session_id"]["S"] == "sess_1"

    @pytest.mark.asyncio
    async def test_deduct_with_insufficient_balance_overdrafts_to_zero(self, ledger_tables):
        """Race scenario: chat completed, deduction would go negative.
        Per spec §6.3 step 6: accept the small overdraft, set balance to 0,
        log a warning. Don't reject — the chat already happened."""
        await top_up("u_1", amount_microcents=1_000_000, stripe_payment_intent_id="pi_x")  # $1
        await deduct(
            "u_1",
            amount_microcents=2_000_000,  # $2 — more than balance
            chat_session_id="sess_overdraft",
            raw_cost_microcents=1_428_571,
            markup_multiplier=1.4,
        )
        assert await get_balance("u_1") == 0


class TestAutoReload:
    @pytest.mark.asyncio
    async def test_auto_reload_default_off(self, ledger_tables):
        # New user — never set auto reload — should not trigger.
        assert await should_auto_reload("u_new") is False

    @pytest.mark.asyncio
    async def test_set_auto_reload_persists(self, ledger_tables):
        await set_auto_reload(
            "u_1",
            enabled=True,
            threshold_cents=500,  # $5
            amount_cents=5000,  # $50
        )
        # Balance is 0 → below threshold → should trigger.
        assert await should_auto_reload("u_1") is True

    @pytest.mark.asyncio
    async def test_above_threshold_does_not_trigger(self, ledger_tables):
        await set_auto_reload(
            "u_1",
            enabled=True,
            threshold_cents=500,  # $5
            amount_cents=5000,
        )
        await top_up("u_1", amount_microcents=10_000_000, stripe_payment_intent_id="pi_x")  # $10
        assert await should_auto_reload("u_1") is False
