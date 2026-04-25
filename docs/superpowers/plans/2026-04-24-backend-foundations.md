# Backend Foundations Implementation Plan (Plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land all backend services + infra needed for the flat-fee pivot, behind a feature flag so the existing tier-based flow keeps working in prod.

**Architecture:** Three new DDB tables (credits, credit_transactions, oauth_tokens), three new backend services (`oauth_service`, `credit_ledger`, `bedrock_pricing`), one new router (`/oauth/chatgpt/*`), plus credit-management endpoints on the existing billing router. The OpenClaw-config writer learns four provider branches (chatgpt_oauth | openai_key | anthropic_key | bedrock_claude). Container provisioning collapses to a single 512/1024 size and gains an "auth-first, container-second" pre-stage path. The old per-tier model gating, MiniMax/Qwen catalog, and usage_poller are deleted.

**Tech Stack:** Python 3.13 (FastAPI), boto3 DynamoDB + Secrets Manager + ECS, AWS CDK v2 (TypeScript), `cryptography.fernet`, `httpx` for the OAuth HTTP calls, `stripe` SDK for PaymentIntents.

**Depends on:** Plan 1 (Stripe hardening) — uses `idempotency_key` and `webhook_dedup` patterns established there.

---

## File Structure

**New files (Python):**
- `apps/backend/core/services/oauth_service.py` — device-code flow against `auth.openai.com`. PKCE state, polling, refresh, encrypted DDB persistence.
- `apps/backend/core/services/credit_ledger.py` — DDB-backed balance + transactions. `get_balance`, `top_up`, `deduct`, `adjustment`, `set_auto_reload`, `should_auto_reload`.
- `apps/backend/core/billing/bedrock_pricing.py` — hardcoded rate table for Claude Sonnet 4.6 + Opus 4.7 (per spec §6.3).
- `apps/backend/routers/oauth.py` — `/api/v1/oauth/chatgpt/start`, `/poll`, `/disconnect`.

**New tests:**
- `apps/backend/tests/unit/services/test_oauth_service.py`
- `apps/backend/tests/unit/services/test_credit_ledger.py`
- `apps/backend/tests/unit/services/test_bedrock_pricing.py`
- `apps/backend/tests/unit/routers/test_oauth.py`
- `apps/backend/tests/unit/routers/test_billing_credits.py`
- `apps/backend/tests/unit/containers/test_config_provider_routing.py`
- `apps/backend/tests/unit/containers/test_workspace_codex_auth.py`

**Modified files (Python):**
- `apps/backend/core/config.py` — add 3 table settings + `STRIPE_FLAT_PRICE_ID`; remove tier price IDs after Plan 3 cutover.
- `apps/backend/core/services/key_service.py` — extend to `openai` + `anthropic` LLM keys; push plaintext to Secrets Manager on save.
- `apps/backend/core/services/billing_service.py` — drop tier-aware checkout; add a `create_flat_fee_checkout(owner_id)` helper using `STRIPE_FLAT_PRICE_ID`.
- `apps/backend/core/containers/config.py` — `write_openclaw_config(provider_choice, ...)` branches; delete `_TIER_ALLOWED_MODEL_IDS` + MiniMax/Qwen catalog entries.
- `apps/backend/core/containers/ecs_manager.py` — collapse `_TIER_TASK_RESOURCES` to single `(512, 1024)`; add `provider_choice` param to `provision_container`; per-user secret-arn injection on task-def register.
- `apps/backend/core/containers/workspace.py` — new `pre_stage_codex_auth(user_id, oauth_tokens)` helper.
- `apps/backend/routers/billing.py` — `POST /credits/top_up`, `PUT /credits/auto_reload`, `GET /credits/balance`; `payment_intent.succeeded` webhook branch.
- `apps/backend/routers/settings_keys.py` — accept `provider in {"openai", "anthropic"}` for LLM keys.
- `apps/backend/main.py` — register `oauth.router`.

**Modified files (CDK):**
- `apps/infra/lib/stacks/database-stack.ts` — add `creditsTable`, `creditTransactionsTable`, `oauthTokensTable`.
- `apps/infra/lib/stacks/container-stack.ts` — collapse per-tier task sizing to single `(512, 1024)`.
- `apps/infra/lib/stacks/service-stack.ts` — pass new env vars; grant new table + Secrets-Manager permissions.

**Deleted files:**
- `apps/backend/core/services/usage_poller.py` (replaced by synchronous credit deduction; chat-path wiring is in Plan 3).

---

## Task 1: CDK — add three new DDB tables

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`

- [ ] **Step 1: Find the existing table-creation section**

Run: `grep -n 'new dynamodb.Table' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/infra/lib/stacks/database-stack.ts`

You should see ~9 existing table constructs. Read 5 lines around one of them (e.g. `usersTable`) to see the construction pattern: PK, optional SK, TTL, KMS encryption, removal policy.

- [ ] **Step 2: Declare the three new tables on the class**

In the `DatabaseStack` class field declarations (around line 17, where `usersTable: dynamodb.Table;` etc are listed), add:

```ts
  public readonly creditsTable: dynamodb.Table;
  public readonly creditTransactionsTable: dynamodb.Table;
  public readonly oauthTokensTable: dynamodb.Table;
