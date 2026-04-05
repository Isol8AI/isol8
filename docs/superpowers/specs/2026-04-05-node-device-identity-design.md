# Persistent Node Device Identity for Desktop Local Tools

**Date:** 2026-04-05
**Status:** Approved

## Problem

OpenClaw requires Ed25519 device identity for `role:"node"` WebSocket connections. After CVE-2026-32057, node pairing cannot be bypassed even in trusted-proxy auth mode. The backend's current `NodeUpstreamConnection` generates ephemeral keypairs that are never in `nodes/paired.json`, so the container rejects every connection with "pairing required".

## Solution

Generate a persistent Ed25519 keypair per user during container provisioning. Pre-write the public key to `nodes/paired.json` on EFS so OpenClaw recognizes it as a paired device. Store the private key PEM at `nodes/.node-device-key.pem` on the same EFS mount. On each node connect, load the key and sign the challenge.

## Data Flow

```
Provisioning (ecs_manager._write_user_configs):
  1. Generate Ed25519 keypair
  2. Write nodes/paired.json to EFS (public key entry)
  3. Write nodes/.node-device-key.pem to EFS (private key)

Node connect (NodeUpstreamConnection.connect):
  1. Read private key from EFS: {mount}/{user_id}/nodes/.node-device-key.pem
  2. Derive device_id (SHA-256 hex of raw public key)
  3. Receive connect.challenge with nonce from container
  4. Sign v2 payload: "v2|{deviceId}|{clientId}|{clientMode}|{role}|{scopes}|{signedAtMs}|{token}|{nonce}"
  5. Send connect with device block
  6. Container checks nodes/paired.json -> found -> hello-ok
```

## File Format

### nodes/paired.json

```json
{
  "<device_id>": {
    "deviceId": "<device_id>",
    "publicKey": "<base64url-no-pad of raw 32-byte Ed25519 public key>",
    "role": "node",
    "roles": ["node"],
    "scopes": [],
    "approvedScopes": [],
    "createdAtMs": <epoch_ms>,
    "approvedAtMs": <epoch_ms>
  }
}
```

Where `device_id` = `hashlib.sha256(raw_32_byte_public_key).hexdigest()`.

### nodes/.node-device-key.pem

Standard PKCS8 PEM-encoded Ed25519 private key. File ownership set to backend user (not container UID 1000) where possible, though on EFS with access points this may share the same UID.

## Security

- **Trust boundary:** The private key lives on the same EFS as the container's workspace. Since the container already runs arbitrary user code and the node connection grants that container command execution on the user's Mac, the key doesn't expand the trust boundary.
- **Per-user isolation:** Each user gets their own keypair. Compromise of one user's key doesn't affect others.
- **No additional privilege:** The key proves "I am the backend connecting as a node for this user." Trusted-proxy auth (`x-forwarded-user` header) is what actually authenticates the user. The device identity is a structural requirement, not an authorization grant.
- **CVE-2026-32057 compliance:** We use a properly paired device with a real Ed25519 signature, not a bypass or spoof.

## Files to Modify

1. **`core/containers/config.py`** — Add `generate_node_device_identity()` (returns device_id, public_key_b64, private_key_pem) and `build_node_paired_json()` (returns JSON string). Remove `skipDevicePairingForTrustedProxy` from auth config.

2. **`core/containers/ecs_manager.py`** — In `_write_user_configs()`, call the new functions to write `nodes/paired.json` and `nodes/.node-device-key.pem`.

3. **`core/gateway/node_connection.py`** — Replace ephemeral key generation with loading the persistent key from EFS. Accept `efs_mount_path` parameter. `_build_device_identity()` takes a private key + device_id instead of generating fresh ones.

4. **`routers/node_proxy.py`** — Pass EFS mount path to `NodeUpstreamConnection`.

## Idempotency

If `nodes/.node-device-key.pem` already exists on EFS, provisioning reads it and regenerates `nodes/paired.json` from the existing key (preserving the device_id). This handles re-provisioning without breaking an active node connection.
