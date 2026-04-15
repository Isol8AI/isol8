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
        """One pass over the active-owner set. No-op in the skeleton."""
        return
