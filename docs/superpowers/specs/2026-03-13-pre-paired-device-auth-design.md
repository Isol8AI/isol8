# Pre-Paired Device Auth for Gateway Connections

**Date:** 2026-03-13
**Status:** Approved

## Problem

OpenClaw PR #44306 introduced `clearUnboundScopes()`, which strips all self-declared scopes from WebSocket connections that lack Ed25519 device identity. Our backend connects to per-user OpenClaw containers from VPC IPs (10.x.x.x), not loopback. OpenClaw's auto-pairing (`shouldAllowSilentLocalPairing`) requires loopback IPs, so auto-pairing fails after the first connection. This breaks every RPC requiring `operator.read` (agents.list, sessions.list, config.get, etc.), causing an empty "Select an agent" state in the chat UI.

## Solution

Pre-write OpenClaw's `devices/paired.json` file on EFS during container provisioning, with the backend's Ed25519 device identity pre-approved as a paired device. When OpenClaw starts, `getPairedDevice()` finds the device already paired, skipping the pairing flow entirely. Scopes are preserved regardless of client IP.

## File Format

OpenClaw stores paired devices at `{stateDir}/devices/paired.json`. The EFS mount maps `{mount_path}/{user_id}/` to `/home/node/.openclaw/` in the container, so we write to EFS path `devices/paired.json` relative to the user's workspace.

The file is a flat JSON object keyed by device ID (SHA-256 hex of the raw 32-byte Ed25519 public key):

```json
{
  "<device_id>": {
    "deviceId": "<device_id>",
    "publicKey": "<base64url-no-pad of raw 32-byte Ed25519 public key>",
    "platform": "linux",
    "clientId": "gateway-client",
    "clientMode": "backend",
    "role": "operator",
    "roles": ["operator"],
    "scopes": ["operator.admin"],
    "approvedScopes": ["operator.admin"],
    "createdAtMs": <epoch_ms>,
    "approvedAtMs": <epoch_ms>
  }
}
```

### Format Verification

Traced through OpenClaw source to confirm each field:

1. **deviceId**: `deriveDeviceIdFromPublicKey()` at `src/infra/device-identity.ts:143` — `crypto.createHash("sha256").update(rawPublicKeyBytes).digest("hex")`.
2. **publicKey**: `normalizeDevicePublicKeyBase64Url()` at `src/infra/device-identity.ts:131` — base64url encoding (RFC 7515, no padding) of the raw 32-byte Ed25519 public key.
3. **Pairing check** at `src/gateway/server/ws-connection/message-handler.ts:786-787`: `getPairedDevice(device.id)` reads `paired.json`, then `paired.publicKey === devicePublicKey` compares base64url-encoded public keys.
4. **Role check** at lines 821-843: `pairedRoles` must contain the requested role (`"operator"`).
5. **Scope check** at lines 846-866: `roleScopesAllow()` checks requested scopes against `approvedScopes`. For operator role, `operator.admin` satisfies all `operator.*` scopes via `operatorScopeSatisfied()` at `src/shared/operator-scope-compat.ts:18-19`.
6. **Scope normalization**: `normalizeDeviceAuthScopes()` at `src/shared/device-auth.ts:18` dedupes, trims, and sorts scopes alphabetically. `["operator.admin"]` normalizes to `["operator.admin"]` (single element, already sorted).

### clearUnboundScopes bypass

At `message-handler.ts:532`: `if (!device && (!isControlUi || decision.kind !== "allow"))` — when the backend sends a `device` field in connect params, `device` is truthy, so `clearUnboundScopes()` never fires regardless of IP or client type.

## Changes Required

### 1. `core/containers/config.py` — Add `write_paired_devices_config()`

New function that takes a device identity dict and returns the `paired.json` JSON string:

```python
def write_paired_devices_config(device_identity: dict) -> str:
    now_ms = int(time.time() * 1000)
    paired_device = {
        "deviceId": device_identity["device_id"],
        "publicKey": _base64url_encode(device_identity["public_key_raw"]),
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
    return json.dumps({device_identity["device_id"]: paired_device}, indent=2)
```

This requires importing `_base64url_encode` from `connection_pool.py` or moving it to a shared location. Since `config.py` shouldn't depend on `connection_pool.py`, move the base64url helper and device identity generation functions to `config.py` (or a new shared module).

### 2. Provisioning endpoints — Write `paired.json` during provisioning

**`routers/billing.py`** (Stripe webhook provisioning, ~line 231-239):
After writing `openclaw.json` and `mcporter.json`, also:
- Generate device identity
- Save PEM to `containers.device_private_key_pem`
- Write `devices/paired.json` to EFS

