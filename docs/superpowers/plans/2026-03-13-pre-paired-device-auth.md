# Pre-Paired Device Auth Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pre-write OpenClaw's `devices/paired.json` on EFS during provisioning so the backend's device identity is already paired when OpenClaw starts, eliminating the "pairing required" failure on VPC connections.

**Architecture:** Extract device identity helpers into a shared module (`core/containers/device_identity.py`). Add a `write_paired_devices_config()` function to `core/containers/config.py`. Update provisioning endpoints (billing webhook + debug) to generate device identity and write `paired.json` alongside existing config files.

**Tech Stack:** Python 3.12, Ed25519 (cryptography lib), SQLAlchemy async, FastAPI, EFS via Workspace helper.

**Spec:** `docs/superpowers/specs/2026-03-13-pre-paired-device-auth-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `core/containers/device_identity.py` | Create | Shared Ed25519 device identity helpers (generate, load, base64url encode) |
| `core/containers/config.py` | Modify | Add `write_paired_devices_config()` |
| `core/gateway/connection_pool.py` | Modify | Import helpers from `device_identity.py` instead of defining locally |
| `routers/debug.py` | Modify | Write `paired.json` during POST and PATCH provisioning |
| `routers/billing.py` | Modify | Write `paired.json` during Stripe webhook provisioning |
| `tests/unit/containers/test_device_identity.py` | Create | Tests for device identity helpers |
| `tests/unit/containers/test_config.py` | Modify | Add tests for `write_paired_devices_config()` |

---

## Chunk 1: Extract Device Identity Module + Paired Config

### Task 1: Create `core/containers/device_identity.py` with tests

**Files:**
- Create: `core/containers/device_identity.py`
- Create: `tests/unit/containers/test_device_identity.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/containers/test_device_identity.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/containers/test_device_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.containers.device_identity'`

- [ ] **Step 3: Write the implementation**

```python
# core/containers/device_identity.py
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
    private_key_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode("ascii")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/containers/test_device_identity.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/containers/device_identity.py tests/unit/containers/test_device_identity.py
git commit -m "feat: extract device identity helpers into shared module"
```

---

### Task 2: Add `write_paired_devices_config()` to `config.py` with tests

**Files:**
- Modify: `core/containers/config.py`
- Modify: `tests/unit/containers/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/unit/containers/test_config.py`:

```python
class TestWritePairedDevicesConfig:
    """Test paired.json generation for pre-pairing device auth."""

    def test_returns_valid_json(self):
        from core.containers.device_identity import generate_device_identity
        from core.containers.config import write_paired_devices_config

        identity = generate_device_identity()
        result = write_paired_devices_config(identity)
        config = json.loads(result)
        assert isinstance(config, dict)

    def test_keyed_by_device_id(self):
        from core.containers.device_identity import generate_device_identity
        from core.containers.config import write_paired_devices_config

        identity = generate_device_identity()
        config = json.loads(write_paired_devices_config(identity))
        assert identity["device_id"] in config

    def test_device_entry_has_required_fields(self):
        from core.containers.device_identity import generate_device_identity
        from core.containers.config import write_paired_devices_config

        identity = generate_device_identity()
        config = json.loads(write_paired_devices_config(identity))
        entry = config[identity["device_id"]]
        assert entry["deviceId"] == identity["device_id"]
        assert entry["role"] == "operator"
        assert entry["roles"] == ["operator"]
        assert entry["scopes"] == ["operator.admin"]
        assert entry["approvedScopes"] == ["operator.admin"]
        assert entry["platform"] == "linux"
        assert entry["clientId"] == "gateway-client"
        assert entry["clientMode"] == "backend"
        assert isinstance(entry["createdAtMs"], int)
        assert isinstance(entry["approvedAtMs"], int)

    def test_public_key_matches_identity(self):
        import base64
        import hashlib
        from core.containers.device_identity import generate_device_identity
        from core.containers.config import write_paired_devices_config

        identity = generate_device_identity()
        config = json.loads(write_paired_devices_config(identity))
        entry = config[identity["device_id"]]
        # Decode the base64url publicKey and verify it matches
        pub_key_b64 = entry["publicKey"]
        padded = pub_key_b64 + "=" * (-len(pub_key_b64) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        assert decoded == identity["public_key_raw"]
        # Verify device_id is SHA-256 of decoded public key
        assert hashlib.sha256(decoded).hexdigest() == identity["device_id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/containers/test_config.py::TestWritePairedDevicesConfig -v`
