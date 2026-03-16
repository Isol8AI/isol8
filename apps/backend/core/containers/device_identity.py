"""
Ed25519 device identity helpers for OpenClaw gateway authentication.

Generates, loads, and encodes Ed25519 keypairs used for device-level
authentication with OpenClaw's gateway protocol.
"""

import base64
import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)


def base64url_encode(data: bytes) -> str:
    """Base64url encode without padding (RFC 7515)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_device_identity() -> dict:
    """Generate a new Ed25519 device identity.

    Returns dict with keys: private_key, public_key_raw, device_id, private_key_pem.
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    device_id = hashlib.sha256(public_key_raw).hexdigest()
    private_key_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode("ascii")
    return {
        "private_key": private_key,
        "public_key_raw": public_key_raw,
        "device_id": device_id,
        "private_key_pem": private_key_pem,
    }


def load_device_identity(private_key_pem: str) -> dict:
    """Reconstruct device identity from a stored PEM private key."""
    private_key = load_pem_private_key(private_key_pem.encode("ascii"), password=None)
    public_key = private_key.public_key()
    public_key_raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    device_id = hashlib.sha256(public_key_raw).hexdigest()
    return {
        "private_key": private_key,
        "public_key_raw": public_key_raw,
        "device_id": device_id,
        "private_key_pem": private_key_pem,
    }
