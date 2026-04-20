"""Thin S3 wrapper for the agent catalog bucket."""

from __future__ import annotations

import json
import re
from typing import Any

import boto3
from botocore.exceptions import ClientError

_VERSION_KEY_RE = re.compile(r"^[^/]+/v(\d+)/")


class CatalogS3Client:
    def __init__(self, bucket_name: str, region_name: str = "us-east-1"):
        if not bucket_name:
            raise ValueError("bucket_name is required")
        self._bucket = bucket_name
        self._s3 = boto3.client("s3", region_name=region_name)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def get_bytes(self, key: str) -> bytes:
        resp = self._s3.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def put_json(self, key: str, obj: Any) -> None:
        self.put_bytes(key, json.dumps(obj).encode("utf-8"), content_type="application/json")

    def get_json(self, key: str, default: Any = None) -> Any:
        try:
            return json.loads(self.get_bytes(key).decode("utf-8"))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return default
            raise

    def list_versions(self, slug: str) -> list[int]:
        """Return sorted list of published version numbers for a slug."""
        prefix = f"{slug}/"
        paginator = self._s3.get_paginator("list_objects_v2")
        versions: set[int] = set()
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                m = _VERSION_KEY_RE.match(obj["Key"])
                if m:
                    versions.add(int(m.group(1)))
        return sorted(versions)
