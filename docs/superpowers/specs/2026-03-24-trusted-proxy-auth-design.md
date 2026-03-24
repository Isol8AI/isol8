# Switch OpenClaw Gateway Auth to Trusted Proxy

**Date:** 2026-03-24
**Status:** Approved

## Motivation

OpenClaw v2026.3.22+ tightened device pairing enforcement, breaking our Ed25519-based WebSocket handshake (`pairing required`). The device identity flow is complex and fragile. Since the backend is the only thing that can reach user containers (private subnet + security groups), trusted proxy auth is a better fit — OpenClaw trusts the backend's IP and reads user identity from a header.

Also updates `write_openclaw_config()` to match the new OpenClaw plugin-based search config format (`plugins.entries.perplexity` instead of `tools.web.search.perplexity`).

## Changes

### 1. `core/containers/config.py`

- `write_openclaw_config()`: Change `gateway.auth` from `{mode: "token", token: ...}` to `{mode: "trusted-proxy", trustedProxy: {userHeader: "x-forwarded-user"}}`. Add `gateway.trustedProxies: ["10.0.0.0/8"]`.
- Move Perplexity search from `tools.web.search.perplexity` to `plugins.entries.perplexity` format.
- Keep `gateway_token` param — still used as the API key for the search proxy.
- Delete `write_paired_devices_config()` function.
- Remove `from core.containers.device_identity import base64url_encode` import.

### 2. `core/gateway/connection_pool.py`

- Remove all Ed25519 device auth: `_build_device_auth_payload_v3`, `_sign_device_payload`, device identity imports.
- Remove `_device_identities` cache dict and `_get_or_create_device_identity()`.
- Simplify `_handshake()`: send `connect` request with `role`, `scopes`, and no `device` or `auth.token` block. Pass user identity via additional WebSocket headers or in the connect params.
- `GatewayConnection.__init__` no longer takes `device_identity` param — takes `user_id` instead (already has it).
- `_create_connection()` no longer calls `_get_or_create_device_identity()`.

### 3. `core/containers/ecs_manager.py`

- `_write_user_configs()`: Remove `paired.json` write and `device_private_key_pem` DB update.
- Remove `generate_device_identity` import.

### 4. Delete `core/containers/device_identity.py`

Entire file removed — no longer needed.

### 5. Tests

- Update `test_connection_pool.py` handshake tests (no device auth).
- Update `test_config.py` for new auth format and plugin-based search.
- Update `test_ecs_manager.py` — no paired.json write, no device_private_key_pem.
- Delete any device_identity tests.

## What stays the same

- `gateway_token` in DynamoDB container record — used for search proxy auth
- EFS workspace writes (openclaw.json, mcporter.json)
- Container provisioning flow (create service → write config → start)
- Frontend — zero changes
- `device_private_key_pem` field ignored (DynamoDB is schemaless, no migration needed)
