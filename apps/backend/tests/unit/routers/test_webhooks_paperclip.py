"""Tests for the Clerk webhook handlers wired to PaperclipProvisioning (T12).

The webhook handler builds a fresh ``PaperclipProvisioning`` per
request via ``_get_paperclip_provisioning``. We patch that factory to
hand back an ``AsyncMock`` provisioning instance so the test never
touches a real httpx client / DynamoDB repo.

Svix signature verification is bypassed via monkeypatch on the
private ``_verify_svix_signature`` symbol — same pattern used by the
existing ``test_webhooks_clerk_email_sync.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.services.paperclip_admin_client import PaperclipApiError
from core.services.paperclip_provisioning import OrgNotProvisionedError


def _bypass_svix(monkeypatch):
    monkeypatch.setattr(
        "routers.webhooks._verify_svix_signature",
        lambda body, headers: None,
    )


def _svix_headers() -> dict:
    return {
        "svix-id": "msg_test",
        "svix-timestamp": "1234567890",
        "svix-signature": "ignored",
    }


# ----------------------------------------------------------------------
# organization.created -> provision_org
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_organization_created_calls_provision_org(async_client, monkeypatch):
    """``organization.created`` should drive ``PaperclipProvisioning.provision_org``
    with the right kwargs, sourcing owner_email from the users repo."""
    _bypass_svix(monkeypatch)

    mock_provisioning = AsyncMock()
    mock_provisioning.provision_org = AsyncMock(return_value=None)

    payload = {
        "type": "organization.created",
        "data": {
            "id": "org_acme",
            "created_by": "user_owner",
        },
    }

    with (
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new=AsyncMock(return_value=mock_provisioning),
        ),
        patch(
            "core.repositories.user_repo.get",
            new=AsyncMock(return_value={"user_id": "user_owner", "email": "owner@acme.test"}),
        ),
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    mock_provisioning.provision_org.assert_awaited_once_with(
        org_id="org_acme",
        owner_user_id="user_owner",
        owner_email="owner@acme.test",
    )


@pytest.mark.asyncio
async def test_organization_created_retryable_failure_enqueues(async_client, monkeypatch):
    """5xx during provision_org should enqueue a pending-updates retry row
    AND return 200 (we own retries from this point).
    """
    _bypass_svix(monkeypatch)

    err = PaperclipApiError("server-down", 503, "")
    mock_provisioning = AsyncMock()
    mock_provisioning.provision_org = AsyncMock(side_effect=err)

    captured_create = AsyncMock(return_value={"update_id": "upd_1"})

    payload = {
        "type": "organization.created",
        "data": {"id": "org_acme", "created_by": "user_owner"},
    }

    with (
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new=AsyncMock(return_value=mock_provisioning),
        ),
        patch(
            "core.repositories.user_repo.get",
            new=AsyncMock(return_value={"user_id": "user_owner", "email": "owner@acme.test"}),
        ),
        patch("core.repositories.update_repo.create", new=captured_create),
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    mock_provisioning.provision_org.assert_awaited_once()
    captured_create.assert_awaited_once()
    kwargs = captured_create.call_args.kwargs
    assert kwargs["owner_id"] == "user_owner"
    assert kwargs["update_type"] == "paperclip_provision"
    assert kwargs["changes"]["op"] == "provision_org"
    assert kwargs["changes"]["org_id"] == "org_acme"
    assert kwargs["changes"]["owner_user_id"] == "user_owner"
    assert kwargs["changes"]["owner_email"] == "owner@acme.test"


@pytest.mark.asyncio
async def test_organization_created_non_retryable_does_not_enqueue(async_client, monkeypatch):
    """4xx (non-429) should NOT enqueue a retry — that error won't fix itself.

    We still return 200 to Clerk because the webhook delivery itself
    is fine; the failure is in our downstream call, and Clerk retries
    would just hit the same 4xx.
    """
    _bypass_svix(monkeypatch)

    err = PaperclipApiError("dup-email", 409, "")
    mock_provisioning = AsyncMock()
    mock_provisioning.provision_org = AsyncMock(side_effect=err)
    captured_create = AsyncMock()

    payload = {
        "type": "organization.created",
        "data": {"id": "org_acme", "created_by": "user_owner"},
    }

    with (
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new=AsyncMock(return_value=mock_provisioning),
        ),
        patch(
            "core.repositories.user_repo.get",
            new=AsyncMock(return_value={"user_id": "user_owner", "email": "owner@acme.test"}),
        ),
        patch("core.repositories.update_repo.create", new=captured_create),
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    captured_create.assert_not_awaited()


# ----------------------------------------------------------------------
# organizationMembership.created -> provision_member
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_membership_created_calls_provision_member(async_client, monkeypatch):
    """``organizationMembership.created`` payloads carry the new member's
    user_id + email under ``public_user_data``, and the owner's user_id
    under ``organization.created_by``. Owner email is sourced from
    the users repo since Clerk doesn't put it on this payload.
    """
    _bypass_svix(monkeypatch)

    mock_provisioning = AsyncMock()
    mock_provisioning.provision_member = AsyncMock(return_value=None)

    payload = {
        "type": "organizationMembership.created",
        "data": {
            "id": "orgm_1",
            "organization": {
                "id": "org_acme",
                "created_by": "user_owner",
            },
            "public_user_data": {
                "user_id": "user_member",
                "identifier": "member@acme.test",
            },
            "role": "org:member",
        },
    }

    with (
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new=AsyncMock(return_value=mock_provisioning),
        ),
        patch(
            "core.repositories.user_repo.get",
            new=AsyncMock(return_value={"user_id": "user_owner", "email": "owner@acme.test"}),
        ),
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    mock_provisioning.provision_member.assert_awaited_once_with(
        org_id="org_acme",
        user_id="user_member",
        email="member@acme.test",
        owner_email="owner@acme.test",
    )


@pytest.mark.asyncio
async def test_membership_created_org_not_provisioned_enqueues(async_client, monkeypatch):
    """``OrgNotProvisionedError`` is always retryable — the org-create
    webhook is in flight, we just need to retry shortly. Should enqueue
    and return 200.
    """
    _bypass_svix(monkeypatch)

    err = OrgNotProvisionedError("org missing")
    mock_provisioning = AsyncMock()
    mock_provisioning.provision_member = AsyncMock(side_effect=err)
    captured_create = AsyncMock(return_value={"update_id": "upd_1"})

    payload = {
        "type": "organizationMembership.created",
        "data": {
            "id": "orgm_1",
            "organization": {"id": "org_acme", "created_by": "user_owner"},
            "public_user_data": {
                "user_id": "user_member",
                "identifier": "member@acme.test",
            },
        },
    }

    with (
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new=AsyncMock(return_value=mock_provisioning),
        ),
        patch(
            "core.repositories.user_repo.get",
            new=AsyncMock(return_value={"user_id": "user_owner", "email": "owner@acme.test"}),
        ),
        patch("core.repositories.update_repo.create", new=captured_create),
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    captured_create.assert_awaited_once()
    kwargs = captured_create.call_args.kwargs
    assert kwargs["owner_id"] == "user_member"
    assert kwargs["changes"]["op"] == "provision_member"
    assert kwargs["changes"]["user_id"] == "user_member"
    assert kwargs["changes"]["email"] == "member@acme.test"


# ----------------------------------------------------------------------
# organizationMembership.deleted -> disable
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_membership_deleted_calls_disable(async_client, monkeypatch):
    _bypass_svix(monkeypatch)

    mock_provisioning = AsyncMock()
    mock_provisioning.disable = AsyncMock(return_value=None)

    payload = {
        "type": "organizationMembership.deleted",
        "data": {
            "id": "orgm_1",
            "organization": {"id": "org_acme"},
            "public_user_data": {"user_id": "user_member"},
        },
    }

    with patch(
        "routers.webhooks._get_paperclip_provisioning",
        new=AsyncMock(return_value=mock_provisioning),
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    mock_provisioning.disable.assert_awaited_once_with(user_id="user_member")


# ----------------------------------------------------------------------
# user.deleted -> disable
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_deleted_calls_disable(async_client, monkeypatch):
    """``user.deleted`` continues to sweep channel_links AND now
    additionally calls ``PaperclipProvisioning.disable``.
    """
    _bypass_svix(monkeypatch)

    mock_provisioning = AsyncMock()
    mock_provisioning.disable = AsyncMock(return_value=None)

    payload = {"type": "user.deleted", "data": {"id": "user_x", "deleted": True}}

    with (
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new=AsyncMock(return_value=mock_provisioning),
        ),
        patch(
            "core.repositories.channel_link_repo.sweep_by_member",
            new=AsyncMock(return_value=0),
        ),
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    mock_provisioning.disable.assert_awaited_once_with(user_id="user_x")


# ----------------------------------------------------------------------
# Stripe customer.subscription.deleted -> disable
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# user.created -> persists email into users repo
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_created_persists_email(async_client, monkeypatch):
    """``user.created`` should extract the primary email from the Clerk
    payload and persist it via ``user_repo.put`` so subsequent
    organization.created webhooks can resolve the owner's email
    without round-tripping Clerk admin.
    """
    _bypass_svix(monkeypatch)

    captured_put = AsyncMock(return_value={"user_id": "user_new", "email": "new@example.test"})

    payload = {
        "type": "user.created",
        "data": {
            "id": "user_new",
            "email_addresses": [
                {"id": "ea_1", "email_address": "alt@example.test"},
                {"id": "ea_2", "email_address": "new@example.test"},
            ],
            "primary_email_address_id": "ea_2",
        },
    }

    with patch("core.repositories.user_repo.put", new=captured_put):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    captured_put.assert_awaited_once()
    args, kwargs = captured_put.call_args
    # ``put`` accepts a positional user_id + keyword email.
    assert args[0] == "user_new"
    assert kwargs.get("email") == "new@example.test"


@pytest.mark.asyncio
async def test_user_created_persist_failure_is_non_fatal(async_client, monkeypatch):
    """A DDB hiccup on user_repo.put must NOT bubble out as a 5xx —
    Clerk would retry the same event and we'd never make progress."""
    _bypass_svix(monkeypatch)

    failing_put = AsyncMock(side_effect=RuntimeError("ddb-down"))

    payload = {
        "type": "user.created",
        "data": {
            "id": "user_new",
            "email_addresses": [{"id": "ea_1", "email_address": "x@y.test"}],
            "primary_email_address_id": "ea_1",
        },
    }

    with patch("core.repositories.user_repo.put", new=failing_put):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    failing_put.assert_awaited_once()


