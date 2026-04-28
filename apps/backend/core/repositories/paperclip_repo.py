"""DynamoDB repository for paperclip-companies table.

PK: user_id (S)
Maps Isol8 user -> Paperclip company + encrypted credentials.

Async repository following the same pattern as peer repos in
``core/repositories/`` (api_key_repo, channel_link_repo, etc.): every
DynamoDB call is wrapped in ``run_in_thread`` and exposed as ``async def``
so future async callers (T11 paperclip_provisioning, T13 cleanup cron)
can ``await`` directly without ``asyncio.to_thread`` at each call site.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread

logger = logging.getLogger(__name__)


PaperclipCompanyStatus = Literal["provisioning", "active", "failed", "disabled"]


@dataclass
class PaperclipCompany:
    user_id: str
    company_id: str
    board_api_key_encrypted: str
    service_token_encrypted: str
    status: PaperclipCompanyStatus
    created_at: datetime
    updated_at: datetime
    last_error: Optional[str] = None
    scheduled_purge_at: Optional[datetime] = None


class PaperclipRepo:
    """Async repository for the paperclip-companies DynamoDB table.

    The table name is injected so the same repo class is usable for the
    real per-environment table (e.g. ``isol8-dev-paperclip-companies``)
    and for moto-backed unit tests. Internally we resolve the boto3
    Table via ``core.dynamodb.get_table`` so prefix-patching in tests
    (and the LocalStack endpoint override) Just Work.
    """

    def __init__(self, table_name: str, region: str | None = None):  # noqa: ARG002 - region kept for back-compat
        # ``region`` is accepted for back-compat with existing call sites
        # but ignored: the shared boto3 resource in core.dynamodb already
        # handles region + endpoint configuration.
        self._table_name = table_name

    def _table(self):
        return get_table(self._table_name)

    async def put(self, company: PaperclipCompany) -> None:
        item = {
            "user_id": company.user_id,
            "company_id": company.company_id,
            "board_api_key_encrypted": company.board_api_key_encrypted,
            "service_token_encrypted": company.service_token_encrypted,
            "status": company.status,
            "created_at": company.created_at.isoformat(),
            "updated_at": company.updated_at.isoformat(),
        }
        if company.last_error is not None:
            item["last_error"] = company.last_error
        if company.scheduled_purge_at is not None:
            item["scheduled_purge_at"] = company.scheduled_purge_at.isoformat()
        await run_in_thread(self._table().put_item, Item=item)

    async def get(self, user_id: str) -> Optional[PaperclipCompany]:
        resp = await run_in_thread(
            self._table().get_item,
            Key={"user_id": user_id},
        )
        if "Item" not in resp:
            return None
        item = resp["Item"]
        return PaperclipCompany(
            user_id=item["user_id"],
            company_id=item["company_id"],
            board_api_key_encrypted=item["board_api_key_encrypted"],
            service_token_encrypted=item["service_token_encrypted"],
            status=item["status"],
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
            last_error=item.get("last_error"),
            scheduled_purge_at=(
                datetime.fromisoformat(item["scheduled_purge_at"]) if item.get("scheduled_purge_at") else None
            ),
        )

    async def update_status(
        self,
        user_id: str,
        *,
        status: PaperclipCompanyStatus,
        last_error: Optional[str] = None,
        scheduled_purge_at: Optional[datetime] = None,
    ) -> None:
        update_expr = "SET #s = :s, updated_at = :u"
        expr_names = {"#s": "status"}
        expr_values: dict = {
            ":s": status,
            ":u": datetime.now(timezone.utc).isoformat(),
        }
        if last_error is not None:
            update_expr += ", last_error = :e"
            expr_values[":e"] = last_error
        if scheduled_purge_at is not None:
            update_expr += ", scheduled_purge_at = :p"
            expr_values[":p"] = scheduled_purge_at.isoformat()
        await run_in_thread(
            self._table().update_item,
            Key={"user_id": user_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )

    async def delete(self, user_id: str) -> None:
        await run_in_thread(
            self._table().delete_item,
            Key={"user_id": user_id},
        )

    async def scan_purge_due(self, now: datetime) -> list[PaperclipCompany]:
        """Return disabled rows whose ``scheduled_purge_at <= now`` via the GSI.

        Paginates through ``LastEvaluatedKey`` so larger result sets past
        the DynamoDB single-page Query limit (~1MB) are not silently
        dropped (mirrors the pagination pattern in
        ``api_key_repo.delete_all_for_owner``).
        """
        out: list[PaperclipCompany] = []
        last_evaluated_key: dict | None = None
        while True:
            kwargs: dict = {
                "IndexName": "by-status-purge-at",
                "KeyConditionExpression": (
                    Key("status").eq("disabled") & Key("scheduled_purge_at").lte(now.isoformat())
                ),
            }
            if last_evaluated_key is not None:
                kwargs["ExclusiveStartKey"] = last_evaluated_key
            resp = await run_in_thread(self._table().query, **kwargs)
            for item in resp.get("Items", []):
                company = await self.get(item["user_id"])
                if company is not None:
                    out.append(company)
                else:
                    logger.warning(
                        "paperclip_repo.scan_purge_due: GSI returned %s but base item missing",
                        item.get("user_id"),
                    )
            last_evaluated_key = resp.get("LastEvaluatedKey")
            if not last_evaluated_key:
                return out
