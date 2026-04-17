"""One-shot fleet cleanup for config policy drift.

Runs synchronously. Walks every active container, evaluates its openclaw.json
against the tier policy, and reverts drift on locked fields. Prints a
summary report at the end.

Usage (from apps/backend/):
    uv run python scripts/reconcile_all_configs.py [--dry-run]

Dry-run prints what WOULD be reverted without writing. Use before flipping
CONFIG_RECONCILER_MODE to enforce to confirm the blast radius.
"""

import argparse
import asyncio
import logging

from core.containers.config import read_openclaw_config_from_efs
from core.repositories import billing_repo, container_repo
from core.services import config_policy
from core.services.config_patcher import locked_rmw

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reconcile_all")


async def reconcile_owner(owner_id: str, dry_run: bool) -> tuple[str, list[str]]:
    account = await billing_repo.get_by_owner_id(owner_id)
    tier = account.get("plan_tier", "free") if isinstance(account, dict) else "free"

    config = await read_openclaw_config_from_efs(owner_id)
    if config is None:
        return ("no_config", [])

    violations = config_policy.evaluate(config, tier)
    if not violations:
        return ("clean", [])

    fields = [v["field"] for v in violations]
    if dry_run:
        return ("would_revert", fields)

    def _mutate(current: dict) -> bool:
        vs = config_policy.evaluate(current, tier)
        if not vs:
            return False
        reverted = config_policy.apply_reverts(current, vs)
        current.clear()
        current.update(reverted)
        return True

    await locked_rmw(owner_id, _mutate, "fleet_cleanup")
    return ("reverted", fields)


async def main(dry_run: bool) -> None:
    owners = await container_repo.list_active_owners()
    logger.info("found %d active containers", len(owners))

    counts = {"clean": 0, "no_config": 0, "would_revert": 0, "reverted": 0, "error": 0}
    for owner_id in owners:
        try:
            status, fields = await reconcile_owner(owner_id, dry_run)
            counts[status] = counts.get(status, 0) + 1
            if fields:
                logger.info("%s owner=%s fields=%s", status, owner_id, fields)
        except Exception as e:
            counts["error"] += 1
            logger.exception("error on owner=%s: %s", owner_id, e)

    logger.info("summary: %s", counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be reverted, do not write.",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
