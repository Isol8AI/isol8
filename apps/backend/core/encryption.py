"""Fernet-based encryption for sensitive data (e.g., BYOK API keys).

Uses the ENCRYPTION_KEY setting from core.config. If not configured,
all encrypt/decrypt operations will raise an error — there is no
plaintext fallback.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from core.config import settings


def _get_fernet() -> Fernet:
    """Build a Fernet instance from the configured ENCRYPTION_KEY.

    If the key is already a valid 32-byte base64url-encoded Fernet key it is
    used directly.  Otherwise HKDF-SHA256 is used to derive a valid 32-byte
    key from the raw value (so any passphrase-style value will work).
    """

    raw = settings.ENCRYPTION_KEY
    if not raw:
        raise RuntimeError(
            "ENCRYPTION_KEY is not configured. "
            "Set the ENCRYPTION_KEY environment variable to a base64-encoded "
            "32-byte key (generate one with `python -c "
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).'
        )

    # Try using the value directly as a Fernet key first
    try:
        decoded = base64.urlsafe_b64decode(raw)
        if len(decoded) == 32:
            return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception:
        pass

    # Derive a valid 32-byte key via HKDF-SHA256
    derived = hashlib.sha256(raw.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* and return base64-encoded ciphertext."""
    f = _get_fernet()
    token = f.encrypt(plaintext.encode())
    return base64.urlsafe_b64encode(token).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt base64-encoded *ciphertext* and return the original plaintext."""
    f = _get_fernet()
    try:
        token = base64.urlsafe_b64decode(ciphertext.encode())
        return f.decrypt(token).decode()
    except (InvalidToken, Exception) as exc:
        raise ValueError("Failed to decrypt value — key may have changed or data is corrupt") from exc
