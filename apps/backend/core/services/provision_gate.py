"""Provision gate evaluation — single source of truth for whether an owner
can provision a container, and *why not* when they can't.

Both `/container/provision` and `/container/status` consult this helper and
return its structured payload on 402, so the two endpoints can never
disagree about the gate state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.repositories import billing_repo, user_repo
from core.services import credit_ledger


_PROVISION_OK_STATUSES = frozenset({"active", "trialing"})


@dataclass(frozen=True)
class Gate:
    """A blocked-state gate result. None means no gate fires (provision allowed)."""

    code: str
    title: str
    message: str
    action_label: str
    action_href: str
    action_admin_only: bool
    owner_role: str  # "admin" | "member"

    def to_payload(self) -> dict[str, Any]:
        """Build the FastAPI HTTPException detail payload.

        ``detail`` is kept as a plain string for backwards-compat with any
        path that still renders FastAPI's default error shape. ``blocked``
        is the structured field new frontends switch on.
        """
        return {
            "detail": self.message,
            "blocked": {
                "code": self.code,
                "title": self.title,
                "message": self.message,
                "action": {
                    "kind": "link",
                    "label": self.action_label,
                    "href": self.action_href,
                    "admin_only": self.action_admin_only,
                },
                "owner_role": self.owner_role,
            },
        }


async def _get_provider_choice(clerk_user_id: str) -> tuple[str, str | None]:
    """Read provider_choice from user_repo (current model — Workstream B
    will move this to billing_repo). Falls back to bedrock_claude when no
    row exists, matching the existing behavior in container.py.
    """
    row = await user_repo.get(clerk_user_id)
    provider_choice = (row or {}).get("provider_choice") or "bedrock_claude"
    byo_provider = (row or {}).get("byo_provider") if provider_choice == "byo_key" else None
    return provider_choice, byo_provider


async def _has_oauth_tokens(clerk_user_id: str) -> bool:
    """Whether the calling Clerk user has ChatGPT OAuth tokens on file.

    OAuth tokens live in the ``oauth-tokens`` DynamoDB table keyed by Clerk
    user_id (see ``core.services.oauth_service``). ChatGPT OAuth is a
    personal-only path (org owners use Bedrock), so the lookup is always
    by the calling user, not the owner_id.

    Lazy import to avoid pulling the OAuth subsystem at module import time.
    """
    from core.services import oauth_service

    tokens = await oauth_service.get_decrypted_tokens(user_id=clerk_user_id)
    return tokens is not None


async def evaluate_provision_gate(
    *,
    owner_id: str,
    owner_type: str,  # "personal" | "org"
    clerk_user_id: str,
    is_admin: bool = True,  # personal owners are always admin of themselves
) -> Gate | None:
    """Return a Gate if provisioning should be blocked, else None.

    Layers (matches existing _assert_provision_allowed logic):
    1. Subscription must be active or trialing (or legacy stripe_subscription_id present).
    2. For bedrock_claude: credit balance must be > 0.
    3. For chatgpt_oauth: OAuth tokens must exist for the calling user.
    """
    owner_role = "admin" if is_admin else "member"

    # Layer 1 — subscription.
    account = await billing_repo.get_by_owner_id(owner_id)
    if not account:
        return Gate(
            code="subscription_required",
            title="Subscribe to start your container",
            message="An active subscription is required to provision a container.",
            action_label="Subscribe",
            action_href="/onboarding",
            action_admin_only=True,
            owner_role=owner_role,
        )
    status = account.get("subscription_status")
    has_legacy_sub = bool(account.get("stripe_subscription_id"))
    is_ok = status in _PROVISION_OK_STATUSES or (status is None and has_legacy_sub)
    if not is_ok:
        if status == "past_due":
            return Gate(
                code="payment_past_due",
                title="Payment past due",
                message="Your latest invoice failed. Update your payment method to continue.",
                action_label="Update payment",
                action_href="/settings/billing",
                action_admin_only=True,
                owner_role=owner_role,
            )
        return Gate(
            code="subscription_required",
            title="Subscription not active",
            message="Reactivate your subscription to start your container.",
            action_label="Manage subscription",
            action_href="/settings/billing",
            action_admin_only=True,
            owner_role=owner_role,
        )

    # Layer 2/3 — provider-specific.
    provider_choice, _ = await _get_provider_choice(clerk_user_id)

    if provider_choice == "bedrock_claude":
        balance = await credit_ledger.get_balance(clerk_user_id)
        if balance <= 0:
            return Gate(
                code="credits_required",
                title="Top up Claude credits to start your container",
                message="Top up some Claude credits to start your Bedrock container.",
                action_label="Top up now",
                action_href="/settings/billing#credits",
                action_admin_only=False,
                owner_role=owner_role,
            )

    if provider_choice == "chatgpt_oauth":
        if not await _has_oauth_tokens(clerk_user_id):
            return Gate(
                code="oauth_required",
                title="Sign in with ChatGPT",
                message="Complete the ChatGPT sign-in to start your container.",
                action_label="Sign in with ChatGPT",
                action_href="/settings/llm",
                action_admin_only=False,
                owner_role=owner_role,
            )

    return None  # all gates pass — provisioning allowed
