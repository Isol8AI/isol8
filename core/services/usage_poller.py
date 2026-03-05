"""Background poller that syncs usage from OpenClaw gateway sessions.

Periodically polls each active user's gateway `sessions.list` RPC,
computes delta tokens from previously recorded events, and writes
new usage events. Works for all channels (web, Telegram, API, etc.).
"""

import asyncio
import logging
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.billing import BillingAccount, UsageEvent
from models.container import Container

logger = logging.getLogger(__name__)

POLL_INTERVAL = 300  # 5 minutes


class UsagePoller:
    """Background task that syncs gateway session usage into billing."""

    def __init__(self, db_factory):
        self._db_factory = db_factory
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Usage poller started (interval=%ds)", POLL_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Usage poller stopped")

    async def _loop(self) -> None:
        # Wait a bit on startup before first poll
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._poll_all_users()
            except Exception:
                logger.exception("Usage poller tick failed")
            await asyncio.sleep(POLL_INTERVAL)

    async def _poll_all_users(self) -> None:
        """Poll all active containers and sync their usage."""
        from core.containers import get_ecs_manager, get_gateway_pool
        from core.services.usage_service import UsageService

        pool = get_gateway_pool()
        ecs = get_ecs_manager()

        async with self._db_factory() as db:
            # Get all running containers
            result = await db.execute(
                select(Container).where(Container.status == "running")
            )
            containers = result.scalars().all()

        if not containers:
            return

        logger.debug("Usage poller: checking %d active containers", len(containers))
        total_synced = 0

        for container in containers:
            try:
                synced = await self._sync_user(
                    container.user_id,
                    container.gateway_token,
                    pool,
                    ecs,
                )
                total_synced += synced
            except Exception:
                logger.warning(
                    "Usage poller: failed to sync user %s", container.user_id,
                    exc_info=True,
                )

        if total_synced > 0:
            logger.info("Usage poller: synced %d session deltas", total_synced)

    async def _sync_user(
        self,
        user_id: str,
        gateway_token: str,
        pool,
        ecs,
    ) -> int:
        """Sync usage for a single user. Returns number of sessions synced."""
        from core.services.usage_service import UsageService

        # Resolve container IP
        async with self._db_factory() as db:
            container, ip = await ecs.resolve_running_container(user_id, db)

        if not container or not ip:
            return 0

        # Fetch sessions from gateway
        try:
            result = await pool.send_rpc(
                user_id=user_id,
                req_id=str(uuid4()),
                method="sessions.list",
                params={},
                ip=ip,
                token=gateway_token,
            )
        except Exception as e:
            logger.debug("Usage poller: gateway unreachable for user %s: %s", user_id, e)
            return 0

        sessions = result.get("sessions", []) if isinstance(result, dict) else []
        if not sessions:
            return 0

        # Get billing account and recorded tokens
        async with self._db_factory() as db:
            usage_service = UsageService(db)
            account = await usage_service.get_billing_account_for_user(user_id)
            if not account:
                logger.debug("Usage poller: no billing account for user %s", user_id)
                return 0

            recorded = await self._get_recorded_tokens(db, account.id)

            # Compute and record deltas
            synced = 0
            for session in sessions:
                session_key = session.get("key", "")
                if not session_key:
                    continue

                current_input = session.get("inputTokens", 0) or 0
                current_output = session.get("outputTokens", 0) or 0
                model = session.get("model", "") or "unknown"
                agent_id = session.get("agentId")

                prev = recorded.get(session_key, {"input": 0, "output": 0})
                delta_input = max(0, current_input - prev["input"])
                delta_output = max(0, current_output - prev["output"])

                if delta_input == 0 and delta_output == 0:
                    continue

                try:
                    await usage_service.record_usage(
                        billing_account_id=account.id,
                        clerk_user_id=user_id,
                        model_id=model,
                        input_tokens=delta_input,
                        output_tokens=delta_output,
                        source="agent",
                        session_id=session_key,
                        agent_id=agent_id,
                    )
                    synced += 1
                except Exception as e:
                    logger.warning(
                        "Usage poller: failed to record session %s for user %s: %s",
                        session_key, user_id, e,
                    )

            return synced

    @staticmethod
    async def _get_recorded_tokens(db: AsyncSession, billing_account_id) -> dict:
        """Get total recorded tokens per session_id from usage_event table."""
        result = await db.execute(
            select(
                UsageEvent.session_id,
                func.sum(UsageEvent.input_tokens).label("input"),
                func.sum(UsageEvent.output_tokens).label("output"),
            )
            .where(
                UsageEvent.billing_account_id == billing_account_id,
                UsageEvent.session_id.isnot(None),
            )
            .group_by(UsageEvent.session_id)
        )
        return {
            row.session_id: {"input": int(row.input), "output": int(row.output)}
            for row in result.all()
        }
