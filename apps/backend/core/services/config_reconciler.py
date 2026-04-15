"""Backend reconciliation loop for openclaw.json tier policy.

Polls every active user's config on EFS at ~1s cadence, evaluates it
against the tier policy (core.services.config_policy), and reverts drift
on locked fields only. Non-locked fields are never touched.

Ships in three modes via CONFIG_RECONCILER_MODE:
  - off: reconciler never starts
  - report: reads + evaluates + logs, never writes (rollout phase A)
  - enforce: reads + evaluates + reverts (rollout phase B, steady state)
"""

import asyncio
import json
import logging
import os
import time

from core.config import settings
from core.observability.metrics import put_metric
from core.repositories import billing_repo, container_repo
from core.services import config_policy
from core.services.config_patcher import locked_rmw

logger = logging.getLogger(__name__)


class ConfigReconciler:
    def __init__(
        self,
        efs_mount: str,
        tier_cache_ttl: float = 60.0,
        tick_interval: float = 1.0,
    ):
        self._efs_mount = efs_mount
        self._tier_cache_ttl = tier_cache_ttl
        self._tick_interval = tick_interval
        self._stop = asyncio.Event()
        # Cache key combines mtime AND tier so a plan change alone (without a
        # file edit) still triggers re-evaluation once the tier-cache TTL
        # expires. Otherwise a paid→free downgrade where the user hasn't
        # touched openclaw.json would never be observed.
        self._last_seen: dict[str, tuple[float, str]] = {}
        self._tier_cache: dict[str, tuple[str, float]] = {}

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        logger.info("config_reconciler started mode=%s", settings.CONFIG_RECONCILER_MODE)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("config_reconciler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_interval)
            except asyncio.TimeoutError:
                pass
        logger.info("config_reconciler stopped")

    async def _tick(self) -> None:
        if settings.CONFIG_RECONCILER_MODE == "off":
            return
        owners = await container_repo.list_active_owners()
        if not owners:
            return

        sem = asyncio.Semaphore(20)

        async def _one(owner_id: str):
            async with sem:
                try:
                    await self._check_one(owner_id)
                except Exception:
                    logger.exception("config_reconciler failed for owner %s", owner_id)

        started = time.monotonic()
        await asyncio.gather(*[_one(o) for o in owners])
        put_metric(
            "config.reconciler.tick.duration",
            value=(time.monotonic() - started) * 1000.0,
            unit="Milliseconds",
            dimensions={"mode": settings.CONFIG_RECONCILER_MODE},
        )

    async def _check_one(self, owner_id: str) -> None:
        # Defense-in-depth against path traversal: owner_ids come from Clerk +
        # DynamoDB and are always safe, but this function now writes to EFS,
        # so guard against unexpected slashes, dotfiles, or `..` segments.
        if not owner_id or "/" in owner_id or ".." in owner_id or owner_id.startswith("."):
            return

        path = os.path.join(self._efs_mount, owner_id, "openclaw.json")
        try:
            mtime = await asyncio.to_thread(os.path.getmtime, path)
        except FileNotFoundError:
            return

        tier = await self._resolve_tier(owner_id)
        if tier is None:
            # Fail-open: don't lock a user out of their own plan due to our DDB error.
            return

        # Short-circuit only when BOTH the file and the user's tier are
        # unchanged since the last tick. A tier change with an untouched
        # file must still re-evaluate (paid→free downgrade case).
        if self._last_seen.get(owner_id) == (mtime, tier):
            return

        grace_until = await container_repo.get_reconciler_grace(owner_id)
        if grace_until > int(time.time()):
            # Admin just wrote; don't fight them.
            return

        mode = settings.CONFIG_RECONCILER_MODE

        if mode == "report":
            # Read without a lock (we're not writing); evaluate; log.
            try:
                config = await asyncio.to_thread(_read_json, path)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("reconciler: failed to read %s: %s", path, e)
                put_metric("config.reconciler.errors", dimensions={"kind": "read"})
                return
            violations = config_policy.evaluate(config, tier)
            if violations:
                put_metric("config.drift.reported", dimensions={"tier": tier})
                logger.info(
                    "reconciler(report) drift for owner=%s tier=%s fields=%s",
                    owner_id,
                    tier,
                    [v["field"] for v in violations],
                )
            self._last_seen[owner_id] = (mtime, tier)
            return

        if mode == "enforce":
            reverted_fields: list[str] = []

            def _mutate(current: dict) -> bool:
                violations = config_policy.evaluate(current, tier)
                if not violations:
                    return False
                reverted = config_policy.apply_reverts(current, violations)
                current.clear()
                current.update(reverted)
                reverted_fields.extend(v["field"] for v in violations)
                return True

            try:
                await locked_rmw(owner_id, _mutate, "policy_revert")
            except Exception as e:
                logger.exception("reconciler: revert failed for owner=%s: %s", owner_id, e)
                put_metric("config.reconciler.errors", dimensions={"kind": "revert"})
                return

            if reverted_fields:
                put_metric("config.drift.reverted", dimensions={"tier": tier})
                logger.info(
                    "reconciler(enforce) reverted owner=%s tier=%s fields=%s",
                    owner_id,
                    tier,
                    reverted_fields,
                )
                # Revert events are observable via the logger.info above
                # (CloudWatch) and the config.drift.reverted metric. No
                # dedicated audit log table — those two channels give us
                # sufficient observability for this loop.
            # Mtime moved from our own write; refresh cache from the fresh stat.
            try:
                new_mtime = await asyncio.to_thread(os.path.getmtime, path)
                self._last_seen[owner_id] = (new_mtime, tier)
            except FileNotFoundError:
                self._last_seen.pop(owner_id, None)
            return

        # Unknown mode — behave as off.
        logger.warning("unknown CONFIG_RECONCILER_MODE=%r, treating as off", mode)

    async def _resolve_tier(self, owner_id: str) -> str | None:
        cached = self._tier_cache.get(owner_id)
        now = time.monotonic()
        if cached and now - cached[1] < self._tier_cache_ttl:
            return cached[0]
        try:
            account = await billing_repo.get_by_owner_id(owner_id)
        except Exception:
            logger.exception("reconciler: billing_repo lookup failed for owner=%s", owner_id)
            put_metric("config.reconciler.errors", dimensions={"kind": "tier_lookup"})
            return None
        tier = (account or {}).get("plan_tier", "free")
        self._tier_cache[owner_id] = (tier, now)
        return tier


def _read_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)