# ----------------------------------------------------------------------
# Clerk webhook svix dedupe (I1)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clerk_webhook_dedupes_by_svix_id(async_client, monkeypatch):
    """Two retries from svix on the same Clerk event must NOT both
    drive ``provision_org`` — the second 409s with email-collision and
    marks the row failed forever. Verify the second delivery returns
    early without invoking the provisioning factory.
    """
    _bypass_svix(monkeypatch)

    # First call: dedupe says "RECORDED", real handler runs.
    # Second call: dedupe says "ALREADY_SEEN", handler must skip.
    from core.services.webhook_dedup import WebhookDedupResult

    dedupe_results = [WebhookDedupResult.RECORDED, WebhookDedupResult.ALREADY_SEEN]

    async def _fake_dedupe(event_id, *, source):
        assert source == "clerk"
        return dedupe_results.pop(0)

    monkeypatch.setattr(
        "core.services.webhook_dedup.record_event_or_skip",
        _fake_dedupe,
    )

    mock_provisioning = AsyncMock()
    mock_provisioning.provision_org = AsyncMock(return_value=None)
    factory = AsyncMock(return_value=mock_provisioning)

    payload = {
        "type": "organization.created",
        "data": {"id": "org_acme", "created_by": "user_owner"},
    }

    with (
        patch("routers.webhooks._get_paperclip_provisioning", new=factory),
        patch(
            "core.repositories.user_repo.get",
            new=AsyncMock(return_value={"user_id": "user_owner", "email": "owner@acme.test"}),
        ),
    ):
        resp1 = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )
        resp2 = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # Provisioning ran exactly once across both retries.
    mock_provisioning.provision_org.assert_awaited_once()


