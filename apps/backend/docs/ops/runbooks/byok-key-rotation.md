# BYOK Encryption Key Rotation Runbook

## Overview

User-provided API keys (BYOK) and gateway tokens are encrypted at rest using Fernet symmetric encryption. The master key is stored in AWS Secrets Manager as `ENCRYPTION_KEY`.

## When to Rotate

- Suspected key compromise
- Employee offboarding with key access
- Regular rotation schedule (recommended: quarterly)

## Rotation Procedure

### 1. Generate New Key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. Update Secrets Manager

```bash
aws secretsmanager update-secret \
  --secret-id isol8-dev-encryption-key \
  --secret-string "<new-key>" \
  --profile isol8-admin
```

### 3. Re-encrypt All BYOK Keys

**TODO:** A re-encryption script does not exist yet. Until one is written, re-encrypt manually:

1. Scan the `api-keys` DynamoDB table for all rows
2. For each row: decrypt `encrypted_key` with the OLD Fernet key, re-encrypt with the NEW key, write back
3. This is safe to run multiple times (idempotent — re-encrypting an already-migrated key produces the same result)

```python
# One-off re-encryption snippet (run via uv run python -c "...")
from cryptography.fernet import Fernet
old_f = Fernet(b"<old-key>")
new_f = Fernet(b"<new-key>")
# For each row: new_f.encrypt(old_f.decrypt(row["encrypted_key"].encode()))
```

### 4. Gateway Tokens

Gateway tokens are not currently encrypted at rest (deferred to a future PR using hash-based storage). No re-encryption needed for gateway tokens during key rotation.

### 5. Deploy

Deploy the backend with the new `ENCRYPTION_KEY` environment variable.

### 6. Verify

- Test BYOK key retrieval for a known user
- Verify gateway connections still authenticate
- Check CloudWatch for `byok_decrypt` audit log entries

## Rollback

If the new key causes decryption failures:

1. Revert Secrets Manager to the old key
2. Redeploy the backend
3. Investigate which rows were re-encrypted and may need reversal

## Monitoring

- CloudWatch Insights query for decrypt failures:
  ```
  fields @timestamp, @message
  | filter action = "byok_decrypt"
  | stats count(*) by bin(1h)
  ```
