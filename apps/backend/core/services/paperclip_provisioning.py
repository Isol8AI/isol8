"""Orchestrator for provisioning Paperclip on Clerk webhook events.

Three entry points (all async, all idempotent on user_id / org_id):

* ``provision_org`` — for ``organization.created``. Creates the Paperclip
  company AND the org owner's Better Auth account in a single
  end-to-end chain (sign_up_user -> create_company -> mint service token
  -> seed Main Agent -> persist row). This is the only path that calls
  ``create_company``.

* ``provision_member`` — for ``organizationMembership.created``. Adds a
  new Isol8 member to the org's existing Paperclip company via the
  full Better Auth + invite-flow chain:

      member_signUp ->
      owner_signIn (using stored owner password) ->
      owner.create_invite ->
      member.accept_invite ->
      owner.approve_join_request ->
      mint member service-token ->
      persist member row.

  Requires the caller (T12 webhook handler) to pass ``owner_email`` —
  Clerk's ``organizationMembership.created`` payload includes the org
  owner's email anyway, so we keep the orchestrator self-contained
  rather than depending on user_repo.

* ``disable`` — for cancellation/deletion. Marks the row
  ``status="disabled"`` with ``scheduled_purge_at = now + grace_days``;
  the company itself is left alive (other org members still have
  access). The ``purge`` cron entrypoint hard-deletes after the grace
  window.

Failure semantics: any failure mid-provisioning calls
``_mark_failed`` to leave a row with ``status="failed"`` and
``last_error`` set so the caller (or a retry path) can observe it,
then re-raises. Subsequent retries with the same args are safe — the
``status="active"`` short-circuit is the only path that skips work.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.encryption import decrypt, encrypt
from core.repositories.paperclip_repo import PaperclipCompany, PaperclipRepo
from core.services import service_token
from core.services.paperclip_admin_client import PaperclipAdminClient, PaperclipApiError

logger = logging.getLogger(__name__)


def _ws_gateway_url(env_name: str) -> str:
    """Pick the right WS gateway URL for the seeded Main Agent's
    openclaw-gateway adapter.

    Mirrors the env-name convention used by ``CLAUDE.md`` and the
    frontend's ``NEXT_PUBLIC_API_URL`` (``api-{env}.isol8.co``).
    Production drops the ``-prod`` suffix.
    """
    if env_name in ("prod", "production"):
        return "wss://ws.isol8.co"
    if env_name:
        return f"wss://ws-{env_name}.isol8.co"
    # Empty env (local dev) — fall back to local WS endpoint.
    return "ws://localhost:8000"


class OrgNotProvisionedError(RuntimeError):
    """Raised when ``provision_member`` is called but the org has no
    Paperclip company yet.

    We deliberately do NOT auto-fall-through to ``provision_org`` here
    because that would race with whichever webhook handler is also
    trying to provision the org. The caller (webhook router) is
    expected to dispatch ``organization.created`` before any
    ``organizationMembership.created`` event for the same org; if the
    order arrives reversed, the caller should retry.

    The ``retryable`` class attribute is a stable signal for T12's
    webhook handler: it can dispatch a retry without string-matching
    on the exception's type or message. This is always retryable —
    the org-create webhook is in flight and will land momentarily.
    """

    retryable: bool = True


class PaperclipProvisioning:
    """End-to-end provisioning chain for Paperclip companies + members.

    Consumes:

      * ``admin_client``: the typed httpx client wrapping Paperclip's
        REST API. Caller is responsible for its lifecycle (it shares
        the connection pool with the proxy router).
      * ``repo``: the async DynamoDB repo for paperclip-companies.
      * ``env_name``: the deploy-environment name used to compute the
        seeded Main Agent's gateway URL (``dev``/``staging``/``prod``).
    """

    def __init__(
        self,
        admin_client: PaperclipAdminClient,
        repo: PaperclipRepo,
        env_name: str,
    ):
        self._admin = admin_client
        self._repo = repo
        self._env_name = env_name

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def provision_org(
        self,
        *,
        org_id: str,
        owner_user_id: str,
        owner_email: str,
    ) -> PaperclipCompany:
        """Provision the Paperclip company + Better Auth owner for a new org.

        Idempotent: if a row already exists for ``owner_user_id`` with
        ``status="active"``, return it unchanged. If it exists with any
        other status (``provisioning`` / ``failed``), we redo the chain
        from scratch — Paperclip's sign-up is not idempotent, so a
        second call against the same email will fail at the Better Auth
        layer; T12 webhook dedupe is the primary retry-suppression
        mechanism.
        """
        existing = await self._repo.get(owner_user_id)
        if existing is not None and existing.status == "active":
            logger.info(
                "paperclip_provisioning.provision_org: owner %s already active for org %s",
                owner_user_id,
                org_id,
            )
            return existing

        password = secrets.token_urlsafe(32)
        try:
            # 1. Better Auth sign-up — creates the per-user Paperclip account
            #    and returns a fresh session token usable as the bearer for
            #    subsequent calls that should "act as" this user.
            signup = await self._admin.sign_up_user(
                email=owner_email,
                password=password,
                name=owner_email,
            )
            paperclip_user_id = signup["user"]["id"]
            session_token = signup["token"]

            # 2. Create the company AS the owner. The bearer token's user
            #    is automatically granted owner-membership server-side.
            company = await self._admin.create_company(
                name=owner_email,
                description="Isol8 Teams workspace",
                session_token=session_token,
                idempotency_key=owner_user_id,
            )
            company_id = company["id"]

            # 3. Mint a long-lived OpenClaw service-token JWT. Baked into
            #    the seeded agent's adapter config so the agent can reach
            #    the user's container via the existing gateway.
            svc_token = service_token.mint(owner_user_id)

            # 4. Best-effort seed of a "Main Agent" pointing at the
            #    user's OpenClaw container. Failure here is not fatal —
            #    the company is still usable, the user can create agents
            #    from the UI manually.
            try:
                await self._admin.create_agent(
                    company_id=company_id,
                    name="Main Agent",
                    role="ceo",
                    adapter_type="openclaw-gateway",
                    adapter_config={
                        "url": _ws_gateway_url(self._env_name),
                        "authToken": svc_token,
                        "sessionKeyStrategy": "fixed",
                        "sessionKey": owner_user_id,
                    },
                    session_token=session_token,
                    idempotency_key=f"{owner_user_id}:main-agent",
                )
            except PaperclipApiError as e:
                logger.warning(
                    "paperclip_provisioning.provision_org: seed agent failed for %s: %s",
                    owner_user_id,
                    e,
                )

            # 5. Persist
            now = datetime.now(timezone.utc)
            row = PaperclipCompany(
                user_id=owner_user_id,
                org_id=org_id,
                company_id=company_id,
                paperclip_user_id=paperclip_user_id,
                paperclip_password_encrypted=encrypt(password),
                service_token_encrypted=encrypt(svc_token),
                status="active",
                created_at=now,
                updated_at=now,
            )
            await self._repo.put(row)
            logger.info(
                "paperclip_provisioning.provision_org: org %s active (company=%s, owner=%s)",
                org_id,
                company_id,
                owner_user_id,
            )
            return row

        except Exception as e:
            await self._mark_failed(
                user_id=owner_user_id,
                org_id=org_id,
                reason=f"provision_org failed: {e}",
            )
            # ``retryable`` is now set automatically:
            #   - PaperclipApiError sets it in __init__ (5xx/429 → True).
            #   - OrgNotProvisionedError carries the class attribute.
            #   - Other exceptions are treated as non-retryable by the
            #     T12 caller (``getattr(exc, "retryable", False)``).
            raise

    async def provision_member(
        self,
        *,
        org_id: str,
        user_id: str,
        email: str,
        owner_email: str,
    ) -> PaperclipCompany:
        """Add a new Isol8 member to the org's existing Paperclip company.

        ``owner_email`` is supplied by the webhook caller (Clerk's
        ``organizationMembership.created`` payload exposes it). We
        could look it up via ``user_repo`` instead, but keeping it as
        a kwarg avoids the cross-service coupling and makes the
        orchestrator easier to test in isolation.

        Idempotent on ``user_id``: an already-active row short-circuits
        to a no-op return.
        """
        existing = await self._repo.get(user_id)
        if existing is not None and existing.status == "active":
            logger.info(
                "paperclip_provisioning.provision_member: member %s already active",
                user_id,
            )
            return existing

        company_id = await self._repo.get_org_company_id(org_id)
        if not company_id:
            raise OrgNotProvisionedError(
                f"Org {org_id} has no Paperclip company yet. "
                "organization.created webhook may not have run yet — caller should retry."
            )

        owner_row = await self._find_org_owner(org_id)
        if owner_row is None:
            # Defensive — get_org_company_id returned a company_id but
            # _find_org_owner couldn't locate the row that produced it.
            # Should be impossible if the GSI is consistent.
            raise OrgNotProvisionedError(f"Org {org_id} has company {company_id} but no owner row found")
        owner_password = decrypt(owner_row.paperclip_password_encrypted)

        member_password = secrets.token_urlsafe(32)
        try:
            # 1. Sign up the new member (creates their Better Auth account).
            member_signup = await self._admin.sign_up_user(
                email=email,
                password=member_password,
                name=email,
            )
            member_paperclip_user_id = member_signup["user"]["id"]
            member_session_token = member_signup["token"]

            # 2. Sign in as the org owner so we can act on the company
            #    (create invite + approve join request).
            owner_signin = await self._admin.sign_in_user(
                email=owner_email,
                password=owner_password,
            )
            owner_session_token = owner_signin["token"]

            # 3. Owner mints a one-shot invite token for this member.
            invite = await self._admin.create_invite(
                session_token=owner_session_token,
                company_id=company_id,
                email=email,
            )
            invite_token = invite["token"]

            # 4. Member accepts the invite, producing a pending join
            #    request bound to the member's Better Auth user.
            accept = await self._admin.accept_invite(
                session_token=member_session_token,
                invite_token=invite_token,
            )
            # Paperclip's accept_invite response shape verified against
            # ``server/src/routes/access.ts:3604-3630``:
            # ``toJoinRequestResponse(created)`` spreads the joinRequests
            # row into a flat object with a top-level ``id`` field. No
            # wrapping, no alternate casing — strict access here so any
            # future shape change fails loud instead of silently dropping
            # the approve_join_request step.
            try:
                request_id = accept["id"]
            except (KeyError, TypeError) as e:
                raise PaperclipApiError(
                    "accept_invite response missing 'id' field",
                    status_code=200,
                    body=accept,
                ) from e

            # 5. Owner approves the pending join request — flips the
            #    membership from pending_approval to active.
            await self._admin.approve_join_request(
                session_token=owner_session_token,
                company_id=company_id,
                request_id=request_id,
            )

            # 6. Mint the member's own OpenClaw service-token JWT.
            svc_token = service_token.mint(user_id)

            # 7. Persist the member row.
            now = datetime.now(timezone.utc)
            row = PaperclipCompany(
                user_id=user_id,
                org_id=org_id,
                company_id=company_id,
                paperclip_user_id=member_paperclip_user_id,
                paperclip_password_encrypted=encrypt(member_password),
                service_token_encrypted=encrypt(svc_token),
                status="active",
                created_at=now,
                updated_at=now,
            )
            await self._repo.put(row)
            logger.info(
                "paperclip_provisioning.provision_member: member %s added to org %s (company=%s)",
                user_id,
                org_id,
                company_id,
            )
            return row

        except Exception as e:  # noqa: F841 — kept for clarity in future logging
            await self._mark_failed(
                user_id=user_id,
                org_id=org_id,
                reason=f"provision_member failed: {e}",
                company_id=company_id,
            )
            # ``retryable`` is set on the exception itself (see provision_org
            # for the full rationale).
            raise

    async def disable(self, *, user_id: str, grace_days: int = 30) -> None:
        """Mark a user's Paperclip row disabled with a purge timer.

        Idempotent: returns early if no row exists. We deliberately do
        NOT call ``disable_company`` here even when this is the only
        member — that's a destructive action the cancellation flow may
        want to delay until after the grace window closes (mirrors the
        existing "30-day account recovery" UX). ``purge`` is where
        Paperclip-side cleanup happens.
        """
        existing = await self._repo.get(user_id)
        if existing is None:
            return
        purge_at = datetime.now(timezone.utc) + timedelta(days=grace_days)
        await self._repo.update_status(
            user_id,
            status="disabled",
            scheduled_purge_at=purge_at,
        )
        logger.info(
            "paperclip_provisioning.disable: user %s scheduled for purge at %s",
            user_id,
            purge_at.isoformat(),
        )

    async def purge(self, *, user_id: str) -> None:
        """Hard-delete a row whose grace window has elapsed.

        Designed to be called from the cleanup cron (T13) for each row
        returned by ``repo.scan_purge_due``. v1 simplification: we
        always delete the local row but only call
        ``admin_client.disable_company`` when this is the last
        remaining member of the org. Paperclip has no per-user
        member-removal REST endpoint, so non-final members just lose
        their local mapping; the Paperclip Better Auth account
        lingers (intentionally — it's still a valid identity for any
        other org we may add them to later, and v1 doesn't support
        cross-org users anyway).

        Order matters: we delete THIS user's row FIRST, then count
        the org's remaining members via the ``by-org-id`` GSI. A
        post-delete count of 0 unambiguously means "the user we just
        purged was the last one"; this is correct regardless of
        whether the purged user was the org owner or a regular
        member. (The previous implementation incorrectly archived
        the company any time the owner row was purged, even with
        other members still present.)

        GSI consistency caveat: ``count_org_members`` reads from the
        ``by-org-id`` GSI which is eventually consistent with the row
        we just deleted. In edge cases the count may be stale (off by
        one) — for example, the GSI may briefly still see the just-
        deleted row, causing us to skip ``disable_company`` when this
        was actually the last member. Acceptable for v1: the next
        purge run picks up any stranded company (the hard-delete of
        the local row already happened, so the user's local mapping
        is gone; the company itself living another day in Paperclip
        is harmless until the cron sees it again).
        """
        existing = await self._repo.get(user_id)
        if existing is None:
            return

        # Delete first so the count reflects the post-purge state.
        await self._repo.delete(user_id)

        remaining_members = await self._repo.count_org_members(existing.org_id)
        is_last_member = remaining_members == 0
        if is_last_member:
            try:
                await self._admin.disable_company(company_id=existing.company_id)
            except PaperclipApiError as e:
                # Archive failure is logged but not fatal — we already
                # removed the local row so the cron doesn't loop on it.
                logger.warning(
                    "paperclip_provisioning.purge: disable_company failed for %s: %s",
                    existing.company_id,
                    e,
                )
        logger.info(
            "paperclip_provisioning.purge: user %s purged (org_remaining=%d, last_member=%s)",
            user_id,
            remaining_members,
            is_last_member,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _find_org_owner(self, org_id: str) -> Optional[PaperclipCompany]:
        """Find the org-owner row (oldest ``created_at`` for this org).

        v1 implementation: query the ``by-org-id`` GSI for all rows in
        the org, then pick the one with the smallest ``created_at``.
        For typical org sizes (1-10 users) this is fine; if Teams ever
        supports large orgs we'd want to either:

          * sort the GSI by ``created_at`` (range key on the GSI), or
          * track the owner's user_id explicitly on every row.

        Both are deferred — the GSI was declared with KEYS_ONLY-style
        projection minimums and the table is small.
        """
        # Re-query the GSI without a Limit so we can pick the oldest
        # row. This is intentionally a separate code path from
        # ``get_org_company_id`` (which only needs one row).
        from boto3.dynamodb.conditions import Key  # local import to keep module load light

        items: list[dict] = []
        last_evaluated_key: Optional[dict] = None
        # We access the repo's internal table to avoid duplicating the
        # boto3 setup. This is a deliberate provisioning-side helper —
        # if we ever need this for non-provisioning code we'll move it
        # into paperclip_repo.
        table = self._repo._table()  # noqa: SLF001 — same package, justified above
        while True:
            kwargs: dict = {
                "IndexName": "by-org-id",
                "KeyConditionExpression": Key("org_id").eq(org_id),
            }
            if last_evaluated_key is not None:
                kwargs["ExclusiveStartKey"] = last_evaluated_key
            from core.dynamodb import run_in_thread

            resp = await run_in_thread(table.query, **kwargs)
            items.extend(resp.get("Items", []))
            last_evaluated_key = resp.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break

        if not items:
            return None

        # Pick the oldest by created_at; if any item is missing the
        # field we fall back to the first row (defensive — shouldn't
        # happen since put() always writes it).
        def _sort_key(it: dict) -> str:
            return it.get("created_at", "")

        oldest = min(items, key=_sort_key)
        return await self._repo.get(oldest["user_id"])

    async def _mark_failed(
        self,
        *,
        user_id: str,
        org_id: str,
        reason: str,
        company_id: str = "",
    ) -> None:
        """Persist ``status="failed"`` + ``last_error``.

        If a prior row exists we update in place (preserving
        immutables like paperclip_user_id); otherwise we write a fresh
        placeholder row so subsequent admin tooling can see the
        failure. Truncates the reason to a sane length to keep the
        DynamoDB item small.
        """
        truncated = reason[:1000]
        existing = await self._repo.get(user_id)
        if existing is not None:
            await self._repo.update_status(
                user_id,
                status="failed",
                last_error=truncated,
            )
            return

        now = datetime.now(timezone.utc)
        await self._repo.put(
            PaperclipCompany(
                user_id=user_id,
                org_id=org_id,
                company_id=company_id,
                paperclip_user_id="",
                paperclip_password_encrypted="",
                service_token_encrypted="",
                status="failed",
                created_at=now,
                updated_at=now,
                last_error=truncated,
            )
        )
