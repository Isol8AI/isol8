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

Run the re-encryption script with both old and new keys:

```bash
cd apps/backend
OLD_KEY=<old-key> NEW_KEY=<new-key> uv run python scripts/rotate_encryption_key.py
```

### 4. Re-encrypt Gateway Tokens

```bash
cd apps/backend
OLD_KEY=<old-key> NEW_KEY=<new-key> uv run python scripts/backfill_gateway_token_encryption.py
```

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
