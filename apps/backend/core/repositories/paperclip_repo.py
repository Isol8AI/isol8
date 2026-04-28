"""DynamoDB repository for paperclip-companies table.

PK: user_id (S)
Maps Isol8 user -> Paperclip company + encrypted credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key


@dataclass
class PaperclipCompany:
    user_id: str
    company_id: str
    board_api_key_encrypted: str
    service_token_encrypted: str
    status: str  # "provisioning" | "active" | "failed" | "disabled"
    created_at: datetime
    updated_at: datetime
    last_error: Optional[str] = None
    scheduled_purge_at: Optional[datetime] = None


class PaperclipRepo:
    def __init__(self, table_name: str, region: str = "us-east-1"):
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def put(self, company: PaperclipCompany) -> None:
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
        self._table.put_item(Item=item)

    def get(self, user_id: str) -> Optional[PaperclipCompany]:
        resp = self._table.get_item(Key={"user_id": user_id})
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

    def update_status(
        self,
        user_id: str,
        *,
        status: str,
        last_error: Optional[str] = None,
        scheduled_purge_at: Optional[datetime] = None,
    ) -> None:
        update_expr = "SET #s = :s, updated_at = :u"
        expr_names = {"#s": "status"}
        expr_values = {
            ":s": status,
            ":u": datetime.now(timezone.utc).isoformat(),
        }
        if last_error is not None:
            update_expr += ", last_error = :e"
            expr_values[":e"] = last_error
        if scheduled_purge_at is not None:
            update_expr += ", scheduled_purge_at = :p"
            expr_values[":p"] = scheduled_purge_at.isoformat()
        self._table.update_item(
            Key={"user_id": user_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )

    def delete(self, user_id: str) -> None:
        self._table.delete_item(Key={"user_id": user_id})

    def scan_purge_due(self, now: datetime) -> list[PaperclipCompany]:
        """Scan disabled rows whose scheduled_purge_at <= now via the GSI."""
        resp = self._table.query(
            IndexName="by-status-purge-at",
            KeyConditionExpression=Key("status").eq("disabled") & Key("scheduled_purge_at").lte(now.isoformat()),
        )
        out: list[PaperclipCompany] = []
        for item in resp.get("Items", []):
            company = self.get(item["user_id"])
            if company is not None:
                out.append(company)
        return out
