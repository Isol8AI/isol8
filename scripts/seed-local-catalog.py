"""Seed the LocalStack agent catalog with a fixture agent.

Usage:
  AWS_ENDPOINT_URL=http://localhost:4566 AGENT_CATALOG_BUCKET=isol8-local-agent-catalog \
    uv run python scripts/seed-local-catalog.py

Requires LocalStack running with S3 enabled. Creates the bucket if absent.
"""
from __future__ import annotations

import io
import json
import os
import tarfile

import boto3

BUCKET = os.environ["AGENT_CATALOG_BUCKET"]
ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")

s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    region_name="us-east-1",
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

try:
    s3.create_bucket(Bucket=BUCKET)
except s3.exceptions.BucketAlreadyOwnedByYou:
    pass

buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tf:
    data = b"name: Demo Pitch\nemoji: \xf0\x9f\x8e\xaf\nvibe: Direct\n"
    info = tarfile.TarInfo(name="./IDENTITY.md")
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))

s3.put_object(Bucket=BUCKET, Key="demo-pitch/v1/workspace.tar.gz", Body=buf.getvalue())
s3.put_object(
    Bucket=BUCKET,
    Key="demo-pitch/v1/manifest.json",
    Body=json.dumps(
        {
            "slug": "demo-pitch",
            "version": 1,
            "name": "Demo Pitch",
            "emoji": "\U0001f3af",
            "vibe": "Direct, data-driven",
            "description": "A fixture for local dev.",
            "suggested_model": "minimax/minimax-m2.5",
            "suggested_channels": [],
            "required_skills": [],
            "required_plugins": [],
            "required_tools": [],
            "published_at": "2026-04-19T00:00:00Z",
            "published_by": "local-seed",
        }
    ).encode(),
)
s3.put_object(
    Bucket=BUCKET,
    Key="demo-pitch/v1/openclaw-slice.json",
    Body=json.dumps(
        {
            "agent": {"name": "Demo Pitch", "emoji": "\U0001f3af", "skills": []},
            "plugins": {},
            "tools": {},
        }
    ).encode(),
)
s3.put_object(
    Bucket=BUCKET,
    Key="catalog.json",
    Body=json.dumps(
        {
            "updated_at": "2026-04-19T00:00:00Z",
            "agents": [
                {
                    "slug": "demo-pitch",
                    "current_version": 1,
                    "manifest_url": "demo-pitch/v1/manifest.json",
                },
            ],
        }
    ).encode(),
)
print("Seeded catalog in bucket", BUCKET)
