import json

import boto3
import pytest
from moto import mock_aws

from core.services.catalog_s3_client import CatalogS3Client


@pytest.fixture
def bucket_name() -> str:
    return "isol8-test-agent-catalog"


@pytest.fixture
def s3_backend(bucket_name: str):
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket_name)
        yield client


def test_put_and_get_object_roundtrip(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    c.put_bytes("pitch/v1/manifest.json", b'{"slug":"pitch"}')
    got = c.get_bytes("pitch/v1/manifest.json")
    assert got == b'{"slug":"pitch"}'


def test_get_json_parses(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    c.put_bytes("catalog.json", json.dumps({"agents": []}).encode())
    assert c.get_json("catalog.json") == {"agents": []}


def test_get_json_missing_returns_default(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    assert c.get_json("missing.json", default={"x": 1}) == {"x": 1}


def test_put_json_writes_json(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    c.put_json("catalog.json", {"agents": [{"slug": "pitch"}]})
    body = s3_backend.get_object(Bucket=bucket_name, Key="catalog.json")["Body"].read()
    assert json.loads(body) == {"agents": [{"slug": "pitch"}]}


def test_list_versions_returns_version_numbers(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    c.put_bytes("pitch/v1/manifest.json", b"{}")
    c.put_bytes("pitch/v2/manifest.json", b"{}")
    c.put_bytes("pitch/v5/manifest.json", b"{}")
    assert c.list_versions("pitch") == [1, 2, 5]


def test_list_versions_empty_for_unknown_slug(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    assert c.list_versions("unknown") == []
