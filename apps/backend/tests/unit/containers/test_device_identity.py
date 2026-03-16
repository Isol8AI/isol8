"""Tests for device identity helpers."""

import base64
import hashlib

from core.containers.device_identity import (
    base64url_encode,
    generate_device_identity,
    load_device_identity,
)


class TestBase64urlEncode:
    def test_encodes_bytes_without_padding(self):
        result = base64url_encode(b"\x00\x01\x02")
        assert isinstance(result, str)
        assert "=" not in result

    def test_round_trips_with_urlsafe_b64decode(self):
        data = b"hello world 1234"
        encoded = base64url_encode(data)
        # Add padding back for stdlib decode
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        assert decoded == data


class TestGenerateDeviceIdentity:
    def test_returns_required_keys(self):
        identity = generate_device_identity()
        assert "private_key" in identity
        assert "public_key_raw" in identity
        assert "device_id" in identity
        assert "private_key_pem" in identity

    def test_device_id_is_sha256_of_public_key(self):
        identity = generate_device_identity()
        expected = hashlib.sha256(identity["public_key_raw"]).hexdigest()
        assert identity["device_id"] == expected

    def test_public_key_raw_is_32_bytes(self):
        identity = generate_device_identity()
        assert len(identity["public_key_raw"]) == 32

    def test_private_key_pem_is_valid(self):
        identity = generate_device_identity()
        assert identity["private_key_pem"].startswith("-----BEGIN PRIVATE KEY-----")

    def test_generates_unique_keys(self):
        id1 = generate_device_identity()
        id2 = generate_device_identity()
        assert id1["device_id"] != id2["device_id"]


class TestLoadDeviceIdentity:
    def test_round_trips_with_generate(self):
        original = generate_device_identity()
        loaded = load_device_identity(original["private_key_pem"])
        assert loaded["device_id"] == original["device_id"]
        assert loaded["public_key_raw"] == original["public_key_raw"]
        assert loaded["private_key_pem"] == original["private_key_pem"]

    def test_can_sign_with_loaded_key(self):
        original = generate_device_identity()
        loaded = load_device_identity(original["private_key_pem"])
        # Should not raise
        loaded["private_key"].sign(b"test message")
