"""One-shot backfill: encrypt plaintext gateway_token values in the containers table.

Idempotent — skips rows that already have an 'enc:' prefix.

Usage:
    cd apps/backend
    uv run python scripts/backfill_gateway_token_encryption.py
"""

import os
import sys

# Ensure the backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

import boto3

from core.config import settings
from core.services.key_service import encrypt_gateway_token


def main():
    prefix = settings.DYNAMODB_TABLE_PREFIX
    table_name = f"{prefix}containers"

    kwargs = {}
    endpoint = getattr(settings, "DYNAMODB_ENDPOINT_URL", None)
    if endpoint:
        kwargs["endpoint_url"] = endpoint

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=getattr(settings, "AWS_REGION", "us-east-1"),
        **kwargs,
    )
    table = dynamodb.Table(table_name)

    print(f"Scanning {table_name} for plaintext gateway_token values...")

    encrypted_count = 0
    skipped_count = 0
    last_key = None

    while True:
        scan_kwargs = {"ProjectionExpression": "owner_id, gateway_token"}
        if last_key:
            scan_kwargs["ExclusiveStartKey"] = last_key

        response = table.scan(**scan_kwargs)

        for item in response.get("Items", []):
            owner_id = item.get("owner_id")
            token = item.get("gateway_token", "")

            if not token:
                skipped_count += 1
                continue

            if token.startswith("enc:"):
                skipped_count += 1
                continue

            # Encrypt and write back
            encrypted = encrypt_gateway_token(token)
            table.update_item(
                Key={"owner_id": owner_id},
                UpdateExpression="SET gateway_token = :enc",
                ExpressionAttributeValues={":enc": encrypted},
            )
            encrypted_count += 1
            print(f"  Encrypted gateway_token for owner {owner_id}")

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break

    print(f"Done. Encrypted: {encrypted_count}, Skipped: {skipped_count}")


if __name__ == "__main__":
    main()