Expected: FAIL — `ImportError: cannot import name 'write_paired_devices_config'`

- [ ] **Step 3: Write the implementation**

Add to `core/containers/config.py`, after the existing imports:

```python
import time

from core.containers.device_identity import base64url_encode
```

Add the function after `write_mcporter_config()`:

```python
def write_paired_devices_config(device_identity: dict) -> str:
    """Generate a paired.json config for pre-pairing a device with OpenClaw.

    The file is written to {user_workspace}/devices/paired.json on EFS,
    which maps to ~/.openclaw/devices/paired.json inside the container.

    Args:
        device_identity: Dict from generate_device_identity() or
            load_device_identity(), must contain device_id and public_key_raw.

    Returns:
        JSON string of the paired.json file.
    """
    now_ms = int(time.time() * 1000)
    device_id = device_identity["device_id"]
    paired_device = {
        "deviceId": device_id,
        "publicKey": base64url_encode(device_identity["public_key_raw"]),
        "platform": "linux",
        "clientId": "gateway-client",
        "clientMode": "backend",
        "role": "operator",
        "roles": ["operator"],
        "scopes": ["operator.admin"],
        "approvedScopes": ["operator.admin"],
        "createdAtMs": now_ms,
        "approvedAtMs": now_ms,
    }
    return json.dumps({device_id: paired_device}, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/containers/test_config.py -v`
Expected: All tests PASS (existing + 4 new)

- [ ] **Step 5: Commit**

```bash
git add core/containers/config.py tests/unit/containers/test_config.py
git commit -m "feat: add write_paired_devices_config for pre-pairing device auth"
```

---

## Chunk 2: Update Provisioning Endpoints + Refactor connection_pool.py

### Task 3: Update `connection_pool.py` to use shared `device_identity` module

**Files:**
- Modify: `core/gateway/connection_pool.py`

- [ ] **Step 1: Replace local helpers with imports from device_identity module**

In `core/gateway/connection_pool.py`:

**A. Replace the serialization import block (lines 20-26):**

Before:
```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
```

After:
```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.containers.device_identity import (
    base64url_encode as _base64url_encode,
    generate_device_identity as _generate_device_identity,
    load_device_identity as _load_device_identity,
)
```

Note: `Ed25519PrivateKey` is still needed for the type annotation in `_sign_device_payload`. The `Encoding`, `NoEncryption`, `PrivateFormat`, `PublicFormat` imports are no longer needed because they were only used inside the local `_generate_device_identity` and `_load_device_identity` functions being removed.

**B. Delete these three local function definitions (lines 38-79):**
- `_base64url_encode` (lines 43-45)
- `_generate_device_identity` (lines 48-63)
- `_load_device_identity` (lines 66-79)

**C. Keep these functions** which are unique to `connection_pool.py`:
- `_build_device_auth_payload_v3` (lines 82-113)
- `_sign_device_payload` (lines 116-119)

