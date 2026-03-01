"""Tests for ConfigStore (S3-backed per-user openclaw.json storage).

Uses mocked boto3 S3 client -- no real AWS required.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from core.containers.config_store import ConfigStore, ConfigStoreError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 boto3 client."""
    client = MagicMock()
    return client


@pytest.fixture
def store(mock_s3_client):
    """Create a ConfigStore with mocked boto3 S3 client."""
    with patch("core.containers.config_store.boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_s3_client
        s = ConfigStore(bucket="test-config-bucket")
    return s


@pytest.fixture
def sample_config():
    """A minimal openclaw.json config dict for testing."""
    return {
        "gateway": {"mode": "local", "auth": {"mode": "none"}},
        "models": {"providers": {}},
        "agents": {"defaults": {"model": {"primary": "test-model"}}},
    }


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestConfigStoreInit:
    """Test ConfigStore initialization."""

    def test_stores_bucket_name(self, store):
        """Bucket name is stored on the instance."""
        assert store._bucket == "test-config-bucket"

    def test_creates_s3_client(self):
        """boto3 S3 client is created with correct region."""
        with patch("core.containers.config_store.boto3") as mock_boto3:
            with patch("core.containers.config_store.settings") as mock_settings:
                mock_settings.AWS_REGION = "us-west-2"
                ConfigStore(bucket="my-bucket")

        mock_boto3.client.assert_called_once_with("s3", region_name="us-west-2")


# ---------------------------------------------------------------------------
# S3 key generation
# ---------------------------------------------------------------------------


class TestS3Key:
    """Test S3 key pattern."""

    def test_key_pattern(self, store):
        """S3 key follows users/{user_id}/openclaw.json pattern."""
        key = store._s3_key("user_abc123")
        assert key == "users/user_abc123/openclaw.json"

    def test_key_with_special_chars(self, store):
        """User IDs with underscores and hyphens are preserved."""
        key = store._s3_key("user_test-long_id-456")
        assert key == "users/user_test-long_id-456/openclaw.json"


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------


class TestGetConfig:
    """Test reading openclaw.json from S3."""

    def test_returns_parsed_json(self, store, mock_s3_client, sample_config):
        """get_config reads and parses JSON from S3."""
        body_mock = MagicMock()
        body_mock.read.return_value = json.dumps(sample_config).encode("utf-8")
        mock_s3_client.get_object.return_value = {"Body": body_mock}

        result = store.get_config("user_abc")

        assert result == sample_config
        mock_s3_client.get_object.assert_called_once_with(
            Bucket="test-config-bucket",
            Key="users/user_abc/openclaw.json",
        )

    def test_returns_none_when_key_missing(self, store, mock_s3_client):
        """get_config returns None when the S3 key does not exist."""
        mock_s3_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
            "GetObject",
        )

        result = store.get_config("user_nonexistent")
        assert result is None

    def test_raises_on_other_s3_errors(self, store, mock_s3_client):
        """get_config raises ConfigStoreError on non-NoSuchKey errors."""
        mock_s3_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "GetObject",
        )

        with pytest.raises(ConfigStoreError, match="Failed to read config"):
            store.get_config("user_abc")

    def test_raises_on_invalid_json(self, store, mock_s3_client):
        """get_config raises ConfigStoreError when S3 object contains invalid JSON."""
        body_mock = MagicMock()
        body_mock.read.return_value = b"not valid json {{"
        mock_s3_client.get_object.return_value = {"Body": body_mock}

        with pytest.raises(ConfigStoreError, match="Failed to parse config"):
            store.get_config("user_abc")


# ---------------------------------------------------------------------------
# put_config
# ---------------------------------------------------------------------------


class TestPutConfig:
    """Test writing openclaw.json to S3."""

    def test_writes_json_to_s3(self, store, mock_s3_client, sample_config):
        """put_config serializes config to JSON and writes to S3."""
        store.put_config("user_abc", sample_config)

        mock_s3_client.put_object.assert_called_once_with(
            Bucket="test-config-bucket",
            Key="users/user_abc/openclaw.json",
            Body=json.dumps(sample_config, indent=2),
            ContentType="application/json",
        )

    def test_raises_on_s3_error(self, store, mock_s3_client, sample_config):
        """put_config raises ConfigStoreError on S3 failure."""
        mock_s3_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "Internal Error"}},
            "PutObject",
        )

        with pytest.raises(ConfigStoreError, match="Failed to write config"):
            store.put_config("user_abc", sample_config)

    def test_json_is_pretty_printed(self, store, mock_s3_client):
        """put_config writes indented JSON for readability."""
        config = {"key": "value"}
        store.put_config("user_abc", config)

        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        body = call_kwargs["Body"]
        assert body == json.dumps(config, indent=2)
        # Verify it contains newlines (pretty-printed)
        assert "\n" in body


# ---------------------------------------------------------------------------
# delete_config
# ---------------------------------------------------------------------------


class TestDeleteConfig:
    """Test deleting openclaw.json from S3."""

    def test_deletes_object_from_s3(self, store, mock_s3_client):
        """delete_config removes the object from S3."""
        store.delete_config("user_abc")

        mock_s3_client.delete_object.assert_called_once_with(
            Bucket="test-config-bucket",
            Key="users/user_abc/openclaw.json",
        )

    def test_no_error_when_key_missing(self, store, mock_s3_client):
        """delete_config succeeds silently when key doesn't exist (S3 delete is idempotent)."""
        # S3 delete_object doesn't raise on missing keys by default
        mock_s3_client.delete_object.return_value = {}

        store.delete_config("user_nonexistent")  # Should not raise
        mock_s3_client.delete_object.assert_called_once()

    def test_raises_on_s3_error(self, store, mock_s3_client):
        """delete_config raises ConfigStoreError on S3 failure."""
        mock_s3_client.delete_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "DeleteObject",
        )

        with pytest.raises(ConfigStoreError, match="Failed to delete config"):
            store.delete_config("user_abc")


# ---------------------------------------------------------------------------
# config_exists
# ---------------------------------------------------------------------------


class TestConfigExists:
    """Test checking if openclaw.json exists in S3."""

    def test_returns_true_when_exists(self, store, mock_s3_client):
        """config_exists returns True when the S3 key exists."""
        mock_s3_client.head_object.return_value = {"ContentLength": 1024}

        assert store.config_exists("user_abc") is True
        mock_s3_client.head_object.assert_called_once_with(
            Bucket="test-config-bucket",
            Key="users/user_abc/openclaw.json",
        )

    def test_returns_false_when_missing(self, store, mock_s3_client):
        """config_exists returns False when the S3 key does not exist."""
        mock_s3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "HeadObject",
        )

        assert store.config_exists("user_abc") is False

    def test_raises_on_other_errors(self, store, mock_s3_client):
        """config_exists raises ConfigStoreError on non-404 errors."""
        mock_s3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}},
            "HeadObject",
        )

        with pytest.raises(ConfigStoreError, match="Failed to check config"):
            store.config_exists("user_abc")


# ---------------------------------------------------------------------------
# ConfigStoreError
# ---------------------------------------------------------------------------


class TestConfigStoreError:
    """Test custom exception."""

    def test_error_message(self):
        """ConfigStoreError stores message."""
        err = ConfigStoreError("something failed", user_id="user_123")
        assert str(err) == "something failed"
        assert err.user_id == "user_123"

    def test_error_without_user_id(self):
        """ConfigStoreError defaults user_id to empty string."""
        err = ConfigStoreError("generic failure")
        assert err.user_id == ""