**`routers/debug.py`** POST `/provision` (~line 64-77):
Same as above.

**`routers/debug.py`** PATCH `/provision` (~line 104-132):
On redeploy, regenerate `paired.json` from existing device identity (load PEM from DB) or generate new if missing.

### 3. `core/gateway/connection_pool.py` — Keep existing device auth

The existing `_get_or_create_device_identity` and handshake code stays as-is. It loads the PEM from DB (saved during provisioning) and uses it for the Ed25519 signed handshake. The only difference is that now the device is already paired on the OpenClaw side.

### 4. Move shared helpers

Move `_base64url_encode`, `_generate_device_identity`, and `_load_device_identity` from `connection_pool.py` to a shared location (e.g., `core/containers/device_identity.py` or keep in `config.py`). Both `config.py` (for `write_paired_devices_config`) and `connection_pool.py` (for handshake signing) need them.

## Implementation Details

### Device identity generation timing

Device identity is generated **after** `create_user_service()` returns (which creates the EFS access point and user directory), but **before** the ECS service starts running. The provisioning sequence is:

1. `create_user_service()` — creates EFS access point + directory with UID=1000
2. Generate device identity
3. Save PEM to DB (`containers.device_private_key_pem`)
4. Write `devices/paired.json` to EFS
5. Write `openclaw.json` to EFS
6. Write `.mcporter/mcporter.json` to EFS

### Directory creation

`workspace.write_file()` calls `resolved.parent.mkdir(parents=True, exist_ok=True)` before writing, so the `devices/` subdirectory is created automatically. No manual `mkdir` needed.

### Scope handling

The `write_paired_devices_config()` function hardcodes `["operator.admin"]` for both `scopes` and `approvedScopes`. This is already normalized (single element, sorted). The backend only ever connects as `operator` role — no other roles are needed.

### PATCH endpoint fallback behavior

When PATCH `/debug/provision` rewrites config:
1. Load `device_private_key_pem` from DB for the user's container
2. If PEM exists: load identity from PEM, write `paired.json` from it
3. If PEM is NULL: generate new identity, save PEM to DB, write `paired.json`

This covers both pre-existing containers (no PEM yet) and containers where `paired.json` was lost.

## Data Flow

```
Provisioning (billing webhook or debug endpoint):
  1. create_user_service() → EFS access point + directory
  2. Generate Ed25519 keypair → _generate_device_identity()
  3. Save PEM to containers.device_private_key_pem in DB
  4. Write devices/paired.json to EFS (pre-approved operator.admin)
  5. Write openclaw.json to EFS
  6. Write .mcporter/mcporter.json to EFS

First backend connection to container:
  1. _get_or_create_device_identity() loads PEM from DB
  2. Handshake sends device field with signed Ed25519 payload
  3. OpenClaw reads devices/paired.json → isPaired=true
  4. Role/scope checks pass (operator + operator.admin)
  5. Scopes preserved, connection succeeds
```

## Edge Cases

**Existing containers without paired.json**: Containers provisioned before this change won't have the file. The PATCH `/debug/provision` endpoint (redeploy) will write it using the PATCH fallback behavior above. For production, a one-time migration or re-provision is needed.

**Existing containers without device_private_key_pem**: The `_get_or_create_device_identity` in `connection_pool.py` already handles this — it generates a new identity and saves PEM to DB. But without `paired.json` on EFS, pairing will fail. The PATCH endpoint handles this via fallback (generates new identity + writes paired.json).

**Deleted paired.json on EFS**: If `paired.json` is deleted but the container is still running and PEM is in DB, the next PATCH redeploy regenerates it. The connection pool's lazy identity generation ensures the backend still has the correct device identity.

**Container restarts**: `paired.json` persists on EFS across container restarts. The same device identity (loaded from DB) connects with the same keypair, matches the pre-paired entry.

**Multiple backend workers**: All uvicorn workers share the same DB, so they all load the same PEM and derive the same device ID. The in-memory cache in `_device_identities` is per-process but produces the same result.

## Testing

- Unit test for `write_paired_devices_config()`: verify JSON structure, field values, and that deviceId matches SHA-256 of the base64url-decoded publicKey.
- Unit test for round-trip: generate identity, write paired config, verify the publicKey in paired.json matches what `_base64url_encode(identity["public_key_raw"])` produces.
- Existing `test_connection_pool.py` and `test_chat_event_transform.py` tests continue to pass (already updated to pass `device_identity`).
