"""Update service -- orchestrates tier changes, image updates, and scheduled worker."""

import asyncio
import logging

from core.config import TIER_CONFIG
from core.repositories import update_repo
from core.services.config_patcher import patch_openclaw_config

logger = logging.getLogger(__name__)


def _build_tier_config_patch(tier_config: dict) -> dict:
    """Build the openclaw.json patch dict for a given tier config."""
    return {
        "agents": {
            "defaults": {
                "model": {"primary": tier_config["primary_model"]},
                "models": tier_config.get("model_aliases", {}),
                "subagent": {"model": tier_config["subagent_model"]},
            }
        }
    }


async def queue_tier_change(owner_id: str, old_tier: str, new_tier: str) -> dict | None:
    """Handle a tier change for an owner.

    Track 1 (always): Patch openclaw.json with new model config.
    Track 2 (if size differs): Create a pending container_resize update.

    Returns the pending update item if a resize was queued, else None.
    """
    new_config = TIER_CONFIG.get(new_tier)
    if not new_config:
        raise ValueError(f"Unknown tier: {new_tier}")

    old_config = TIER_CONFIG.get(old_tier)
    if not old_config:
        raise ValueError(f"Unknown tier: {old_tier}")

    # Track 1: always patch config
    patch = _build_tier_config_patch(new_config)
    await patch_openclaw_config(owner_id, patch)
    logger.info("Patched openclaw.json for tier change %s -> %s (owner=%s)", old_tier, new_tier, owner_id)

    # Track 2: queue resize if container size changed
    pending_update = None
    old_cpu, old_mem = old_config["container_cpu"], old_config["container_memory"]
    new_cpu, new_mem = new_config["container_cpu"], new_config["container_memory"]

    if old_cpu != new_cpu or old_mem != new_mem:
        pending_update = await update_repo.create(
            owner_id=owner_id,
            update_type="container_resize",
            description=f"Resize container for tier change {old_tier} -> {new_tier}",
            changes={
                "new_cpu": new_cpu,
                "new_memory": new_mem,
            },
        )
        logger.info(
            "Queued container resize %s -> %s cpu=%s mem=%s (owner=%s)",
            old_tier,
            new_tier,
            new_cpu,
            new_mem,
            owner_id,
        )

    return pending_update


async def queue_image_update(owner_id: str, new_image: str, description: str | None = None) -> dict:
    """Queue a container image update for a single owner."""
    desc = description or f"Image update to {new_image}"
    item = await update_repo.create(
        owner_id=owner_id,
        update_type="image_update",
        description=desc,
        changes={"new_image": new_image},
    )
    logger.info("Queued image update for owner=%s image=%s", owner_id, new_image)
    return item


async def queue_fleet_image_update(new_image: str, description: str | None = None) -> int:
    """Queue an image update for every owner in the billing-accounts table.

    Scans the billing-accounts DynamoDB table and creates one pending update per owner.
    Returns the count of updates created.
    """
    from core.dynamodb import get_table, run_in_thread

    table = get_table("billing-accounts")
    count = 0
    last_key = None

    while True:
        scan_kwargs: dict = {}
        if last_key:
            scan_kwargs["ExclusiveStartKey"] = last_key

        response = await run_in_thread(table.scan, **scan_kwargs)
        items = response.get("Items", [])

        for item in items:
            owner_id = item.get("owner_id")
            if not owner_id:
                continue
            await queue_image_update(owner_id, new_image, description)
            count += 1

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break

    logger.info("Queued fleet image update for %d owners, image=%s", count, new_image)
    return count


async def apply_update(owner_id: str, update_id: str) -> bool:
    """Apply a single pending update.

    1. Conditionally set status to 'applying' (prevents double-apply).
    2. Apply config patch if present.
    3. Apply ECS changes if present (TODO: ecs_manager.update_user_container).
    4. Mark as applied on success, failed on error.

    Returns True if applied, False if already being applied or failed precondition.
    """
    # Step 1: conditional write
    acquired = await update_repo.set_status_conditional(owner_id, update_id, "applying", ["pending", "scheduled"])
    if not acquired:
        logger.warning("Could not acquire update %s for owner %s (already applying?)", update_id, owner_id)
        return False

    try:
        # Re-fetch the update to get its details
        from core.dynamodb import get_table, run_in_thread
        from boto3.dynamodb.conditions import Key

        table = get_table("pending-updates")
        response = await run_in_thread(
            table.query,
            KeyConditionExpression=Key("owner_id").eq(owner_id) & Key("update_id").eq(update_id),
        )
        items = response.get("Items", [])
        if not items:
            logger.error("Update %s not found after acquiring lock (owner=%s)", update_id, owner_id)
            return False

        update = items[0]
        changes = update.get("changes", {})
        update_type = update.get("update_type", "")

        # Step 2: apply config patch if present
        config_patch = changes.get("config_patch")
        if config_patch:
            await patch_openclaw_config(owner_id, config_patch)
            logger.info("Applied config patch for update %s (owner=%s)", update_id, owner_id)

        # Step 3: apply ECS changes if present
        new_image = changes.get("new_image")
        new_cpu = changes.get("new_cpu")
        new_memory = changes.get("new_memory")

        if new_image or new_cpu or new_memory:
            # TODO: call ecs_manager.update_user_container() once implemented
            logger.info(
                "TODO: ECS update for owner=%s image=%s cpu=%s mem=%s (update=%s)",
                owner_id,
                new_image,
                new_cpu,
                new_memory,
                update_id,
            )

        # Step 4: mark as applied
        await update_repo.mark_applied(owner_id, update_id)
        logger.info("Update %s applied successfully (owner=%s, type=%s)", update_id, owner_id, update_type)
        return True

    except Exception:
        logger.exception("Failed to apply update %s (owner=%s)", update_id, owner_id)
        # Mark as failed
        try:
            await update_repo.set_status_conditional(owner_id, update_id, "failed", ["applying"])
        except Exception:
            logger.exception("Failed to mark update %s as failed", update_id)
        return False


async def run_scheduled_worker() -> None:
    """Background worker: poll for due scheduled updates and apply them.

    Runs every 60 seconds indefinitely.
    """
    logger.info("Scheduled update worker started")
    while True:
        try:
            due_updates = await update_repo.get_due_scheduled()
            if due_updates:
                logger.info("Found %d due scheduled updates", len(due_updates))
            for update in due_updates:
                owner_id = update["owner_id"]
                update_id = update["update_id"]
                try:
                    await apply_update(owner_id, update_id)
                except Exception:
                    logger.exception("Error applying scheduled update %s (owner=%s)", update_id, owner_id)
        except Exception:
            logger.exception("Error in scheduled update worker loop")

        await asyncio.sleep(60)
