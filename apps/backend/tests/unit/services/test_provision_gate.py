"""Tests for the provision-gate helper."""

from unittest.mock import AsyncMock, patch

import pytest

from core.services.provision_gate import Gate, evaluate_provision_gate


@pytest.mark.asyncio
async def test_no_billing_account_returns_subscription_required():
    with patch("core.services.provision_gate.billing_repo") as repo:
        repo.get_by_owner_id = AsyncMock(return_value=None)
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is not None
    assert gate.code == "subscription_required"
    assert gate.action_admin_only is True


@pytest.mark.asyncio
async def test_active_subscription_bedrock_zero_balance_returns_credits_required():
    with (
        patch("core.services.provision_gate.billing_repo") as repo,
        patch("core.services.provision_gate._get_provider_choice") as gp,
        patch("core.services.provision_gate.credit_ledger") as cl,
    ):
        repo.get_by_owner_id = AsyncMock(
            return_value={"subscription_status": "active", "stripe_subscription_id": "sub_x"},
        )
        gp.return_value = ("bedrock_claude", None)
        cl.get_balance = AsyncMock(return_value=0)
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is not None
    assert gate.code == "credits_required"


@pytest.mark.asyncio
async def test_trialing_with_credits_returns_none():
    with (
        patch("core.services.provision_gate.billing_repo") as repo,
        patch("core.services.provision_gate._get_provider_choice") as gp,
        patch("core.services.provision_gate.credit_ledger") as cl,
    ):
        repo.get_by_owner_id = AsyncMock(
            return_value={"subscription_status": "trialing", "stripe_subscription_id": "sub_x"},
        )
        gp.return_value = ("bedrock_claude", None)
        cl.get_balance = AsyncMock(return_value=500_000)  # 50 cents in microcents
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is None  # all gates pass


@pytest.mark.asyncio
async def test_past_due_returns_payment_past_due():
    with patch("core.services.provision_gate.billing_repo") as repo:
        repo.get_by_owner_id = AsyncMock(
            return_value={"subscription_status": "past_due", "stripe_subscription_id": "sub_x"},
        )
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is not None
    assert gate.code == "payment_past_due"


@pytest.mark.asyncio
async def test_chatgpt_oauth_no_tokens_returns_oauth_required():
    with (
        patch("core.services.provision_gate.billing_repo") as repo,
        patch("core.services.provision_gate._get_provider_choice") as gp,
        patch("core.services.provision_gate._has_oauth_tokens") as ht,
    ):
        repo.get_by_owner_id = AsyncMock(
            return_value={"subscription_status": "active", "stripe_subscription_id": "sub_x"},
        )
        gp.return_value = ("chatgpt_oauth", None)
        ht.return_value = False
        gate = await evaluate_provision_gate(
            owner_id="user_x",
            owner_type="personal",
            clerk_user_id="user_x",
        )
    assert gate is not None
    assert gate.code == "oauth_required"


def test_gate_to_payload_shape():
    gate = Gate(
        code="credits_required",
        title="Top up Claude credits",
        message="Top up some Claude credits to start your Bedrock container.",
        action_label="Top up now",
        action_href="/settings/billing#credits",
        action_admin_only=False,
        owner_role="admin",
    )
    payload = gate.to_payload()
    assert payload["blocked"]["code"] == "credits_required"
    assert payload["blocked"]["action"]["href"] == "/settings/billing#credits"
    assert payload["blocked"]["action"]["admin_only"] is False
    assert payload["blocked"]["owner_role"] == "admin"
    assert payload["detail"]  # legacy string preserved
