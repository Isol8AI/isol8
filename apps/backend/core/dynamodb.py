"""DynamoDB client singleton and helpers."""

import asyncio
import functools
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import boto3

from core.config import settings

_table_prefix: str = getattr(settings, "DYNAMODB_TABLE_PREFIX", "")
_dynamodb_resource = None


def _get_resource():
    global _dynamodb_resource
    if _dynamodb_resource is None:
        kwargs = {}
        endpoint = getattr(settings, "DYNAMODB_ENDPOINT_URL", None)
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        _dynamodb_resource = boto3.resource(
            "dynamodb",
            region_name=getattr(settings, "AWS_REGION", "us-east-1"),
            **kwargs,
        )
    return _dynamodb_resource


def table_name(short_name: str) -> str:
    return f"{_table_prefix}{short_name}"


def get_table(short_name: str):
    return _get_resource().Table(table_name(short_name))


T = TypeVar("T")


async def run_in_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return await asyncio.to_thread(functools.partial(func, **kwargs) if kwargs else func, *args)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
