"""DynamoDB throttle-aware call wrapper.

Wraps all boto3 DynamoDB calls with metric emission and retry on throttle.
Uses asyncio.to_thread for sync boto3 calls to avoid blocking the event loop.
"""

import asyncio
from functools import partial

from botocore.exceptions import ClientError

from core.observability.metrics import put_metric

THROTTLE_CODES = {"ProvisionedThroughputExceededException", "ThrottlingException"}


async def call_with_metrics(table_name: str, op: str, fn, *args, **kwargs):
    """Call a boto3 DynamoDB op, emitting throttle/error metrics.

    Retries throttles up to 3x with exponential backoff.

    IMPORTANT: boto3 calls are SYNCHRONOUS. This wrapper uses
    asyncio.to_thread to avoid blocking the event loop.
    """
    for attempt in range(3):
        try:
            return await asyncio.to_thread(partial(fn, *args, **kwargs))
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in THROTTLE_CODES:
                put_metric("dynamodb.throttle", dimensions={"table": table_name, "op": op})
                if attempt < 2:
                    await asyncio.sleep(2**attempt * 0.1)  # 0.1s, 0.2s backoff
                    continue
                raise
            else:
                put_metric(
                    "dynamodb.error",
                    dimensions={"table": table_name, "op": op, "error_code": code},
                )
                raise
