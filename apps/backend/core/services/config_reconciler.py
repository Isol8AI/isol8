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
import logging

from core.repositories import container_repo

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
        self._last_seen_mtime: dict[str, float] = {}
        self._tier_cache: dict[str, tuple[str, float]] = {}

    def stop(self) -> None:
        """Signal the loop to exit after its current tick."""
        self._stop.set()

    async def run_forever(self) -> None:
        logger.info("config_reconciler started")
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("config_reconciler tick failed")
            # Sleep until tick_interval elapses OR stop is set (whichever first).
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_interval)
            except asyncio.TimeoutError:
                pass
        logger.info("config_reconciler stopped")

    async def _tick(self) -> None:
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

        await asyncio.gather(*[_one(o) for o in owners])

    async def _check_one(self, owner_id: str) -> None:
        import os

        path = os.path.join(self._efs_mount, owner_id, "openclaw.json")
        try:
            mtime = await asyncio.to_thread(os.path.getmtime, path)
        except FileNotFoundError:
            # Container row says running but file not yet there; skip.
            return

        if self._last_seen_mtime.get(owner_id) == mtime:
            return

        # File changed (or first time seeing it); in this task, only record
        # the mtime. Actual read + policy + revert lands in Task 11.
        self._last_seen_mtime[owner_id] = mtime