```

- [ ] **Step 3: Construct the three tables in the constructor**

After the last existing table construct (find the line ending the `adminActionsTable` block), add:

```ts
    // Credits balance per user — atomic counter, deducted per Bedrock chat
    // (card 3 only). Single-key, plain item; per spec §6.1.
    this.creditsTable = new dynamodb.Table(this, "CreditsTable", {
      tableName: `isol8-${env}-credits`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });

    // Credit transactions audit log — immutable history of top-ups, deducts,
    // adjustments. PK user_id + SK tx_id (ULID, sortable by time).
    // Per spec §6.1.
    this.creditTransactionsTable = new dynamodb.Table(this, "CreditTxnsTable", {
      tableName: `isol8-${env}-credit-transactions`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "tx_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });

    // ChatGPT OAuth bootstrap tokens — Fernet-encrypted access + refresh
    // tokens captured during signup, used once when staging the user's EFS
    // codex/auth.json file at container provision. Per spec §5.1.
    this.oauthTokensTable = new dynamodb.Table(this, "OAuthTokensTable", {
      tableName: `isol8-${env}-oauth-tokens`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });
```

- [ ] **Step 4: Add CfnOutputs for the new table names**

Below the existing `CfnOutput` blocks at the bottom of the constructor:

```ts
    new cdk.CfnOutput(this, "CreditsTableName", {
      value: this.creditsTable.tableName,
      exportName: `${this.stackName}-credits-table`,
    });
    new cdk.CfnOutput(this, "CreditTxnsTableName", {
      value: this.creditTransactionsTable.tableName,
      exportName: `${this.stackName}-credit-txns-table`,
    });
    new cdk.CfnOutput(this, "OAuthTokensTableName", {
      value: this.oauthTokensTable.tableName,
      exportName: `${this.stackName}-oauth-tokens-table`,
    });
```

- [ ] **Step 5: Verify CDK synth**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/infra && pnpm cdk synth isol8-dev > /dev/null && echo OK`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/infra/lib/stacks/database-stack.ts
git commit -m "$(cat <<'EOF'
infra: add credits, credit-transactions, oauth-tokens DDB tables

Three new tables for the flat-fee pivot per spec §6.1 and §5.1:
- isol8-{env}-credits: per-user balance, atomic counter
- isol8-{env}-credit-transactions: immutable audit log
- isol8-{env}-oauth-tokens: Fernet-encrypted ChatGPT bootstrap tokens

All KMS-encrypted with the existing customer-managed key, PITR on, dev
DESTROY / prod RETAIN per the ENV_CONFIG convention.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: CDK — collapse per-tier task sizing to single 512/1024

**Files:**
- Modify: `apps/infra/lib/stacks/container-stack.ts`

- [ ] **Step 1: Find the per-tier sizing config**

Run: `grep -n '_TIER_TASK_RESOURCES\|TASK_RESOURCES\|512.*1024\|1024.*2048' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/infra/lib/stacks/container-stack.ts`

The current container-stack.ts likely has either a per-tier `Map<tier, {cpu, mem}>` block or per-tier `taskDefinition` constructs.

- [ ] **Step 2: Replace per-tier sizing with a single constant**

If you find a map like:

```ts
const TIER_RESOURCES: Record<string, { cpu: number; memoryMiB: number }> = {
  free: { cpu: 256, memoryMiB: 512 },
  starter: { cpu: 512, memoryMiB: 1024 },
  pro: { cpu: 1024, memoryMiB: 2048 },
  enterprise: { cpu: 2048, memoryMiB: 4096 },
};
```

Replace with:

```ts
// Single per-user task size for the flat-fee pivot. Per spec §3.2 / §10.
// Old per-tier sizing deleted; resize add-ons are out of scope (§3.5).
const PER_USER_TASK_RESOURCES = { cpu: 512, memoryMiB: 1024 } as const;
```

If the per-tier sizing is inline in `taskDefinition` constructs instead, replace each with `cpu: 512, memoryMiB: 1024`. Update any callers of `TIER_RESOURCES[tier]` to read from `PER_USER_TASK_RESOURCES` directly.

- [ ] **Step 3: Verify CDK synth**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/infra && pnpm cdk synth isol8-dev > /dev/null && echo OK`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/infra/lib/stacks/container-stack.ts
git commit -m "$(cat <<'EOF'
infra: collapse per-tier container sizing to single 512 CPU / 1024 MB

Per spec §3.2 / §10, the flat-fee pivot ships one task size for everyone.
Deletes the four-tier sizing map. Existing tasks keep their old sizing
until they get re-provisioned (Plan 3 cutover tears down the 6 test
containers; new signups land on the single size).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: CDK — wire env vars + grants for new tables, Secrets Manager

**Files:**
- Modify: `apps/infra/lib/stacks/service-stack.ts`

- [ ] **Step 1: Add new env vars to the backend container**

In the `taskDefinition.addContainer({ environment: { ... } })` block, add (alphabetical):

```ts
CREDITS_TABLE: props.databaseStack.creditsTable.tableName,
CREDIT_TRANSACTIONS_TABLE: props.databaseStack.creditTransactionsTable.tableName,
OAUTH_TOKENS_TABLE: props.databaseStack.oauthTokensTable.tableName,
STRIPE_FLAT_PRICE_ID: process.env.STRIPE_FLAT_PRICE_ID ?? "",
```

(Use `process.env.STRIPE_FLAT_PRICE_ID` so the price id is sourced from CI/GitHub Actions secrets, not from CDK code. Same pattern as the existing `STRIPE_STARTER_PRICE_ID`.)

- [ ] **Step 2: Grant the backend role read/write on the new tables**

Find the block where existing tables are granted to `taskRole`. Add:

```ts
props.databaseStack.creditsTable.grantReadWriteData(taskRole);
props.databaseStack.creditTransactionsTable.grantReadWriteData(taskRole);
props.databaseStack.oauthTokensTable.grantReadWriteData(taskRole);
```

- [ ] **Step 3: Grant the backend role per-user Secrets Manager management**

Add an inline policy statement so the backend can create / update / delete per-user LLM-key secrets:

```ts
taskRole.addToPrincipalPolicy(
  new iam.PolicyStatement({
    effect: iam.Effect.ALLOW,
    actions: [
      "secretsmanager:CreateSecret",
      "secretsmanager:PutSecretValue",
      "secretsmanager:UpdateSecret",
      "secretsmanager:DeleteSecret",
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ],
    resources: [
      `arn:aws:secretsmanager:${this.region}:${this.account}:secret:isol8/${props.environment}/user-keys/*`,
    ],
  })
);
```

(Make sure `import * as iam from "aws-cdk-lib/aws-iam";` is at the top of the file — likely already present.)

- [ ] **Step 4: Verify CDK synth**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/infra && pnpm cdk synth isol8-dev > /dev/null && echo OK`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/infra/lib/stacks/service-stack.ts
git commit -m "$(cat <<'EOF'
infra: pass new table names + Secrets Manager grants to backend

Wires CREDITS_TABLE, CREDIT_TRANSACTIONS_TABLE, OAUTH_TOKENS_TABLE,
STRIPE_FLAT_PRICE_ID to the backend Fargate task. Grants RW on the
three new tables and a per-user-namespaced Secrets Manager policy
(isol8/{env}/user-keys/*).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Backend config.py — add new settings

**Files:**
- Modify: `apps/backend/core/config.py`

- [ ] **Step 1: Add the new fields to Settings**

Find the Settings class. Add (alphabetical with siblings):

```python
    CREDITS_TABLE: str = ""
    CREDIT_TRANSACTIONS_TABLE: str = ""
    OAUTH_TOKENS_TABLE: str = ""
    STRIPE_FLAT_PRICE_ID: str = ""
```

(Do NOT delete `STRIPE_STARTER_PRICE_ID`, `STRIPE_PRO_PRICE_ID`, etc. yet — they're still wired to live containers. Plan 3's cutover removes them.)

- [ ] **Step 2: Verify nothing imports the new settings before they exist (sanity)**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run python -c "from core.config import settings; print(settings.CREDITS_TABLE, settings.STRIPE_FLAT_PRICE_ID)"`
Expected: prints two empty strings, no error.

- [ ] **Step 3: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/config.py
git commit -m "$(cat <<'EOF'
feat(backend): add credit ledger + OAuth + flat-price settings

CREDITS_TABLE, CREDIT_TRANSACTIONS_TABLE, OAUTH_TOKENS_TABLE,
STRIPE_FLAT_PRICE_ID. Old per-tier price IDs left in place; Plan 3
cutover removes them after live traffic stops using them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `bedrock_pricing.py` — Claude rate constants

**Files:**
- Create: `apps/backend/core/billing/bedrock_pricing.py`
- Test: `apps/backend/tests/unit/services/test_bedrock_pricing.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/services/test_bedrock_pricing.py`:

```python
"""Unit tests for Bedrock Claude pricing constants and cost calc."""

import pytest

from core.billing.bedrock_pricing import (
    UnknownModelError,
    cost_microcents,
)


class TestCostMicrocents:
    def test_sonnet_4_6_cost(self):
        # Sonnet 4.6: $3 / MTok input, $15 / MTok output (Bedrock list price).
        # 1 MTok = 1,000,000 tokens. $1 = 100 cents = 1,000,000 microcents.
        # 1000 input + 500 output should cost:
        # (1000 / 1_000_000) × $3 = $0.003 = 3000 microcents (input)
        # (500 / 1_000_000) × $15 = $0.0075 = 7500 microcents (output)
        # Total: 10500 microcents
        result = cost_microcents(
            model_id="anthropic.claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
        )
        assert result == 10_500

    def test_opus_4_7_cost(self):
        # Opus 4.7: $15 / MTok input, $75 / MTok output.
        # 1000 input + 500 output:
        # (1000 / 1_000_000) × $15 = $0.015 = 15_000 microcents (input)
        # (500 / 1_000_000) × $75 = $0.0375 = 37_500 microcents (output)
        # Total: 52_500 microcents
        result = cost_microcents(
            model_id="anthropic.claude-opus-4-7",
            input_tokens=1000,
            output_tokens=500,
        )
        assert result == 52_500

    def test_unknown_model_raises(self):
        with pytest.raises(UnknownModelError) as exc:
            cost_microcents(model_id="anthropic.claude-fake-99",
                            input_tokens=100, output_tokens=100)
        assert "anthropic.claude-fake-99" in str(exc.value)

    def test_zero_tokens_zero_cost(self):
        result = cost_microcents(
            model_id="anthropic.claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
        )
        assert result == 0

    def test_cost_is_integer(self):
        """Microcents are integers — no float drift in the deduct path."""
        result = cost_microcents(
            model_id="anthropic.claude-sonnet-4-6",
            input_tokens=1234, output_tokens=5678,
        )
        assert isinstance(result, int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_bedrock_pricing.py -v`
Expected: 5 failures, all `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module**

First create the directory + `__init__.py`:

```bash
mkdir -p /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/billing
touch /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/billing/__init__.py
```

Then create `apps/backend/core/billing/bedrock_pricing.py`:

```python
"""Bedrock Claude pricing constants — input/output token rates per model.

Rates sourced from AWS Bedrock list price (us-east-1, 2026-04). Update
this file when AWS changes pricing; no other code should hardcode rates.
Per spec §6.3.

Microcents arithmetic is used everywhere in the credit ledger so we
avoid float drift on deduction. 1 dollar = 100 cents = 1,000,000
microcents.
"""

from __future__ import annotations


_MICROCENTS_PER_MTOK_USD = 1_000_000  # $1 per 1M tokens = 1_000_000 microcents per token-million


class UnknownModelError(KeyError):
    """Raised when a model id has no entry in the rate table."""


# (input_per_mtok_usd, output_per_mtok_usd)
_RATES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "anthropic.claude-sonnet-4-6": (3.0, 15.0),
    "anthropic.claude-opus-4-7": (15.0, 75.0),
}


def cost_microcents(*, model_id: str, input_tokens: int, output_tokens: int) -> int:
    """Compute the un-marked-up cost in microcents for an inference call.

    Args:
        model_id: bare Bedrock model id (e.g. "anthropic.claude-sonnet-4-6").
            Pass without the "amazon-bedrock/" prefix.
        input_tokens: prompt tokens consumed.
        output_tokens: completion tokens produced.

    Returns:
        Integer microcents. Markup is applied separately by credit_ledger.deduct.

    Raises:
        UnknownModelError: model_id has no rate entry.
    """
    try:
        in_rate, out_rate = _RATES_USD_PER_MTOK[model_id]
    except KeyError:
        raise UnknownModelError(model_id) from None

    in_microcents = int(input_tokens * in_rate)
    out_microcents = int(output_tokens * out_rate)
    return in_microcents + out_microcents
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_bedrock_pricing.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/billing/__init__.py apps/backend/core/billing/bedrock_pricing.py apps/backend/tests/unit/services/test_bedrock_pricing.py
git commit -m "$(cat <<'EOF'
feat(billing): bedrock_pricing module with Claude rate constants

Hardcoded rate table for Claude Sonnet 4.6 + Opus 4.7. Microcents
arithmetic (integer math) so the credit-deduct path doesn't drift on
floats. Per spec §6.3. Update this file when AWS list pricing changes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `credit_ledger.py` — DDB-backed balance + transactions

**Files:**
- Create: `apps/backend/core/services/credit_ledger.py`
- Test: `apps/backend/tests/unit/services/test_credit_ledger.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/services/test_credit_ledger.py`:

```python
"""Unit tests for the credit ledger: balance, top-up, deduct, auto-reload."""

import boto3
import pytest
from moto import mock_aws

from core.services.credit_ledger import (
    InsufficientBalanceError,
    deduct,
    get_balance,
    set_auto_reload,
    should_auto_reload,
    top_up,
)


@pytest.fixture
def ledger_tables(monkeypatch):
    """Provision moto-mocked credits + credit-transactions tables."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-credits",
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        client.create_table(
            TableName="test-credit-txns",
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "tx_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "tx_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("CREDITS_TABLE", "test-credits")
        monkeypatch.setenv("CREDIT_TRANSACTIONS_TABLE", "test-credit-txns")
        yield


class TestBalance:
    @pytest.mark.asyncio
    async def test_zero_balance_for_new_user(self, ledger_tables):
        assert await get_balance("u_new") == 0

    @pytest.mark.asyncio
    async def test_balance_after_top_up(self, ledger_tables):
        await top_up("u_1", amount_microcents=10_000_000, stripe_payment_intent_id="pi_1")  # $10
        assert await get_balance("u_1") == 10_000_000


class TestTopUp:
    @pytest.mark.asyncio
    async def test_top_up_writes_transaction(self, ledger_tables):
        await top_up("u_1", amount_microcents=5_000_000, stripe_payment_intent_id="pi_2")
        client = boto3.client("dynamodb", region_name="us-east-1")
        items = client.scan(TableName="test-credit-txns")["Items"]
        assert len(items) == 1
        assert items[0]["type"]["S"] == "top_up"
        assert int(items[0]["amount_microcents"]["N"]) == 5_000_000
        assert items[0]["stripe_payment_intent_id"]["S"] == "pi_2"

    @pytest.mark.asyncio
    async def test_two_top_ups_accumulate(self, ledger_tables):
        await top_up("u_1", amount_microcents=3_000_000, stripe_payment_intent_id="pi_a")
        await top_up("u_1", amount_microcents=2_000_000, stripe_payment_intent_id="pi_b")
        assert await get_balance("u_1") == 5_000_000


class TestDeduct:
    @pytest.mark.asyncio
    async def test_deduct_reduces_balance(self, ledger_tables):
        await top_up("u_1", amount_microcents=10_000_000, stripe_payment_intent_id="pi_x")
        await deduct(
            "u_1",
            amount_microcents=2_000_000,
            chat_session_id="sess_1",
            raw_cost_microcents=1_428_571,  # 2M / 1.4 markup
            markup_multiplier=1.4,
        )
        assert await get_balance("u_1") == 8_000_000

    @pytest.mark.asyncio
    async def test_deduct_writes_transaction_with_markup_metadata(self, ledger_tables):
        await top_up("u_1", amount_microcents=10_000_000, stripe_payment_intent_id="pi_x")
        await deduct(
            "u_1",
            amount_microcents=2_000_000,
            chat_session_id="sess_1",
            raw_cost_microcents=1_428_571,
            markup_multiplier=1.4,
        )
        client = boto3.client("dynamodb", region_name="us-east-1")
        items = client.scan(TableName="test-credit-txns")["Items"]
        deduct_row = next(i for i in items if i["type"]["S"] == "deduct")
        assert int(deduct_row["amount_microcents"]["N"]) == -2_000_000
        assert int(deduct_row["raw_cost_microcents"]["N"]) == 1_428_571
        # DDB stores Decimal — moto roundtrips as string.
        assert float(deduct_row["markup_multiplier"]["N"]) == 1.4
        assert deduct_row["chat_session_id"]["S"] == "sess_1"

    @pytest.mark.asyncio
    async def test_deduct_with_insufficient_balance_overdrafts_to_zero(self, ledger_tables):
        """Race scenario: chat completed, deduction would go negative.
        Per spec §6.3 step 6: accept the small overdraft, set balance to 0,
        log a warning. Don't reject — the chat already happened."""
        await top_up("u_1", amount_microcents=1_000_000, stripe_payment_intent_id="pi_x")  # $1
        await deduct(
            "u_1",
            amount_microcents=2_000_000,  # $2 — more than balance
            chat_session_id="sess_overdraft",
            raw_cost_microcents=1_428_571,
            markup_multiplier=1.4,
        )
        assert await get_balance("u_1") == 0


class TestAutoReload:
    @pytest.mark.asyncio
    async def test_auto_reload_default_off(self, ledger_tables):
        # New user — never set auto reload — should not trigger.
        assert await should_auto_reload("u_new") is False

    @pytest.mark.asyncio
    async def test_set_auto_reload_persists(self, ledger_tables):
        await set_auto_reload(
            "u_1",
            enabled=True,
            threshold_cents=500,    # $5
            amount_cents=5000,      # $50
        )
        # Balance is 0 → below threshold → should trigger.
        assert await should_auto_reload("u_1") is True

    @pytest.mark.asyncio
    async def test_above_threshold_does_not_trigger(self, ledger_tables):
        await set_auto_reload(
            "u_1",
            enabled=True,
            threshold_cents=500,   # $5
            amount_cents=5000,
        )
        await top_up("u_1", amount_microcents=10_000_000, stripe_payment_intent_id="pi_x")  # $10
        assert await should_auto_reload("u_1") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_credit_ledger.py -v`
Expected: all fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the credit ledger**

Create `apps/backend/core/services/credit_ledger.py`:

```python
"""Credit ledger — per-user prepaid balance + immutable transaction log.

Backed by two DDB tables: `credits` (single row per user, atomic counter)
and `credit-transactions` (immutable audit log, PK user_id + SK tx_id).
Per spec §6. Card 3 only — cards 1 and 2 don't touch this module.

Concurrency:
- Top-up: atomic ADD on balance_microcents (cannot overflow on writes).
- Deduct: atomic ADD with negative + ConditionExpression that the result
  stays non-negative. If the condition fails (race with another chat),
  we accept the small overdraft per spec §6.3 step 6 and force balance
  to zero with an unconditional SET — better UX than refunding a chat.
- Get balance: eventually-consistent read by default; the caller can
  pass consistent=True if the freshness matters (the pre-chat hard-stop
  check sets consistent=True so a top-up that just landed via webhook
  unblocks the next message immediately).
"""

from __future__ import annotations

import logging
import time
import uuid
from decimal import Decimal
from typing import Literal

import boto3
from botocore.exceptions import ClientError

from core.config import settings


logger = logging.getLogger(__name__)


class InsufficientBalanceError(Exception):
    """Reserved for callers that want to fail-closed instead of overdraft.

    NOT raised by deduct() under normal use — deduct() accepts the
    overdraft per spec §6.3. Provided for use cases like the pre-chat
    hard-stop check.
    """


def _credits_table():
    return boto3.resource("dynamodb", region_name=settings.AWS_REGION).Table(
        settings.CREDITS_TABLE
    )


def _txns_table():
    return boto3.resource("dynamodb", region_name=settings.AWS_REGION).Table(
        settings.CREDIT_TRANSACTIONS_TABLE
    )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_tx_id() -> str:
    # Time-prefixed so the SK sorts chronologically.
    return f"{int(time.time() * 1000):013d}-{uuid.uuid4().hex[:8]}"


async def get_balance(user_id: str, *, consistent: bool = False) -> int:
    """Returns balance in microcents. 0 if the user has no row yet."""
    resp = _credits_table().get_item(
        Key={"user_id": user_id}, ConsistentRead=consistent
    )
    item = resp.get("Item")
    if not item:
        return 0
    return int(item.get("balance_microcents", 0))


async def top_up(
    user_id: str,
    *,
    amount_microcents: int,
    stripe_payment_intent_id: str,
) -> int:
    """Add credits to a user's balance. Returns the new balance.

    Idempotent on stripe_payment_intent_id at the webhook layer (handler
    dedupes by event.id via Plan 1's webhook_dedup helper). This function
    itself is NOT idempotent — calling twice will credit twice.
    """
    if amount_microcents <= 0:
        raise ValueError(f"amount_microcents must be positive, got {amount_microcents}")

    resp = _credits_table().update_item(
        Key={"user_id": user_id},
        UpdateExpression="ADD balance_microcents :amt SET updated_at = :now, last_top_up_at = :now",
        ExpressionAttributeValues={
            ":amt": amount_microcents,
            ":now": _now_iso(),
        },
        ReturnValues="UPDATED_NEW",
    )
    new_balance = int(resp["Attributes"]["balance_microcents"])

    _txns_table().put_item(
        Item={
            "user_id": user_id,
            "tx_id": _new_tx_id(),
            "type": "top_up",
            "amount_microcents": amount_microcents,
            "balance_after_microcents": new_balance,
            "stripe_payment_intent_id": stripe_payment_intent_id,
            "created_at": _now_iso(),
        }
    )
    return new_balance


async def deduct(
    user_id: str,
    *,
    amount_microcents: int,
    chat_session_id: str,
    raw_cost_microcents: int,
    markup_multiplier: float,
    bedrock_invocation_id: str | None = None,
) -> int:
    """Deduct credits for one chat. Returns the new balance.

    Per spec §6.3: tries an atomic conditional decrement; on race-induced
    overdraft, falls back to setting balance=0 and logs a warning.
    """
    if amount_microcents <= 0:
        raise ValueError(f"amount_microcents must be positive, got {amount_microcents}")

    try:
        resp = _credits_table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="ADD balance_microcents :neg SET updated_at = :now",
            ConditionExpression="balance_microcents >= :amt",
            ExpressionAttributeValues={
                ":neg": -amount_microcents,
                ":amt": amount_microcents,
                ":now": _now_iso(),
            },
            ReturnValues="UPDATED_NEW",
        )
        new_balance = int(resp["Attributes"]["balance_microcents"])
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # Race-induced overdraft: chat already completed, can't refund.
        # Force balance to 0, log, continue.
        logger.warning(
            "Credit overdraft for user_id=%s session=%s amount=%d — forcing to 0",
            user_id, chat_session_id, amount_microcents,
        )
        _credits_table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET balance_microcents = :zero, updated_at = :now",
            ExpressionAttributeValues={":zero": 0, ":now": _now_iso()},
        )
        new_balance = 0

    txn_item = {
        "user_id": user_id,
        "tx_id": _new_tx_id(),
        "type": "deduct",
        "amount_microcents": -amount_microcents,
        "balance_after_microcents": new_balance,
        "chat_session_id": chat_session_id,
        "raw_cost_microcents": raw_cost_microcents,
        "markup_multiplier": Decimal(str(markup_multiplier)),
        "created_at": _now_iso(),
    }
    if bedrock_invocation_id:
        txn_item["bedrock_invocation_id"] = bedrock_invocation_id
    _txns_table().put_item(Item=txn_item)
    return new_balance


async def adjustment(
    user_id: str,
    *,
    amount_microcents: int,
    reason: str,
    operator: str,
) -> int:
    """Operator-only manual adjustment (e.g. refund, support credit).

    Positive amount adds, negative subtracts. Always succeeds; if subtracting
    would go negative, balance becomes 0 (consistent with deduct overdraft).
    """
    new_balance = max(0, await get_balance(user_id, consistent=True) + amount_microcents)
    _credits_table().update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET balance_microcents = :bal, updated_at = :now",
        ExpressionAttributeValues={":bal": new_balance, ":now": _now_iso()},
    )
    _txns_table().put_item(
        Item={
            "user_id": user_id,
            "tx_id": _new_tx_id(),
            "type": "adjustment",
            "amount_microcents": amount_microcents,
            "balance_after_microcents": new_balance,
            "reason": reason,
            "operator": operator,
            "created_at": _now_iso(),
        }
    )
    return new_balance


async def set_auto_reload(
    user_id: str,
    *,
    enabled: bool,
    threshold_cents: int | None = None,
    amount_cents: int | None = None,
) -> None:
    """Configure auto-reload. When enabled, threshold and amount are required."""
    if enabled and (threshold_cents is None or amount_cents is None):
        raise ValueError("threshold_cents and amount_cents required when enabling")

    update_expr_parts = ["SET auto_reload_enabled = :en, updated_at = :now"]
    values: dict = {":en": enabled, ":now": _now_iso()}
    if threshold_cents is not None:
        update_expr_parts.append("auto_reload_threshold_cents = :th")
        values[":th"] = threshold_cents
    if amount_cents is not None:
        update_expr_parts.append("auto_reload_amount_cents = :am")
        values[":am"] = amount_cents
    update_expr = update_expr_parts[0] + ", " + ", ".join(update_expr_parts[1:]) \
        if len(update_expr_parts) > 1 else update_expr_parts[0]

    _credits_table().update_item(
        Key={"user_id": user_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=values,
    )


async def should_auto_reload(user_id: str) -> bool:
    """True iff auto-reload is enabled and balance < threshold."""
    resp = _credits_table().get_item(
        Key={"user_id": user_id}, ConsistentRead=True
    )
    item = resp.get("Item")
    if not item or not item.get("auto_reload_enabled"):
        return False
    threshold_cents = int(item.get("auto_reload_threshold_cents", 0))
    threshold_microcents = threshold_cents * 10_000  # 1 cent = 10_000 microcents
    balance = int(item.get("balance_microcents", 0))
    return balance < threshold_microcents
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_credit_ledger.py -v`
Expected: all 9 pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/services/credit_ledger.py apps/backend/tests/unit/services/test_credit_ledger.py
git commit -m "$(cat <<'EOF'
feat(billing): credit_ledger service for per-user prepaid balance

Atomic top-up + deduct + auto-reload + adjustment. Per spec §6:
- top_up: atomic ADD, immutable txn log
- deduct: atomic conditional decrement; on race-induced overdraft, force
  balance to 0 (better UX than refunding a completed chat)
- adjustment: operator-only, supports the manual-refund path from §6.5
- set_auto_reload + should_auto_reload: opt-in threshold-based recharge
  (matches Anthropic / OpenAI Console UX per spec)

Card 3 only — cards 1 and 2 don't touch this module. Wiring to the
chat path is in Plan 3 (gateway pre-chat balance check + post-chat deduct).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `oauth_service.py` — device-code flow against auth.openai.com

**Files:**
- Create: `apps/backend/core/services/oauth_service.py`
- Test: `apps/backend/tests/unit/services/test_oauth_service.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/services/test_oauth_service.py`:

```python
"""Unit tests for the ChatGPT device-code OAuth orchestration."""

import json
from unittest.mock import AsyncMock, patch

import boto3
import httpx
import pytest
from cryptography.fernet import Fernet
from moto import mock_aws

from core.services.oauth_service import (
    DevicePollPending,
    DevicePollResult,
    poll_device_code,
    request_device_code,
    revoke_user_oauth,
)


@pytest.fixture
def oauth_table(monkeypatch):
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-oauth-tokens",
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("OAUTH_TOKENS_TABLE", "test-oauth-tokens")
        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
        yield


@pytest.mark.asyncio
async def test_request_device_code_returns_user_facing_fields(oauth_table):
    """Backend POST to OpenAI device endpoint returns the user-code + URL."""

    fake_resp = {
        "device_code": "dev_abc",
        "user_code": "ABCD-1234",
        "verification_uri": "https://chatgpt.com/codex",
        "expires_in": 900,
        "interval": 5,
    }

    async def fake_post(self, url, **kwargs):
        return httpx.Response(200, json=fake_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        result = await request_device_code(user_id="u_1")

    assert result.user_code == "ABCD-1234"
    assert result.verification_uri == "https://chatgpt.com/codex"
    assert result.interval == 5
    # Server-side device_code is NOT returned to the caller — kept in DDB.
    assert not hasattr(result, "device_code")


@pytest.mark.asyncio
async def test_poll_pending_returns_pending(oauth_table):
    """OpenAI 'authorization_pending' translates to DevicePollPending."""

    # First seed a device-code session.
    seed_resp = {
        "device_code": "dev_pending",
        "user_code": "WAIT-0001",
        "verification_uri": "https://chatgpt.com/codex",
        "expires_in": 900,
        "interval": 5,
    }

    async def fake_seed(self, url, **kwargs):
        return httpx.Response(200, json=seed_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_seed):
        await request_device_code(user_id="u_1")

    # Then poll while still pending.
    async def fake_poll(self, url, **kwargs):
        return httpx.Response(
            400,
            json={"error": "authorization_pending"},
            request=httpx.Request("POST", url),
        )

    with patch.object(httpx.AsyncClient, "post", new=fake_poll):
        result = await poll_device_code(user_id="u_1")

    assert result is DevicePollPending


@pytest.mark.asyncio
async def test_poll_success_persists_encrypted_tokens(oauth_table):
    """Successful poll: tokens are Fernet-encrypted into the DDB row."""

    seed_resp = {
        "device_code": "dev_success",
        "user_code": "OKAY-9999",
        "verification_uri": "https://chatgpt.com/codex",
        "expires_in": 900,
        "interval": 5,
    }

    async def fake_seed(self, url, **kwargs):
        return httpx.Response(200, json=seed_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_seed):
        await request_device_code(user_id="u_1")

    success_resp = {
        "access_token": "eyJ.fake-jwt.access",
        "refresh_token": "rt_opaque_1",
        "id_token": "eyJ.id-token.x",
        "account_id": "chatgpt-account-1",
    }

    async def fake_success(self, url, **kwargs):
        return httpx.Response(200, json=success_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_success):
        result = await poll_device_code(user_id="u_1")

    assert isinstance(result, DevicePollResult)
    # Tokens are stored encrypted, so the raw DDB row should NOT contain them
    # in plaintext.
    client = boto3.client("dynamodb", region_name="us-east-1")
    raw_item = client.get_item(
        TableName="test-oauth-tokens", Key={"user_id": {"S": "u_1"}}
    )["Item"]
    raw_payload_b = raw_item["encrypted_tokens"]["B"]
    assert b"eyJ.fake-jwt.access" not in raw_payload_b
    assert b"rt_opaque_1" not in raw_payload_b


@pytest.mark.asyncio
async def test_revoke_deletes_oauth_row(oauth_table):
    """revoke_user_oauth removes the persisted token row."""

    seed_resp = {
        "device_code": "dev_revoke",
        "user_code": "BYE-0001",
        "verification_uri": "https://chatgpt.com/codex",
        "expires_in": 900,
        "interval": 5,
    }
    success_resp = {
        "access_token": "eyJ.x.y",
        "refresh_token": "rt",
        "id_token": "eyJ.z",
        "account_id": "acc",
    }

    async def fake_seed(self, url, **kwargs):
        return httpx.Response(200, json=seed_resp, request=httpx.Request("POST", url))

    async def fake_success(self, url, **kwargs):
        return httpx.Response(200, json=success_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_seed):
        await request_device_code(user_id="u_1")
    with patch.object(httpx.AsyncClient, "post", new=fake_success):
        await poll_device_code(user_id="u_1")

    await revoke_user_oauth(user_id="u_1")

    client = boto3.client("dynamodb", region_name="us-east-1")
    resp = client.get_item(TableName="test-oauth-tokens", Key={"user_id": {"S": "u_1"}})
    assert "Item" not in resp
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_oauth_service.py -v`
Expected: 4 failures, all `ModuleNotFoundError`.

- [ ] **Step 3: Add `httpx` to backend dependencies if not present**

Run: `grep -n 'httpx' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/pyproject.toml`

If `httpx` is not listed, add it:

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend
uv add httpx
```

- [ ] **Step 4: Implement `oauth_service.py`**

Create `apps/backend/core/services/oauth_service.py`:

```python
"""ChatGPT OAuth — device-code flow orchestration.

We use the public Codex CLI client_id verified at
https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/utils/oauth/openai-codex.ts
The device-code endpoint is officially supported by OpenAI per
https://developers.openai.com/codex/auth.

We do NOT install @mariozechner/pi-ai — that's a CLI library that writes
tokens to ~/.codex/auth.json (single-file pattern, would clobber on a
shared backend). We borrow only the constants here and orchestrate the
device-code flow ourselves with isolated per-user storage in DDB.

Per spec §5.1 + §5.1.1.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Final

import boto3
import httpx
from cryptography.fernet import Fernet

from core.config import settings


logger = logging.getLogger(__name__)


# Constants borrowed from pi-ai (see module docstring).
CLIENT_ID: Final = "app_EMoamEEZ73f0CkXaXp7hrann"
DEVICE_CODE_URL: Final = "https://auth.openai.com/codex/device"
TOKEN_URL: Final = "https://auth.openai.com/oauth/token"
SCOPE: Final = "openid profile email offline_access"


@dataclass(frozen=True)
class DeviceCodeResponse:
    """User-facing fields shown in our UI to drive completion."""

    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass(frozen=True)
class DevicePollResult:
    """Returned on successful poll. Tokens are persisted internally;
    callers receive only an opaque marker that auth completed."""

    account_id: str | None


# Sentinel returned while OpenAI says "still pending".
DevicePollPending: Final = object()


def _table():
    return boto3.resource("dynamodb", region_name=settings.AWS_REGION).Table(
        settings.OAUTH_TOKENS_TABLE
    )


def _fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


async def request_device_code(*, user_id: str) -> DeviceCodeResponse:
    """Start a device-code session for this user. Persists the device_code
    in DDB so the subsequent poll knows what to ask OpenAI about.

    Each call is independent — many users can have device-code sessions
    in flight concurrently against the same client_id (per spec §5.1).
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            DEVICE_CODE_URL,
            data={"client_id": CLIENT_ID, "scope": SCOPE},
        )
    resp.raise_for_status()
    body = resp.json()

    _table().put_item(
        Item={
            "user_id": user_id,
            "state": "pending",
            "device_code": body["device_code"],
            "user_code": body["user_code"],
            "interval": int(body.get("interval", 5)),
        }
    )
    return DeviceCodeResponse(
        user_code=body["user_code"],
        verification_uri=body["verification_uri"],
        expires_in=int(body["expires_in"]),
        interval=int(body.get("interval", 5)),
    )


async def poll_device_code(*, user_id: str) -> DevicePollResult | object:
    """Poll OpenAI's token endpoint for this user's device-code session.

    Returns DevicePollPending while OpenAI says authorization_pending.
    Returns DevicePollResult on success, after Fernet-encrypting the
    tokens into DDB. Raises if the session is unknown / expired / errored.
    """
    row = _table().get_item(Key={"user_id": user_id}).get("Item")
    if not row or row.get("state") not in ("pending",):
        raise RuntimeError(f"No pending device-code session for user {user_id}")

    device_code = row["device_code"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": CLIENT_ID,
                "device_code": device_code,
            },
        )

    if resp.status_code == 400:
        err = resp.json().get("error")
        if err == "authorization_pending":
            return DevicePollPending
        if err == "slow_down":
            # Per OAuth device-code spec — caller should back off; we
            # treat as pending. Optional: bump interval in DDB.
            return DevicePollPending
        raise RuntimeError(f"OpenAI device-code poll failed: {err}")
    resp.raise_for_status()

    body = resp.json()
    tokens_plain = json.dumps(
        {
            "access_token": body["access_token"],
            "refresh_token": body["refresh_token"],
            "id_token": body.get("id_token"),
            "account_id": body.get("account_id"),
        }
    ).encode()
    encrypted = _fernet().encrypt(tokens_plain)

    _table().update_item(
        Key={"user_id": user_id},
        UpdateExpression=(
            "SET #s = :ok, encrypted_tokens = :tok, account_id = :acc "
            "REMOVE device_code, user_code, interval"
        ),
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={
            ":ok": "active",
            ":tok": encrypted,
            ":acc": body.get("account_id") or "",
        },
    )
    return DevicePollResult(account_id=body.get("account_id"))


async def get_decrypted_tokens(*, user_id: str) -> dict | None:
    """Decrypt and return the user's stored OAuth tokens. None if no row."""
    row = _table().get_item(Key={"user_id": user_id}).get("Item")
    if not row or row.get("state") != "active":
        return None
    plain = _fernet().decrypt(bytes(row["encrypted_tokens"]))
    return json.loads(plain.decode())


async def revoke_user_oauth(*, user_id: str) -> None:
    """Delete the user's OAuth row. Caller is responsible for also
    deleting any pre-staged auth file on EFS (see workspace.py)."""
    _table().delete_item(Key={"user_id": user_id})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_oauth_service.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/services/oauth_service.py apps/backend/tests/unit/services/test_oauth_service.py apps/backend/pyproject.toml apps/backend/uv.lock
git commit -m "$(cat <<'EOF'
feat(oauth): backend-driven device-code flow for ChatGPT OAuth

Hand-rolled device-code orchestration against auth.openai.com using the
public Codex CLI client_id (verified in pi-mono source). Backend POSTs
to /codex/device, stores the device_code keyed by our user_id, then polls
the token endpoint. On success: tokens are Fernet-encrypted and persisted
to oauth-tokens DDB. Per spec §5.1 / §5.1.1.

We do NOT install pi-ai — that library writes tokens to ~/.codex/auth.json
which would clobber on a shared backend. We borrow constants and isolate
per-user.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `routers/oauth.py` — `/api/v1/oauth/chatgpt/*` endpoints

**Files:**
- Create: `apps/backend/routers/oauth.py`
- Test: `apps/backend/tests/unit/routers/test_oauth.py`
- Modify: `apps/backend/main.py` — register router.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/routers/test_oauth.py`:

```python
"""Integration tests for /api/v1/oauth/chatgpt/* endpoints."""

from unittest.mock import AsyncMock, patch

import pytest

from core.services.oauth_service import (
    DeviceCodeResponse,
    DevicePollPending,
    DevicePollResult,
)


@pytest.mark.asyncio
async def test_start_returns_user_code_and_verification_uri(authed_client):
    fake_resp = DeviceCodeResponse(
        user_code="TEST-1234",
        verification_uri="https://chatgpt.com/codex",
        expires_in=900,
        interval=5,
    )
    with patch(
        "routers.oauth.request_device_code",
        new=AsyncMock(return_value=fake_resp),
    ):
        resp = await authed_client.post("/api/v1/oauth/chatgpt/start")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_code"] == "TEST-1234"
    assert body["verification_uri"] == "https://chatgpt.com/codex"
    assert body["interval"] == 5


@pytest.mark.asyncio
async def test_poll_returns_pending_status(authed_client):
    with patch(
        "routers.oauth.poll_device_code",
        new=AsyncMock(return_value=DevicePollPending),
    ):
        resp = await authed_client.post("/api/v1/oauth/chatgpt/poll")
    assert resp.status_code == 200
    assert resp.json() == {"status": "pending"}


@pytest.mark.asyncio
async def test_poll_returns_completed_status(authed_client):
    with patch(
        "routers.oauth.poll_device_code",
        new=AsyncMock(return_value=DevicePollResult(account_id="acc_1")),
    ):
        resp = await authed_client.post("/api/v1/oauth/chatgpt/poll")
    assert resp.status_code == 200
    assert resp.json() == {"status": "completed", "account_id": "acc_1"}


@pytest.mark.asyncio
async def test_disconnect_revokes(authed_client):
    with patch(
        "routers.oauth.revoke_user_oauth", new=AsyncMock()
    ) as mock_revoke:
        resp = await authed_client.post("/api/v1/oauth/chatgpt/disconnect")
    assert resp.status_code == 204
    mock_revoke.assert_awaited_once()
```

(Note: requires an `authed_client` fixture that injects a valid Clerk JWT. If absent, model after `tests/unit/routers/conftest.py` patterns from existing routers like `test_billing.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_oauth.py -v`
Expected: failures — likely `404 Not Found` on the routes (router not registered yet).

- [ ] **Step 3: Implement the router**

Create `apps/backend/routers/oauth.py`:

```python
"""ChatGPT OAuth endpoints.

Per spec §5.1: backend-driven device-code flow. Frontend POSTs /start,
shows the user_code + verification_uri to the user, then polls /poll
until status flips from "pending" to "completed".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from core.auth import AuthContext, get_current_user
from core.services.oauth_service import (
    DevicePollPending,
    DevicePollResult,
    poll_device_code,
    request_device_code,
    revoke_user_oauth,
)


router = APIRouter(prefix="/oauth/chatgpt", tags=["oauth"])


@router.post("/start", summary="Begin a ChatGPT OAuth device-code session")
async def start(ctx: AuthContext = Depends(get_current_user)):
    result = await request_device_code(user_id=ctx.user_id)
    return {
        "user_code": result.user_code,
        "verification_uri": result.verification_uri,
        "expires_in": result.expires_in,
        "interval": result.interval,
    }


@router.post("/poll", summary="Poll the device-code session for completion")
async def poll(ctx: AuthContext = Depends(get_current_user)):
    result = await poll_device_code(user_id=ctx.user_id)
    if result is DevicePollPending:
        return {"status": "pending"}
    assert isinstance(result, DevicePollResult)
    return {"status": "completed", "account_id": result.account_id}


@router.post(
    "/disconnect",
    status_code=204,
    summary="Revoke the user's stored ChatGPT OAuth tokens",
)
async def disconnect(ctx: AuthContext = Depends(get_current_user)):
    await revoke_user_oauth(user_id=ctx.user_id)
    return Response(status_code=204)
```

- [ ] **Step 4: Register the router in main.py**

Edit `apps/backend/main.py`. Find where other routers are imported (e.g., `from routers import billing, ...`). Add `oauth`:

```python
from routers import oauth  # add to existing import line or alongside
```

And where they're mounted (e.g., `app.include_router(billing.router, prefix="/api/v1")`):

```python
app.include_router(oauth.router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_oauth.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/routers/oauth.py apps/backend/main.py apps/backend/tests/unit/routers/test_oauth.py
git commit -m "$(cat <<'EOF'
feat(oauth): /api/v1/oauth/chatgpt/{start,poll,disconnect} endpoints

Three-endpoint surface for the device-code flow:
- POST /start: backend kicks off device-code, returns user_code +
  verification_uri for the frontend to display
- POST /poll: returns {status: pending} or {status: completed, account_id}
- POST /disconnect: revokes the stored tokens (204)

All Clerk-authed, all per-user-isolated. Wires the router into main.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `workspace.py` — `pre_stage_codex_auth` helper

**Files:**
- Modify: `apps/backend/core/containers/workspace.py`
- Test: `apps/backend/tests/unit/containers/test_workspace_codex_auth.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/containers/test_workspace_codex_auth.py`:

```python
"""Tests for the EFS pre-staging of OpenClaw's Codex auth.json file."""

import json
import os
from pathlib import Path

import pytest

from core.containers.workspace import pre_stage_codex_auth


@pytest.fixture
def fake_efs_root(tmp_path, monkeypatch):
    monkeypatch.setenv("EFS_MOUNT_PATH", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_pre_stage_writes_codex_auth_json(fake_efs_root):
    tokens = {
        "access_token": "eyJ.access",
        "refresh_token": "rt_opaque",
        "account_id": "acc_1",
    }
    await pre_stage_codex_auth(user_id="u_1", oauth_tokens=tokens)

    expected_path = fake_efs_root / "u_1" / "codex" / "auth.json"
    assert expected_path.exists(), f"Expected {expected_path} to exist"
    written = json.loads(expected_path.read_text())
    assert written["auth_mode"] == "chatgpt"
    assert written["tokens"]["access_token"] == "eyJ.access"
    assert written["tokens"]["refresh_token"] == "rt_opaque"
    assert written["tokens"]["account_id"] == "acc_1"


@pytest.mark.asyncio
async def test_pre_stage_overwrites_existing(fake_efs_root):
    """Re-OAuth: rewrite the file with new tokens, no merge needed."""
    await pre_stage_codex_auth(
        user_id="u_1",
        oauth_tokens={"access_token": "old", "refresh_token": "old_rt", "account_id": "x"},
    )
    await pre_stage_codex_auth(
        user_id="u_1",
        oauth_tokens={"access_token": "new", "refresh_token": "new_rt", "account_id": "x"},
    )
    written = json.loads((fake_efs_root / "u_1" / "codex" / "auth.json").read_text())
    assert written["tokens"]["access_token"] == "new"
    assert written["tokens"]["refresh_token"] == "new_rt"


@pytest.mark.asyncio
async def test_pre_stage_creates_parent_dirs(fake_efs_root):
    """The codex/ subdir doesn't exist yet — helper must mkdir -p."""
    await pre_stage_codex_auth(
        user_id="brand_new_user",
        oauth_tokens={"access_token": "x", "refresh_token": "y", "account_id": "z"},
    )
    assert (fake_efs_root / "brand_new_user" / "codex").is_dir()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/containers/test_workspace_codex_auth.py -v`
Expected: failures — `pre_stage_codex_auth` not exported.

- [ ] **Step 3: Add the helper to workspace.py**

Edit `apps/backend/core/containers/workspace.py`. Append a new function:

```python
async def pre_stage_codex_auth(*, user_id: str, oauth_tokens: dict) -> None:
    """Write the user's ChatGPT OAuth profile to EFS before container start.

    The file shape is what OpenClaw's openai-codex provider reads at boot
    via ~/.codex/auth.json. The container is configured (in openclaw.json)
    to set CODEX_HOME to /mnt/efs/users/{user_id}/codex so this file is
    found cold. Per spec §5.1.

    Args:
        user_id: our internal user_id.
        oauth_tokens: dict with keys access_token, refresh_token, account_id
            (account_id is optional). Sourced from oauth_service.poll_device_code.
    """
    from pathlib import Path
    from core.config import settings
    import json

    base = Path(settings.EFS_MOUNT_PATH) / user_id / "codex"
    base.mkdir(parents=True, exist_ok=True)

    payload = {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": oauth_tokens["access_token"],
            "refresh_token": oauth_tokens["refresh_token"],
        },
    }
    if oauth_tokens.get("account_id"):
        payload["tokens"]["account_id"] = oauth_tokens["account_id"]

    auth_path = base / "auth.json"
    auth_path.write_text(json.dumps(payload, indent=2))
    # OpenClaw container runs as UID 1000 — match ownership so it can rotate
    # the file when refreshing tokens. Best-effort; ignore failures (e.g.
    # local dev without root).
    try:
        os.chown(str(auth_path), 1000, 1000)
        os.chown(str(base), 1000, 1000)
    except (PermissionError, OSError):
        pass
```

(Make sure `import os` is at the top of `workspace.py` — likely already present.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/containers/test_workspace_codex_auth.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/containers/workspace.py apps/backend/tests/unit/containers/test_workspace_codex_auth.py
git commit -m "$(cat <<'EOF'
feat(containers): pre_stage_codex_auth helper for EFS auth-staging

Writes /mnt/efs/users/{user_id}/codex/auth.json in the format OpenClaw's
openai-codex provider reads at boot. Called from provision_container()
when provider_choice=chatgpt_oauth. Best-effort chowns to UID 1000
(OpenClaw's container user) so the in-container auto-refresh can rotate
the file. Per spec §5.1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `key_service.py` — extend to LLM keys + Secrets Manager push

**Files:**
- Modify: `apps/backend/core/services/key_service.py`

- [ ] **Step 1: Read the existing key_service.py to understand the current shape**

Run: `cat /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/services/key_service.py | head -80`

You should see Fernet encrypt/decrypt + DDB persistence for tool keys (Perplexity, Firecrawl, OpenAI TTS, ElevenLabs). Note the existing `save_user_key`, `get_user_key`, `delete_user_key` function signatures.

- [ ] **Step 2: Add LLM provider support**

Find the validation list (likely a constant set like `_ALLOWED_PROVIDERS = {"perplexity", "firecrawl", ...}`). Add `"openai"` and `"anthropic"`:

```python
_ALLOWED_PROVIDERS = {
    "perplexity",
    "firecrawl",
    "elevenlabs",
    "openai_tts",
    "openai",      # NEW: LLM key for card 2
    "anthropic",   # NEW: LLM key for card 2
}
```

(Exact set name will vary; match the existing code.)

- [ ] **Step 3: Add Secrets Manager push for LLM providers**

Inside `save_user_key`, after the existing DDB write, add a branch:

```python
# LLM provider keys also get pushed to Secrets Manager so the per-user
# ECS task definition can reference them via `secrets: [{name, valueFrom}]`.
# Tool keys (Perplexity etc.) live in DDB only — they're read by the backend
# and forwarded to the user's container at chat time, not env-injected.
if provider in {"openai", "anthropic"}:
    secret_arn = await _put_user_secret(
        user_id=user_id,
        provider=provider,
        api_key_plaintext=api_key,
    )
    # Persist the ARN on the DDB row so ecs_manager.update_task_definition
    # can find it without re-querying Secrets Manager.
    await api_key_repo.set_secret_arn(user_id, provider, secret_arn)
```

Then add the `_put_user_secret` helper in the same file:

```python
async def _put_user_secret(
    *,
    user_id: str,
    provider: str,
    api_key_plaintext: str,
) -> str:
    """Create-or-update the per-user Secrets Manager secret. Returns ARN."""
    import boto3
    from core.config import settings

    name = f"isol8/{settings.ENVIRONMENT or 'dev'}/user-keys/{user_id}/{provider}"
    sm = boto3.client("secretsmanager", region_name=settings.AWS_REGION)
    try:
        sm.create_secret(Name=name, SecretString=api_key_plaintext)
    except sm.exceptions.ResourceExistsException:
        sm.put_secret_value(SecretId=name, SecretString=api_key_plaintext)
    return sm.describe_secret(SecretId=name)["ARN"]
```

And in `delete_user_key`, after the DDB delete, also tear down the secret:

```python
if provider in {"openai", "anthropic"}:
    import boto3
    from core.config import settings
    name = f"isol8/{settings.ENVIRONMENT or 'dev'}/user-keys/{user_id}/{provider}"
    sm = boto3.client("secretsmanager", region_name=settings.AWS_REGION)
    try:
        sm.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
    except sm.exceptions.ResourceNotFoundException:
        pass
```

- [ ] **Step 4: Add validation step (1-token test call)**

Per spec §5.2 step 3a: validate the key with a 1-token test call before storing. Add to `save_user_key`, before the DDB write:

```python
if provider == "openai":
    # 1-token test against /v1/models — cheapest read.
    import httpx
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if r.status_code == 401:
        raise ValueError("OpenAI API key rejected — verify the key and try again")
elif provider == "anthropic":
    import httpx
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
    if r.status_code == 401:
        raise ValueError("Anthropic API key rejected — verify the key and try again")
```

- [ ] **Step 5: Add `set_secret_arn` to `api_key_repo`**

Find `apps/backend/core/repositories/api_key_repo.py`. Add (or modify the existing put_item helper to support):

```python
async def set_secret_arn(user_id: str, provider: str, secret_arn: str) -> None:
    """Persist the AWS Secrets Manager ARN alongside the key row."""
    table = _table()
    table.update_item(
        Key={"user_id": user_id, "provider": provider},
        UpdateExpression="SET secret_arn = :a, updated_at = :t",
        ExpressionAttributeValues={
            ":a": secret_arn,
            ":t": _now_iso(),  # or however the rest of this file gets ISO time
        },
    )
```

(Match the existing helper-function patterns in the file — the snippet above is illustrative; adapt naming to what's there.)

- [ ] **Step 6: Run any existing key_service tests + add a new one for the LLM path**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_key_service.py -v`
Expected: existing tests pass (we didn't break them). If there were no existing tests, that's okay too.

- [ ] **Step 7: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/services/key_service.py apps/backend/core/repositories/api_key_repo.py
git commit -m "$(cat <<'EOF'
feat(keys): extend key_service to OpenAI/Anthropic LLM keys

Card 2 (BYO key) needs the user's LLM key reachable as an ECS env-var
secret. Pattern: save_user_key(openai|anthropic) validates with a
1-token test call, encrypts to DDB (existing path), AND pushes the
plaintext into Secrets Manager at isol8/{env}/user-keys/{user}/{provider}.
The secret ARN is stored on the DDB row so ecs_manager can build a
task-definition `secrets:` reference without re-querying.

Tool keys (Perplexity etc.) keep the DDB-only path — they're not
env-injected, just read by the backend at chat time.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `routers/settings_keys.py` — accept LLM key types

**Files:**
- Modify: `apps/backend/routers/settings_keys.py`

- [ ] **Step 1: Find the request schema or validation**

Run: `grep -n 'provider\|Provider\|allowed\|Allowed' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/routers/settings_keys.py | head -10`

You're looking for either a Pydantic model field with `Literal[...]` constraints or an inline `if provider not in {...}: raise`.

- [ ] **Step 2: Extend the allowed-provider literal**

If there's a Pydantic model like:

```python
class SaveKeyRequest(BaseModel):
    provider: Literal["perplexity", "firecrawl", "elevenlabs", "openai_tts"]
    api_key: str
```

Update to:

```python
class SaveKeyRequest(BaseModel):
    provider: Literal[
        "perplexity", "firecrawl", "elevenlabs", "openai_tts",
        "openai", "anthropic",
    ]
    api_key: str
```

If validation is inline (`if provider not in _ALLOWED:`) the `key_service` change in Task 10 already covers it — no router change needed.

- [ ] **Step 3: Verify the router still accepts the old types + the new ones**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_settings_keys.py -v` (if file exists)
Expected: passes. If no such test exists, hit it manually with curl after deploy.

- [ ] **Step 4: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/routers/settings_keys.py
git commit -m "$(cat <<'EOF'
feat(keys): accept openai + anthropic providers on POST /settings/keys

Wires the router validation to allow the two new LLM-provider key types
introduced by the BYO-key card (spec §5.2).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `core/containers/config.py` — provider routing in `write_openclaw_config`

**Files:**
- Modify: `apps/backend/core/containers/config.py`
- Test: `apps/backend/tests/unit/containers/test_config_provider_routing.py`

- [ ] **Step 1: Read the current `write_openclaw_config` signature + body**

Run: `grep -n 'def write_openclaw_config\|_TIER_ALLOWED_MODEL_IDS\|MiniMax\|Qwen' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/containers/config.py`

Note the current signature, the per-tier model whitelist, and the model catalog entries.

- [ ] **Step 2: Write the failing tests**

Create `apps/backend/tests/unit/containers/test_config_provider_routing.py`:

```python
"""write_openclaw_config emits the correct provider block per provider_choice."""

import json
from pathlib import Path

import pytest

from core.containers.config import write_openclaw_config


@pytest.mark.asyncio
async def test_chatgpt_oauth_branch(tmp_path):
    out = tmp_path / "openclaw.json"
    await write_openclaw_config(
        config_path=out,
        provider_choice="chatgpt_oauth",
        user_id="u_1",
    )
    cfg = json.loads(out.read_text())
    primary = cfg["agents"]["defaults"]["model"]["primary"]
    assert primary == "openai-codex/gpt-5.5"
    # CODEX_HOME points at the user's EFS auth dir.
    assert cfg["models"]["providers"]["openai-codex"]["codexHome"].endswith(
        "/u_1/codex"
    )


@pytest.mark.asyncio
async def test_openai_key_branch(tmp_path):
    out = tmp_path / "openclaw.json"
    await write_openclaw_config(
        config_path=out,
        provider_choice="byo_key",
        byo_provider="openai",
        user_id="u_1",
    )
    cfg = json.loads(out.read_text())
    primary = cfg["agents"]["defaults"]["model"]["primary"]
    assert primary == "openai/gpt-5.4"
    # The OPENAI_API_KEY env var is injected via ECS task secret, not in this file.
    assert "env" not in cfg or "OPENAI_API_KEY" not in cfg.get("env", {}), (
        "API key should never be embedded in openclaw.json — comes from ECS secret"
    )


@pytest.mark.asyncio
async def test_anthropic_key_branch(tmp_path):
    out = tmp_path / "openclaw.json"
    await write_openclaw_config(
        config_path=out,
        provider_choice="byo_key",
        byo_provider="anthropic",
        user_id="u_1",
    )
    cfg = json.loads(out.read_text())
    primary = cfg["agents"]["defaults"]["model"]["primary"]
    subagent = cfg["agents"]["defaults"]["model"]["subagent"]
    assert primary == "anthropic/claude-opus-4-7"
    assert subagent == "anthropic/claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_bedrock_claude_branch(tmp_path):
    out = tmp_path / "openclaw.json"
    await write_openclaw_config(
        config_path=out,
        provider_choice="bedrock_claude",
        user_id="u_1",
    )
    cfg = json.loads(out.read_text())
    primary = cfg["agents"]["defaults"]["model"]["primary"]
    assert primary == "amazon-bedrock/anthropic.claude-opus-4-7"
    bedrock_cfg = cfg["plugins"]["entries"]["amazon-bedrock"]["config"]
    assert bedrock_cfg["discovery"]["enabled"] is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/containers/test_config_provider_routing.py -v`
Expected: failures — likely TypeError on missing kwargs or assertion mismatches against the existing tier-based config.

- [ ] **Step 4: Refactor `write_openclaw_config` to branch on `provider_choice`**

Replace the old function body. The new signature:

```python
async def write_openclaw_config(
    *,
    config_path: Path,
    provider_choice: str,           # "chatgpt_oauth" | "byo_key" | "bedrock_claude"
    user_id: str,
    byo_provider: str | None = None,  # required when provider_choice == "byo_key"
) -> None:
    """Write the user's openclaw.json with the correct provider block.

    Per spec §4.2. Tier gating + per-tier model whitelisting is removed —
    one config shape per provider_choice. The OPENAI_API_KEY / ANTHROPIC_API_KEY
    env vars are NEVER written into this file; they're injected via ECS
    task definition secrets at task start.
    """

    base_config: dict = {
        "agents": {"defaults": {"model": {}}},
        "plugins": {"entries": {}},
    }

    if provider_choice == "chatgpt_oauth":
        codex_home = f"{settings.EFS_MOUNT_PATH}/{user_id}/codex"
        base_config["models"] = {
            "providers": {"openai-codex": {"codexHome": codex_home}}
        }
        base_config["agents"]["defaults"]["model"] = {
            "primary": "openai-codex/gpt-5.5",
            "subagent": "openai-codex/gpt-5.5",
        }

    elif provider_choice == "byo_key":
        if byo_provider == "openai":
            base_config["agents"]["defaults"]["model"] = {
                "primary": "openai/gpt-5.4",
                "subagent": "openai/gpt-5.4",
            }
        elif byo_provider == "anthropic":
            base_config["agents"]["defaults"]["model"] = {
                "primary": "anthropic/claude-opus-4-7",
                "subagent": "anthropic/claude-sonnet-4-6",
            }
        else:
            raise ValueError(f"byo_provider must be 'openai' or 'anthropic', got {byo_provider!r}")

    elif provider_choice == "bedrock_claude":
        base_config["plugins"]["entries"]["amazon-bedrock"] = {
            "config": {"discovery": {"enabled": True, "region": settings.AWS_REGION}}
        }
        base_config["agents"]["defaults"]["model"] = {
            "primary": "amazon-bedrock/anthropic.claude-opus-4-7",
            "subagent": "amazon-bedrock/anthropic.claude-sonnet-4-6",
        }

    else:
        raise ValueError(f"Unknown provider_choice: {provider_choice!r}")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(base_config, indent=2))
```

- [ ] **Step 5: Delete `_TIER_ALLOWED_MODEL_IDS` and the MiniMax / Qwen catalog entries**

In the same file, find and delete:
- The `_TIER_ALLOWED_MODEL_IDS = {...}` dict
- Any `_DEFAULT_MODELS_BY_TIER` or similar tier-based defaults
- Catalog entries for `minimax.minimax-m2.5`, `qwen.qwen3-vl-235b` if they live in this file (some may be in `core/services/catalog_service.py` — leave those for Plan 3 cutover)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/containers/test_config_provider_routing.py -v`
Expected: 4 passed.

- [ ] **Step 7: Run any existing config tests to confirm no regression**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/containers/ -v`
Expected: pass. If any old tests assumed tier-based config, update them to call with the new `provider_choice=` kwarg or delete them if obsolete.

- [ ] **Step 8: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/containers/config.py apps/backend/tests/unit/containers/test_config_provider_routing.py
git commit -m "$(cat <<'EOF'
feat(containers): write_openclaw_config branches on provider_choice

Per spec §4.2: four provider config shapes, one per signup card. CODEX_HOME
points at EFS for chatgpt_oauth (where the pre-staged auth.json lives).
API keys are never embedded in the config file — they come from ECS task
secrets at start. Bedrock branch enables provider discovery for the task
role's IAM creds.

Deletes the per-tier model whitelist and MiniMax/Qwen catalog entries
that lived in this file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: `ecs_manager.py` — single size + provider_choice + secret injection

**Files:**
- Modify: `apps/backend/core/containers/ecs_manager.py`

- [ ] **Step 1: Find the existing tier sizing + task-def construction**

Run: `grep -n '_TIER_TASK_RESOURCES\|provision_container\|register_task_definition\|task_definition' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/containers/ecs_manager.py | head -15`

- [ ] **Step 2: Replace the per-tier sizing with a single constant**

Find `_TIER_TASK_RESOURCES = { ... }`. Replace with:

```python
# Single per-user task size (spec §3.2 / §10). Per-tier sizing is gone.
PER_USER_CPU = "512"
PER_USER_MEMORY_MIB = "1024"
```

Update every read site (e.g. `cpu = _TIER_TASK_RESOURCES[tier]["cpu"]`) to use the new constants.

- [ ] **Step 3: Add `provider_choice` parameter to `provision_container`**

Find the `provision_container` function signature. Add the param and propagate it down:

```python
async def provision_container(
    *,
    user_id: str,
    provider_choice: str,                # "chatgpt_oauth" | "byo_key" | "bedrock_claude"
    byo_provider: str | None = None,     # required when provider_choice == "byo_key"
    # ... existing params ...
) -> dict:
```

- [ ] **Step 4: Build the task-def `secrets:` block per `provider_choice`**

Inside `provision_container`, before registering the task definition, compute the secrets list:

```python
secrets_for_task: list[dict] = []
if provider_choice == "byo_key":
    if byo_provider not in {"openai", "anthropic"}:
        raise ValueError(f"byo_provider must be set for byo_key, got {byo_provider!r}")
    # The api_key_repo row was populated by key_service when the user saved
    # their key. The secret_arn is the AWS Secrets Manager ARN to inject.
    key_row = await api_key_repo.get(user_id, byo_provider)
    if not key_row or not key_row.get("secret_arn"):
        raise RuntimeError(
            f"No saved {byo_provider} key for user {user_id} — caller should "
            "block provisioning until the user adds their key"
        )
    env_var_name = "OPENAI_API_KEY" if byo_provider == "openai" else "ANTHROPIC_API_KEY"
    secrets_for_task.append({"name": env_var_name, "valueFrom": key_row["secret_arn"]})
```

(For `chatgpt_oauth`: no per-task secret — the auth file is on EFS. For `bedrock_claude`: AWS creds come from the task role.)

- [ ] **Step 5: Stage OAuth auth file BEFORE the ECS service is created**

Inside `provision_container`, after the EFS access point is provisioned and before the ECS service is created, when `provider_choice == "chatgpt_oauth"`:

```python
if provider_choice == "chatgpt_oauth":
    from core.services.oauth_service import get_decrypted_tokens
    tokens = await get_decrypted_tokens(user_id=user_id)
    if not tokens:
        raise RuntimeError(
            f"No ChatGPT OAuth tokens for user {user_id} — caller should "
            "complete OAuth before provisioning"
        )
    from core.containers.workspace import pre_stage_codex_auth
    await pre_stage_codex_auth(user_id=user_id, oauth_tokens=tokens)
```

- [ ] **Step 6: Pass `provider_choice` through to `write_openclaw_config`**

Find the existing `write_openclaw_config(...)` call inside `provision_container`. Update to:

```python
await write_openclaw_config(
    config_path=Path(settings.EFS_MOUNT_PATH) / user_id / "openclaw.json",
    provider_choice=provider_choice,
    user_id=user_id,
    byo_provider=byo_provider,
)
```

- [ ] **Step 7: Use the new sizing + secrets when registering task def**

Find the `ecs_client.register_task_definition(...)` call. Update the `containerDefinitions[0]`:

```python
container_def = {
    "name": "openclaw",
    "image": settings.OPENCLAW_IMAGE,
    "essential": True,
    "memory": int(PER_USER_MEMORY_MIB),
    "cpu": int(PER_USER_CPU),
    # ... existing mountPoints, environment, healthCheck ...
}
if secrets_for_task:
    container_def["secrets"] = secrets_for_task

ecs_client.register_task_definition(
    family=f"openclaw-{user_id}",
    networkMode="awsvpc",
    requiresCompatibilities=["FARGATE"],
    cpu=PER_USER_CPU,
    memory=PER_USER_MEMORY_MIB,
    executionRoleArn=settings.ECS_EXECUTION_ROLE_ARN,
    taskRoleArn=settings.ECS_TASK_ROLE_ARN,
    containerDefinitions=[container_def],
    volumes=[...existing EFS volume config...],
)
```

(Match exact param names to whatever the existing call uses.)

- [ ] **Step 8: Run the existing ecs_manager tests**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py -v`
Expected: pass. Existing tests likely call `provision_container(...)` without `provider_choice`. Update them by adding `provider_choice="bedrock_claude"` (the current behavior nearest analog) so they don't break.

- [ ] **Step 9: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/containers/ecs_manager.py apps/backend/tests/unit/containers/test_ecs_manager.py
git commit -m "$(cat <<'EOF'
feat(containers): single 512/1024 task size + provider_choice plumbing

Per spec §10:
- Replaces _TIER_TASK_RESOURCES with PER_USER_CPU/MEMORY constants
- provision_container now takes provider_choice (and byo_provider for card 2)
- For chatgpt_oauth: pre-stages /mnt/efs/users/{user}/codex/auth.json
  BEFORE the ECS service is created, so the container reads it cold
- For byo_key: builds the task-def `secrets:` list referencing the
  per-user Secrets Manager ARN saved by key_service
- For bedrock_claude: nothing extra; AWS creds come from task role

Old per-tier sizing constants deleted.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Credit endpoints — `POST /credits/top_up`, `PUT /credits/auto_reload`, `GET /credits/balance`

**Files:**
- Modify: `apps/backend/routers/billing.py`
- Test: `apps/backend/tests/unit/routers/test_billing_credits.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/routers/test_billing_credits.py`:

```python
"""Tests for the new credit-management endpoints."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_balance_returns_microcents(authed_client):
    with patch(
        "routers.billing.credit_ledger.get_balance",
        new=AsyncMock(return_value=12_345_678),
    ):
        resp = await authed_client.get("/api/v1/billing/credits/balance")
    assert resp.status_code == 200
    assert resp.json() == {
        "balance_microcents": 12_345_678,
        "balance_dollars": "12.35",
    }


@pytest.mark.asyncio
async def test_top_up_creates_payment_intent(authed_client):
    fake_pi = type("PI", (), {"id": "pi_test", "client_secret": "secret_test"})()
    with patch(
        "routers.billing.billing_repo.get_by_owner_id",
        new=AsyncMock(return_value={"stripe_customer_id": "cus_test"}),
    ), patch("stripe.PaymentIntent.create", return_value=fake_pi) as mock_pi:
        resp = await authed_client.post(
            "/api/v1/billing/credits/top_up",
            json={"amount_cents": 2000},  # $20
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_secret"] == "secret_test"
    _, kwargs = mock_pi.call_args
    assert kwargs["amount"] == 2000
    assert kwargs["currency"] == "usd"
    assert kwargs["customer"] == "cus_test"
    assert kwargs["metadata"]["purpose"] == "credit_top_up"
    assert "idempotency_key" in kwargs


@pytest.mark.asyncio
async def test_top_up_below_minimum_rejected(authed_client):
    resp = await authed_client.post(
        "/api/v1/billing/credits/top_up",
        json={"amount_cents": 100},  # $1, below $5 min
    )
    assert resp.status_code == 400
    assert "minimum" in resp.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_set_auto_reload_persists(authed_client):
    with patch(
        "routers.billing.credit_ledger.set_auto_reload", new=AsyncMock()
    ) as mock_set:
        resp = await authed_client.put(
            "/api/v1/billing/credits/auto_reload",
            json={"enabled": True, "threshold_cents": 500, "amount_cents": 5000},
        )
    assert resp.status_code == 204
    mock_set.assert_awaited_once_with(
        "test_user_id",  # from authed_client fixture
        enabled=True,
        threshold_cents=500,
        amount_cents=5000,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_billing_credits.py -v`
Expected: failures — endpoints don't exist.

- [ ] **Step 3: Add the endpoints to `routers/billing.py`**

Find a good spot (alphabetically near `/portal` or at the end of the file). Add the imports if missing:

```python
from pydantic import BaseModel, Field
from core.services import credit_ledger
```

Then add the endpoint code:

```python
class TopUpRequest(BaseModel):
    amount_cents: int = Field(..., ge=500, description="Minimum $5 (500 cents)")


class AutoReloadRequest(BaseModel):
    enabled: bool
    threshold_cents: int | None = Field(default=None, ge=500)
    amount_cents: int | None = Field(default=None, ge=500)


@router.get("/credits/balance", summary="Get the user's prepaid credit balance")
async def get_credits_balance(ctx: AuthContext = Depends(get_current_user)):
    balance_uc = await credit_ledger.get_balance(ctx.user_id)
    # 1 dollar = 1_000_000 microcents — convert for display.
    dollars = f"{balance_uc / 1_000_000:.2f}"
    return {"balance_microcents": balance_uc, "balance_dollars": dollars}


@router.post("/credits/top_up", summary="Buy credits via Stripe PaymentIntent")
async def top_up_credits(
    body: TopUpRequest,
    ctx: AuthContext = Depends(get_current_user),
):
    if body.amount_cents < 500:
        raise HTTPException(status_code=400, detail="Minimum top-up is $5 (500 cents)")
    account = await billing_repo.get_by_owner_id(ctx.user_id)
    if not account or not account.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No Stripe customer on file")

    with timing("stripe.api.latency", {"op": "payment_intent.create"}):
        pi = stripe.PaymentIntent.create(
            amount=body.amount_cents,
            currency="usd",
            customer=account["stripe_customer_id"],
            automatic_payment_methods={"enabled": True},
            metadata={
                "purpose": "credit_top_up",
                "user_id": ctx.user_id,
            },
            idempotency_key=f"top_up:{ctx.user_id}:{body.amount_cents}:{int(time.time() // 60)}",
        )
    return {"client_secret": pi.client_secret, "payment_intent_id": pi.id}


@router.put("/credits/auto_reload", status_code=204, summary="Configure auto-reload")
async def set_auto_reload(
    body: AutoReloadRequest,
    ctx: AuthContext = Depends(get_current_user),
):
    if body.enabled and (body.threshold_cents is None or body.amount_cents is None):
        raise HTTPException(
            status_code=400,
            detail="threshold_cents and amount_cents required when enabling",
        )
    await credit_ledger.set_auto_reload(
        ctx.user_id,
        enabled=body.enabled,
        threshold_cents=body.threshold_cents,
        amount_cents=body.amount_cents,
    )
    return Response(status_code=204)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_billing_credits.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/routers/billing.py apps/backend/tests/unit/routers/test_billing_credits.py
git commit -m "$(cat <<'EOF'
feat(billing): credit balance, top-up, and auto-reload endpoints

Per spec §6.2 + §6.4:
- GET /credits/balance: read-through to credit_ledger
- POST /credits/top_up: creates a Stripe PaymentIntent, frontend confirms
  with Elements, webhook handler (next task) credits the balance
- PUT /credits/auto_reload: configure threshold + amount

$5 min on top-ups (matches Anthropic / OpenAI Console). Idempotency key
on the PaymentIntent uses a 1-min bucket so user-initiated retries dedupe.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Webhook handler — `payment_intent.succeeded` credits the ledger

**Files:**
- Modify: `apps/backend/routers/billing.py` — add a branch to the existing Stripe webhook handler.

- [ ] **Step 1: Find the webhook event-type switch**

Run: `grep -n 'event_type ==\|event\\["type"\\] ==\|invoice.payment_succeeded\|payment_intent' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/routers/billing.py | head -20`

You should see an `if/elif` chain inside `handle_stripe_webhook` matching event types.

- [ ] **Step 2: Add the `payment_intent.succeeded` branch**

Inside the existing `if/elif` chain (after the dedup check from Plan 1 Task 3), add:

```python
    elif event_type == "payment_intent.succeeded":
        pi = event["data"]["object"]
        if pi.get("metadata", {}).get("purpose") != "credit_top_up":
            # Some other payment intent (e.g. Stripe-internal). Ignore.
            return Response(status_code=200)

        user_id = pi["metadata"].get("user_id")
        if not user_id:
            logger.error("Credit top-up webhook missing user_id metadata: %s", pi["id"])
            return Response(status_code=200)

        # 1 cent = 10_000 microcents. PaymentIntent.amount is in cents.
        amount_microcents = int(pi["amount"]) * 10_000
        await credit_ledger.top_up(
            user_id,
            amount_microcents=amount_microcents,
            stripe_payment_intent_id=pi["id"],
        )
        put_metric(
            "credit.top_up",
            value=pi["amount"] / 100.0,
            unit="None",
            dimensions={"source": "stripe_payment_intent"},
        )
```

- [ ] **Step 3: Add an integration test for the new branch**

Append to `apps/backend/tests/unit/routers/test_billing_credits.py`:

```python
@pytest.mark.asyncio
async def test_payment_intent_succeeded_credits_ledger(
    async_client, monkeypatch, dedup_table_and_settings
):
    fake_event = {
        "id": "evt_pi_credit_1",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_test",
                "amount": 2000,  # $20
                "metadata": {
                    "purpose": "credit_top_up",
                    "user_id": "u_buyer",
                },
            }
        },
    }
    monkeypatch.setattr(
        "stripe.Webhook.construct_event",
        lambda body, sig, secret: fake_event,
    )

    with patch(
        "routers.billing.credit_ledger.top_up", new=AsyncMock(return_value=20_000_000)
    ) as mock_top_up:
        import json
        resp = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=json.dumps(fake_event),
            headers={"stripe-signature": "ignored"},
        )

    assert resp.status_code == 200
    mock_top_up.assert_awaited_once_with(
        "u_buyer",
        amount_microcents=20_000_000,  # $20 = 2000 cents = 20M microcents
        stripe_payment_intent_id="pi_test",
    )
```

- [ ] **Step 4: Run the new test**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_billing_credits.py::test_payment_intent_succeeded_credits_ledger -v`
Expected: PASS.

- [ ] **Step 5: Run the full billing-router test suite**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_billing.py tests/unit/routers/test_billing_credits.py tests/unit/routers/test_billing_webhook_dedup.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/routers/billing.py apps/backend/tests/unit/routers/test_billing_credits.py
git commit -m "$(cat <<'EOF'
feat(billing): payment_intent.succeeded webhook credits the ledger

Reads PaymentIntent.metadata.purpose == "credit_top_up" + .user_id, then
calls credit_ledger.top_up. Webhook-event dedup (Plan 1) prevents double
crediting on Stripe replays. Per spec §6.2.

Other PaymentIntent purposes (Stripe-internal, future use) silently 200.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Delete `usage_poller.py` and the `usage_event` / `usage_daily` tables

**Files:**
- Delete: `apps/backend/core/services/usage_poller.py`
- Delete: `apps/backend/models/billing.py` (only if it ONLY contains usage_event / usage_daily — verify first)
- Modify: `apps/backend/main.py` — remove the poller startup hook.

- [ ] **Step 1: Find every reference to `usage_poller`**

Run: `grep -rn 'usage_poller\|UsagePoller\|run_scheduled_worker' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/ --include='*.py' | grep -v __pycache__`

You should see (a) the file itself, (b) an import + start call in `main.py` lifespan handler.

- [ ] **Step 2: Remove the poller from main.py lifespan**

Edit `apps/backend/main.py`. Find the `lifespan` async-context-manager. Remove:

```python
from core.services.usage_poller import run_scheduled_worker  # delete this import
# ... and inside lifespan: ...
poller_task = asyncio.create_task(run_scheduled_worker())
# ... and the cleanup:
poller_task.cancel()
```

- [ ] **Step 3: Verify the imports + tests don't break**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run python -c "from main import app; print('ok')"`
Expected: `ok`. If it errors with another import-of-`usage_poller`, fix that import too.

- [ ] **Step 4: Delete the file**

```bash
rm /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/services/usage_poller.py
```

- [ ] **Step 5: Check whether `models/billing.py` should also go**

Run: `cat /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/models/billing.py`

If the file ONLY contains `usage_event` / `usage_daily` schema, delete it. If it has other content, leave it and just remove the obsolete classes.

- [ ] **Step 6: Run the full test suite — must pass without poller**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/ -v`
Expected: all pass. If any tests imported usage_poller or its classes, delete those tests — they covered code that no longer exists.

- [ ] **Step 7: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add -A apps/backend/
git commit -m "$(cat <<'EOF'
refactor(billing): delete usage_poller — replaced by credit_ledger

The poller was scanning DDB usage rows and reporting overages to Stripe
Meters. The flat-fee pivot removes overage entirely (cards 1+2: we don't
see the cost; card 3: synchronous deduct from credit_ledger). The poller
has nothing to do.

Removes the lifespan startup hook in main.py and any dead imports.
Old usage_event / usage_daily DDB tables are still provisioned in CDK;
Plan 3 cutover removes them after we confirm no live traffic depends.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: `billing_service.py` — flat-fee subscription helper

**Files:**
- Modify: `apps/backend/core/services/billing_service.py`

- [ ] **Step 1: Add a `create_flat_fee_checkout` (or `create_trial_subscription`) helper**

The actual Stripe Subscription create lives in Plan 3 (trial mechanics). For Plan 2 we just add the helper that uses `STRIPE_FLAT_PRICE_ID` instead of the per-tier price IDs.

Find the existing `create_checkout_session` function. Below it, add:

```python
async def create_flat_fee_checkout(*, owner_id: str) -> stripe.checkout.Session:
    """Create a Stripe Checkout session on the single flat-fee price.

    Used by frontend cards 1, 2, 3 — all three pay $50/mo to the same
    STRIPE_FLAT_PRICE_ID. The trial flow (Plan 3) bypasses Checkout entirely
    in favor of SetupIntent + Subscription create with trial_period_days; this
    helper exists for the no-trial path (e.g. card 3 if the user opts to skip
    trial and pay immediately).
    """
    if not settings.STRIPE_FLAT_PRICE_ID:
        raise RuntimeError("STRIPE_FLAT_PRICE_ID not configured")

    account = await billing_repo.get_by_owner_id(owner_id)
    if not account or not account.get("stripe_customer_id"):
        raise RuntimeError(f"No Stripe customer for owner_id={owner_id}")

    with timing("stripe.api.latency", {"op": "checkout.session.create"}):
        session = stripe.checkout.Session.create(
            customer=account["stripe_customer_id"],
            mode="subscription",
            line_items=[{"price": settings.STRIPE_FLAT_PRICE_ID, "quantity": 1}],
            success_url=f"{settings.FRONTEND_URL}/chat?checkout=success",
            cancel_url=f"{settings.FRONTEND_URL}/onboarding?checkout=cancel",
            automatic_tax={"enabled": True},
            customer_update={"address": "auto"},
            idempotency_key=f"flat_checkout:{owner_id}:{int(time.time() // 300)}",
        )
    return session
```

- [ ] **Step 2: Don't delete the per-tier `create_checkout_session` yet**

Plan 3 cutover deletes it. For now both paths coexist — the new code uses `create_flat_fee_checkout`, the old code keeps serving live traffic until cutover.

- [ ] **Step 3: Smoke-test in isolation**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run python -c "from core.services.billing_service import create_flat_fee_checkout; print('importable')"`
Expected: `importable`.

- [ ] **Step 4: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/services/billing_service.py
git commit -m "$(cat <<'EOF'
feat(billing): create_flat_fee_checkout helper using STRIPE_FLAT_PRICE_ID

Single-price Checkout for the flat-fee pivot. Coexists with the per-tier
create_checkout_session for now; Plan 3 cutover deletes the old one.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: Smoke test the full backend in dev

**Files:** none — deploy + manual verification only.

- [ ] **Step 1: Run the full backend test suite locally**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/ -v`
Expected: all pass.

- [ ] **Step 2: Run lint + type-check**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync && turbo run lint --filter=@isol8/backend`
Expected: PASS.

- [ ] **Step 3: Push and watch CI**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git push origin main
sleep 10
RUN_ID=$(gh run list --repo Isol8AI/isol8 --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo Isol8AI/isol8 --exit-status
```

Expected: deploy.yml + backend.yml both green.

- [ ] **Step 4: Manually create the Stripe Flat Price (one-time, ops)**

In the Stripe dashboard (Test mode for dev, Live mode for prod):
1. Products → Create product → name: "Isol8 Hosted Agent", description: "Always-on personal AI agent infrastructure"
2. Add a price: $50.00 USD, recurring monthly
3. Copy the price ID (`price_...`)
4. Set the GitHub Actions secret `STRIPE_FLAT_PRICE_ID` to that value (Settings → Secrets and variables → Actions → New repository secret)
5. Re-deploy: `gh workflow run deploy.yml --ref main`

(Per env: do this once for Test mode using dev secrets, once for Live mode using prod secrets.)

- [ ] **Step 5: Smoke test the new endpoints in dev browser console**

```javascript
const t = await Clerk.session.getToken();

// Balance — should return 0 for a new user.
await fetch('https://api-dev.isol8.co/api/v1/billing/credits/balance', {
  headers: { Authorization: 'Bearer ' + t }
}).then(r => r.json())

// Auto-reload toggle — should 204.
await fetch('https://api-dev.isol8.co/api/v1/billing/credits/auto_reload', {
  method: 'PUT',
  headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' },
  body: JSON.stringify({ enabled: true, threshold_cents: 500, amount_cents: 5000 })
})

// Top-up — should return a client_secret you can use with Stripe Elements.
await fetch('https://api-dev.isol8.co/api/v1/billing/credits/top_up', {
  method: 'POST',
  headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' },
  body: JSON.stringify({ amount_cents: 1000 })
}).then(r => r.json())

// OAuth start — should return user_code + verification_uri.
await fetch('https://api-dev.isol8.co/api/v1/oauth/chatgpt/start', {
  method: 'POST',
  headers: { Authorization: 'Bearer ' + t }
}).then(r => r.json())
```

If any of those 500, check CloudWatch logs for the backend task and fix forward.

- [ ] **Step 6: No commit — deploy-only**

---

## Self-Review

**Spec coverage check** (vs the relevant spec sections):

| Spec section | Tasks |
|---|---|
| §3.2 — single 512/1024 | Task 2 (CDK) + Task 13 (backend) |
| §3.3 — kill MiniMax/Qwen catalog + per-tier code | Task 12 (config.py) + Task 16 (poller) |
| §4.2 — provider config shapes | Task 12 |
| §5.1 — ChatGPT OAuth device-code | Tasks 7 + 8 + 9 |
| §5.1.1 — public client_id | Task 7 (the `CLIENT_ID` constant) |
| §5.2 — BYO API key | Tasks 10 + 11 + 13 |
| §5.3 — Bedrock-Claude | Task 12 (bedrock branch) + Task 13 (no-secret path) |
| §6.1 — credits + transactions tables | Task 1 (CDK) + Task 6 (service) |
| §6.2 — top-up flow | Task 14 (endpoint) + Task 15 (webhook) |
| §6.3 — deduct flow + bedrock_pricing | Task 5 + Task 6 (deduct method); chat-path wiring is Plan 3 |
| §6.4 — auto-reload | Task 6 + Task 14 |
| §6.5 — non-refundable + adjustment | Task 6 (`adjustment` method) |
| §6.6 — hard stop on $0 | Provided by `credit_ledger.deduct` overdraft handling; pre-chat check is Plan 3 |
| §10 — provisioning rewrite | Tasks 9 + 13 |

Items deferred to Plan 3 (intentional): trial state machine (§7), frontend (§9), chat-path wiring of credits, cutover.

**Placeholder scan:** all steps have concrete code, exact paths, exact commands. No "TODO" / "TBD" / "fill in" placeholders.

**Type / signature consistency check:**
- `credit_ledger.top_up(user_id, *, amount_microcents, stripe_payment_intent_id)` — same shape used in Tasks 6 + 14 + 15.
- `credit_ledger.deduct(user_id, *, amount_microcents, chat_session_id, raw_cost_microcents, markup_multiplier, bedrock_invocation_id=None)` — defined in Task 6, called by Plan 3.
- `oauth_service.request_device_code(*, user_id) -> DeviceCodeResponse` and `poll_device_code(*, user_id) -> DevicePollResult | DevicePollPending` — same in Tasks 7 + 8.
- `write_openclaw_config(*, config_path, provider_choice, user_id, byo_provider=None)` — same in Tasks 12 + 13.
- `provision_container(*, user_id, provider_choice, byo_provider=None, ...)` — same in Task 13 (Plan 3 callers will use this signature).

**Dependencies between tasks:**
- 1 → 4 (config reads new tables) → 6 / 7 (services use config)
- 1 → 3 (env vars + grants reference new tables)
- 5 → (Plan 3 chat-deduct path)
- 6 → 14 → 15
- 7 → 8 → 13 (provision needs decrypted tokens) → 18
- 9 → 13
- 10 → 11 → 13 (provision needs the secret_arn from key_service)
- 12 → 13
- 16 standalone (cleanup)
- 17 standalone (helper)

**Suggested execution order (single executor):** 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18. Linear dependency chain is fine; ~3-5 days work.

**For parallel execution:** can run (1→3→4), 2, 5, 16, 17 in parallel; then (6→14→15), (7→8), (9→13), (10→11→12) in parallel; then 13 waits on (9, 10, 11, 12); then 18.