- [ ] **Step 2: Run existing tests to verify nothing broke**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/core/test_connection_pool.py tests/unit/core/test_chat_event_transform.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add core/gateway/connection_pool.py
git commit -m "refactor: use shared device_identity module in connection_pool"
```

---

### Task 4: Update `routers/debug.py` to write `paired.json` during provisioning

**Files:**
- Modify: `routers/debug.py`

- [ ] **Step 1: Update POST `/provision` to generate device identity and write paired.json**

Add imports at the top of `routers/debug.py`:
```python
from core.containers.config import write_mcporter_config, write_openclaw_config, write_paired_devices_config
from core.containers.device_identity import generate_device_identity, load_device_identity
```

(Remove the existing `from core.containers.config import write_mcporter_config, write_openclaw_config` line.)

In the `provision_container` function, after `service_name = await get_ecs_manager().create_user_service(...)`, add device identity generation and paired.json writing:

```python
        # Generate device identity for gateway auth
        device_identity = generate_device_identity()

        # Save device key to DB
        from sqlalchemy import update as sql_update
        from models.container import Container as ContainerModel
        await db.execute(
            sql_update(ContainerModel)
            .where(ContainerModel.user_id == user_id)
            .values(device_private_key_pem=device_identity["private_key_pem"])
        )
        await db.commit()

        # Write configs to EFS
        config_json = write_openclaw_config(
            region=settings.AWS_REGION,
            gateway_token=gateway_token,
            proxy_base_url=settings.PROXY_BASE_URL,
        )
        get_workspace().write_file(user_id, "openclaw.json", config_json)
        get_workspace().write_file(user_id, ".mcporter/mcporter.json", write_mcporter_config())
        get_workspace().write_file(user_id, "devices/paired.json", write_paired_devices_config(device_identity))
```

- [ ] **Step 2: Update PATCH `/provision` to write paired.json on redeploy**

In the `redeploy_container` function, after writing `openclaw.json`, add:

```python
        # Write/update paired.json for device auth
        pem = container.device_private_key_pem
        if pem:
            device_identity = load_device_identity(pem)
        else:
            device_identity = generate_device_identity()
            from sqlalchemy import update as sql_update
            from models.container import Container as ContainerModel
            await db.execute(
                sql_update(ContainerModel)
                .where(ContainerModel.user_id == user_id)
                .values(device_private_key_pem=device_identity["private_key_pem"])
            )
            await db.commit()
        get_workspace().write_file(user_id, "devices/paired.json", write_paired_devices_config(device_identity))
```

- [ ] **Step 3: Run all backend tests**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add routers/debug.py
git commit -m "feat: write paired.json during debug provisioning and redeploy"
```

---

### Task 5: Update `routers/billing.py` to write `paired.json` during Stripe provisioning

**Files:**
- Modify: `routers/billing.py`

- [ ] **Step 1: Add paired.json writing to Stripe webhook provisioning**

Add imports at the top of `routers/billing.py`:
```python
from core.containers.config import write_mcporter_config, write_openclaw_config, write_paired_devices_config
from core.containers.device_identity import generate_device_identity
```

(Remove the existing `from core.containers.config import write_mcporter_config, write_openclaw_config` line.)

In the `stripe_webhook` function, after writing `openclaw.json` and `mcporter.json` (~line 238-239), add:

```python
                # Generate device identity and write paired.json for gateway auth
                device_identity = generate_device_identity()
                from sqlalchemy import update as sql_update
                from models.container import Container as ContainerModel
                await db.execute(
                    sql_update(ContainerModel)
                    .where(ContainerModel.user_id == user_id)
                    .values(device_private_key_pem=device_identity["private_key_pem"])
                )
                await db.commit()
                get_workspace().write_file(user_id, "devices/paired.json", write_paired_devices_config(device_identity))
```

- [ ] **Step 2: Run all backend tests**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add routers/billing.py
git commit -m "feat: write paired.json during Stripe webhook provisioning"
```

---

### Task 6: Run full test suite and verify

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run linter**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m ruff check .`
Expected: No errors

- [ ] **Step 3: Verify the paired.json format with a quick smoke test**

Run in Python:
```python
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -c "
import json, base64, hashlib
from core.containers.device_identity import generate_device_identity
from core.containers.config import write_paired_devices_config

identity = generate_device_identity()
config = json.loads(write_paired_devices_config(identity))
device_id = identity['device_id']
entry = config[device_id]

# Verify device_id derivation
pub_b64 = entry['publicKey']
padded = pub_b64 + '=' * (-len(pub_b64) % 4)
raw = base64.urlsafe_b64decode(padded)
assert hashlib.sha256(raw).hexdigest() == device_id, 'device_id mismatch'
assert entry['role'] == 'operator'
assert entry['approvedScopes'] == ['operator.admin']
print('OK: paired.json format verified')
"
```
Expected: `OK: paired.json format verified`
