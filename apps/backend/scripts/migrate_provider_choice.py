"""One-shot backfill: copy provider_choice from users -> billing_accounts.

Run via:
    aws ecs run-task \\
        --cluster isol8-prod-service-... \\
        --task-definition isol8-prod-backend-... \\
        --launch-type FARGATE \\
        --overrides '{"containerOverrides":[{"name":"backend","command":["python","scripts/migrate_provider_choice.py"]}]}' \\
        --network-configuration awsvpcConfiguration=...

Idempotent -- re-running is safe. Skips rows that already have
provider_choice set.

Strategy: scan billing_accounts (the destination), and for each row
without provider_choice, look up the owner's user-side choice via the
users table and copy. For org rows we don't know which user originally
set the choice, so we use the first found org admin's user row as the
source. If no admin's user_repo row has provider_choice set, the org
is skipped and logged -- they'll be re-prompted on next provision.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import httpx

from core.config import settings
from core.repositories import billing_repo, user_repo

logger = logging.getLogger(__name__)


_CLERK_API_BASE = "https://api.clerk.com/v1"
_TIMEOUT_S = 10.0


async def _list_org_admin_user_ids(org_id: str) -> list[str]:
    """Return Clerk user_ids of admin members of the given org.

    Uses Clerk Backend API GET /v1/organizations/{org_id}/memberships,
    which returns an envelope {data: [...memberships], total_count: N}.
    Each membership has shape
    {id, role, public_user_data: {user_id, ...}, ...}.

    There is no `list_org_members` helper in core.services.clerk_admin
    (only the inverse list_user_organizations), so this script issues
    the REST call directly. If a centralized helper is added later,
    this function can be replaced with a single call.
    """
    if not settings.CLERK_SECRET_KEY:
        return []

    headers = {"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"}
    params = {"limit": 100}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(
                f"{_CLERK_API_BASE}/organizations/{org_id}/memberships",
                headers=headers,
                params=params,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("clerk org memberships network error for %s: %s", org_id, e)
        return []

    if response.status_code == 404:
        return []
    if response.status_code >= 400:
        logger.warning(
            "clerk org memberships HTTP %s for %s",
            response.status_code,
            org_id,
        )
        return []

    try:
        payload = response.json()
    except ValueError:
        return []

    memberships = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(memberships, list):
        return []

    admin_user_ids: list[str] = []
    for m in memberships:
        if not isinstance(m, dict):
            continue
        role = m.get("role") or ""
        # Clerk roles: "admin" / "basic_member" or "org:admin" / "org:member".
        if "admin" not in str(role):
            continue
        public_user_data = m.get("public_user_data") or {}
        user_id = public_user_data.get("user_id") or m.get("user_id")
        if user_id:
            admin_user_ids.append(user_id)
    return admin_user_ids


async def _find_user_choice(billing_row: dict) -> tuple[str | None, str | None] | None:
    """Locate a source provider_choice for the given billing row.

    Returns (provider_choice, byo_provider) or None if no source found.
    """
    owner_id = billing_row["owner_id"]
    owner_type = billing_row.get("owner_type", "personal")

    if owner_type == "personal":
        # owner_id IS the clerk user_id.
        user = await user_repo.get(owner_id)
        if not user or not user.get("provider_choice"):
            return None
        return user.get("provider_choice"), user.get("byo_provider")

    # Org: find an org admin via Clerk, use their user row's choice.
    try:
        admin_user_ids = await _list_org_admin_user_ids(owner_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not list org members for %s: %s", owner_id, e)
        return None

    for member_user_id in admin_user_ids:
        user = await user_repo.get(member_user_id)
        if user and user.get("provider_choice"):
            return user.get("provider_choice"), user.get("byo_provider")

    return None


async def main() -> int:
    scanned = migrated = skipped_already = skipped_no_source = skipped_org_invariant = 0
    async for billing_row in billing_repo.scan_all():
        scanned += 1
        if billing_row.get("provider_choice"):
            skipped_already += 1
            continue

        result = await _find_user_choice(billing_row)
        if result is None:
            skipped_no_source += 1
            logger.warning(
                "No source user choice found for owner %s (owner_type=%s)",
                billing_row["owner_id"],
                billing_row.get("owner_type", "personal"),
            )
            continue
        provider_choice, byo_provider = result

        # Org invariant: chatgpt_oauth on org -> skip (org will be re-prompted).
        if billing_row.get("owner_type") == "org" and provider_choice == "chatgpt_oauth":
            skipped_org_invariant += 1
            logger.warning(
                "Org %s had chatgpt_oauth from admin -- skipping (orgs must use bedrock_claude or byo_key)",
                billing_row["owner_id"],
            )
            continue

        try:
            await billing_repo.set_provider_choice(
                billing_row["owner_id"],
                provider_choice=provider_choice,
                byo_provider=byo_provider if provider_choice == "byo_key" else None,
                owner_type=billing_row.get("owner_type", "personal"),
            )
        except ValueError as e:
            logger.warning(
                "Skipping %s: %s",
                billing_row["owner_id"],
                e,
            )
            skipped_org_invariant += 1
            continue

        migrated += 1
        logger.info(
            "Migrated owner %s: provider_choice=%s byo_provider=%s",
            billing_row["owner_id"],
            provider_choice,
            byo_provider,
        )

    print(
        f"=== Migration complete ===\n"
        f"scanned={scanned} migrated={migrated} "
        f"skipped_already={skipped_already} "
        f"skipped_no_source={skipped_no_source} "
        f"skipped_org_invariant={skipped_org_invariant}",
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    sys.exit(asyncio.run(main()))
