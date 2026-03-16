
























# Foundation Verification Plan

Date: 2026-02-12

## Purpose

Before expanding OpenClaw features (multi-channel, tool use, etc.), verify the foundational systems work end-to-end on the dev instance:

1. **Memory persistence** — Does OpenClaw remember facts across messages?
2. **Background mode KMS** — Can the enclave decrypt/encrypt state autonomously?
3. **Agent state visibility** — Can we inspect what's inside the encrypted tarballs?

## Prerequisites

- Backend deployed to dev (`api-dev.isol8.co`)
- Enclave running with latest code (including vsock proxy KMS whitelist fix)
- Frontend deployed to dev (`dev.isol8.co`)
- User account with personal encryption set up and unlocked

## Test 1: Memory Persistence (Zero-Trust Mode)

**Goal:** Verify OpenClaw stores and retrieves facts across messages within the same agent.

### Steps

1. Create a new agent named `memory-test` (zero-trust mode, default)
2. Send message: `"My favorite color is purple and I was born in 1990."`
3. Wait for response. Note the response acknowledges the facts.
4. Send message: `"What is my favorite color?"`
5. **Expected:** Agent responds with "purple" (retrieved from memory/session history)
6. Send message: `"Tell me everything you remember about me."`
7. **Expected:** Agent mentions purple and 1990

### What to check if it fails

- Check enclave logs for memory-related errors: `docker logs` or CloudWatch
- Look for `[Bridge]` stderr output mentioning memory search failures
- Check if the embedding model downloaded successfully (first run takes ~830MB)
- Inspect the tarball (see Test 3) for `agents/memory-test/memory/` directory

### Pass criteria

- Agent recalls facts from earlier messages (at minimum from session history)
- No memory-related errors in enclave logs

---

## Test 2: Background Mode End-to-End

**Goal:** Verify background (KMS) encryption mode works for agent state.

### Step 2a: Verify vsock proxy allows KMS

1. SSH into dev EC2 instance
2. Check vsock_proxy.py is running and has KMS domains:
   ```bash
   ps aux | grep vsock_proxy
   # Check logs for "Allowed hosts" line including kms.us-east-1.amazonaws.com
   ```

### Step 2b: Verify KMS_KEY_ID is set in enclave

1. Check enclave environment:
   ```bash
   # The KMS_KEY_ID should be set in the enclave env (from Terraform)
   # Check enclave startup logs for KMS credential initialization
   ```

### Step 2c: Create background mode agent

1. In the frontend, click "New Agent"
2. Select **"Always-on"** encryption mode (background)
3. Name it `bg-test`
4. Send message: `"Hello, I'm testing background mode. My name is Alice."`
5. **Expected:** Agent responds normally (streaming chunks appear)
6. Send message: `"What's my name?"`
7. **Expected:** Agent responds "Alice"

### Step 2d: Verify state persisted with KMS

1. Check backend logs for:
   ```
   Agent state updated for <user_id>/bg-test (mode=background)
   ```
2. In the database, verify the agent_state row:
   ```sql
   SELECT agent_name, encryption_mode, tarball_size_bytes,
          LENGTH(encrypted_tarball) as tarball_len,
          encrypted_dek IS NOT NULL as has_dek
   FROM agent_states
   WHERE agent_name = 'bg-test';
   ```
   - `encryption_mode` should be `background`
   - `encrypted_tarball` should be non-null (JSON KMS envelope)
   - `encrypted_dek` may be null (not currently used, full envelope in tarball)

### Step 2e: Verify enclave KMS decrypt/encrypt

Check enclave logs for:
```
[Enclave] Decrypted state from KMS (N bytes)
[Enclave] Encrypted N bytes with KMS envelope
```

### What to check if it fails

- **403 Forbidden in vsock proxy**: KMS domains not in whitelist (fixed in this PR)
- **"KMS_KEY_ID environment variable required"**: KMS key not configured in enclave env
- **KMS Decrypt fails**: Check KMS key policy allows enclave's IAM role
- **KMS attestation error**: PCR values in KMS policy don't match current enclave build

### Pass criteria

- Background mode agent responds to messages
- State is stored as KMS envelope in DB
- Enclave logs show KMS encrypt/decrypt operations
- Second message can access state from first (enclave decrypted autonomously)

---

## Test 3: Agent State Inspection

**Goal:** Ability to examine what's inside an agent's encrypted tarball.

### Current limitation

There's no API endpoint to inspect agent state contents. For now, use enclave-side debugging:

### Option A: Add diagnostic logging in enclave

After `_unpack_tarball()` in `bedrock_server.py`, the enclave could log directory contents:
```python
# Already exists: state is unpacked to tmpfs_path
# Add temporary diagnostic:
for root, dirs, files in os.walk(tmpfs_path):
    for f in files:
        filepath = os.path.join(root, f)
        size = os.path.getsize(filepath)
        rel = os.path.relpath(filepath, tmpfs_path)
        print(f"[Enclave] Tarball contents: {rel} ({size} bytes)", flush=True)
```

### Option B: Check via database

For zero-trust agents, the state is opaque (encrypted to user key).
For background agents, you can verify the envelope structure:

```sql
-- Check if stored as valid JSON KMS envelope
SELECT
    agent_name,
    encryption_mode,
    CASE
        WHEN encrypted_tarball IS NOT NULL THEN
            (encrypted_tarball::text LIKE '%encrypted_dek%')::text
        ELSE 'no tarball'
    END as is_kms_format
FROM agent_states;
```

### Future: Agent state inspection endpoint

A proper solution would be an endpoint that asks the enclave to decrypt and list the tarball contents (file names and sizes only, not content). This would be useful for debugging memory and session issues.

---

## Test Matrix

| Test | Mode | What it verifies |
|------|------|-----------------|
| 1: Memory | zero_trust | Memory/session persistence within tarball |
| 2: Background | background | KMS envelope encrypt/decrypt, vsock proxy, state round-trip |
| 3: Inspection | both | Ability to debug agent state contents |

## Code Changes in This PR

| File | Change |
|------|--------|
| `enclave/vsock_proxy.py` | Added `kms.us-east-1.amazonaws.com` and `kms.us-west-2.amazonaws.com` to ALLOWED_HOSTS |
| `routers/agents.py` | Fixed GET /agents/{name}/state to return `encryption_mode` without crashing for background mode |
| `routers/websocket_chat.py` | Fixed docstring (s/encrypted_dek/KMS envelope/) |

## Known Risks

1. **Embedding model download** (~830MB) happens synchronously on first agent run. This may cause a timeout on the first message to any agent that triggers memory search.
   - Mitigation: Pre-download in Dockerfile.enclave, or increase timeout for first message.

2. **KMS key policy** must allow the enclave's IAM role and PCR values. If the enclave was rebuilt with new code, PCR values change and KMS operations fail.
   - Mitigation: Update KMS key policy after each enclave rebuild (Terraform manages this).

3. **No graceful degradation** for background mode failures. If KMS is unreachable, the agent message fails entirely.
   - Future: Return error message to user instead of silent failure.