# ----------------------------------------------------------------------
# _lookup_owner_email Clerk-admin fallback (C2)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_email_falls_back_to_clerk_admin(async_client, monkeypatch):
    """If the users row has no email column (e.g. provisioned before
    the email column was added), ``_lookup_owner_email`` should pull
    from Clerk's admin API rather than enqueueing a permanent retry.
    """
    _bypass_svix(monkeypatch)

    # Users repo returns a row with NO email — simulates a pre-fix row.
    user_get = AsyncMock(return_value={"user_id": "user_owner"})

    # Clerk admin returns a payload with the primary email populated.
    clerk_get = AsyncMock(
        return_value={
            "id": "user_owner",
            "email_addresses": [
                {"id": "ea_1", "email_address": "owner@acme.test"},
            ],
            "primary_email_address_id": "ea_1",
        }
    )

    mock_provisioning = AsyncMock()
    mock_provisioning.provision_org = AsyncMock(return_value=None)

    payload = {
        "type": "organization.created",
        "data": {"id": "org_acme", "created_by": "user_owner"},
    }

    with (
        patch("core.repositories.user_repo.get", new=user_get),
        patch("core.services.clerk_admin.get_user", new=clerk_get),
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new=AsyncMock(return_value=mock_provisioning),
        ),
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers=_svix_headers(),
        )

    assert resp.status_code == 200
    clerk_get.assert_awaited_once_with("user_owner")
    mock_provisioning.provision_org.assert_awaited_once_with(
        org_id="org_acme",
        owner_user_id="user_owner",
        owner_email="owner@acme.test",
    )


@pytest.mark.asyncio
async def test_stripe_subscription_deleted_calls_disable(async_client, monkeypatch):
    """``customer.subscription.deleted`` should call
    ``PaperclipProvisioning.disable`` for the affected owner with the
    standard 30-day grace.
    """
    # Bypass Stripe signature verification: the Stripe webhook constructs
    # the event from the raw body via ``stripe.Webhook.construct_event``,
    # which signs with STRIPE_WEBHOOK_SECRET. Patching to the canonical
    # event dict is simpler than synthesizing a real signature.
    fake_event = {
        "id": "evt_test",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_existing",
                "status": "canceled",
            }
        },
    }

    monkeypatch.setattr(
        "stripe.Webhook.construct_event",
        lambda body, sig, secret: fake_event,
    )

    mock_provisioning = AsyncMock()
    mock_provisioning.disable = AsyncMock(return_value=None)

    fake_account = {
        "owner_id": "user_owner",
        "stripe_customer_id": "cus_existing",
    }

    with (
        patch(
            "core.repositories.billing_repo.get_by_stripe_customer_id",
            new=AsyncMock(return_value=fake_account),
        ),
        patch(
            "core.services.webhook_dedup.record_event_or_skip",
            new=AsyncMock(
                return_value=__import__(
                    "core.services.webhook_dedup", fromlist=["WebhookDedupResult"]
                ).WebhookDedupResult.RECORDED
            ),
        ),
        patch(
            "core.services.billing_service.BillingService.cancel_subscription",
            new=AsyncMock(return_value=None),
        ),
        patch("core.containers.get_ecs_manager") as mock_ecs,
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new=AsyncMock(return_value=mock_provisioning),
        ),
    ):
        mock_ecs.return_value.delete_user_service = AsyncMock(return_value=None)
        resp = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "ignored"},
        )

    assert resp.status_code == 200
    mock_provisioning.disable.assert_awaited_once_with(user_id="user_owner")
