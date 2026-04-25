# Flat-Fee BYO-LLM + Claude Credits — Design

**Date:** 2026-04-24
**Status:** Draft, awaiting user review
**Replaces:** Current 4-tier pricing (free / starter $40 / pro $75 / enterprise $165)
**Supersedes:** `docs/superpowers/plans/2026-04-13-free-tier-scale-to-zero.md` (no free tier in new model)

---

## 1. Summary

Pivot Isol8 from a 4-tier pricing ladder with a Bedrock-only LLM stack to a flat-fee
product with three signup paths:

1. **Sign in with ChatGPT** — $50/mo flat, 14-day free trial. User's ChatGPT
   subscription powers all inference via OpenClaw's `openai-codex` provider (OAuth).
2. **Bring your own API key** — $50/mo flat, 14-day free trial. User provides
   their own OpenAI or Anthropic API key; we wire it into the container.
3. **Powered by Claude** — $50/mo flat + prepaid Claude credits. We provide
   Claude (Sonnet 4.6 + Opus 4.7) via AWS Bedrock with a 1.4x markup on raw
   inference cost. No trial — credits required day one.

The $50 price covers the always-on container, multi-channel delivery,
and the standard agent toolset. Premium positioning vs. shared-compute
competitors (Cursor, Claude Pro at $20). See §3.4 for the full
justification and a roadmap addendum on future bundled features.

All three paths share the same hosted infrastructure: a per-user always-on
ECS Fargate container running OpenClaw, accessed via the existing WebSocket
chat UI. The free tier is killed. The Starter / Pro / Enterprise tiers are
killed. There is one container size for everyone (0.5 vCPU / 1 GB).

The change is justified by:

- **Product-thesis alignment.** "It's not a good product if you don't use the
  frontier models" — kill MiniMax / Qwen, expose only frontier (GPT-5.5, Claude
  Sonnet 4.6, Claude Opus 4.7).
- **Unit economics.** At ~$18/mo per always-on container COGS, $50 flat gives
  ~58% gross margin without depending on any LLM markup.
- **Cleaner code.** Eliminates per-tier model gating, the unmerged scale-to-zero
  plan, and the tier-vs-tier billing branching.

---

## 2. Motivation

### What's broken about the current model

- **MiniMax / Qwen are not the product anyone wants.** The free + starter tier
  experience is a degraded version of the product, which actively anti-sells
  the paid tiers.
- **Per-user always-on containers are wrong unit economics for a free tier.**
  Even with the planned scale-to-zero, free users cost real money (storage,
  cold-start engineering, abuse surface) for users who may never convert.
- **Bedrock-only locks us out of frontier OpenAI models** (GPT-5, GPT-5.5).
- **Tier ladders create decision paralysis at signup** without meaningfully
  segmenting customers.

### What the new model fixes

- **Frontier models only.** GPT-5.5 (via ChatGPT OAuth) and Claude Sonnet 4.6 /
  Opus 4.7 are the entire catalog.
- **One container size, one price.** No tier decision. Pick how you want to
  pay for inference; everything else is the same.
- **Clean separation of concerns.** $50 = container + product. LLM cost is
  user's problem (cards 1, 2) or pass-through with markup (card 3).
- **Multiple acquisition wedges.** ChatGPT power-users, Claude power-users,
  and "I'll just pay you" all have a clear front door.

---

## 3. Product model

### 3.1 The three cards

All cards: $50/mo, billed monthly via Stripe, single 0.5 vCPU / 1 GB always-on
ECS Fargate container, multi-channel (Telegram / Discord / WhatsApp), persistent
agent workspace on EFS, plus the bundled feature set in §3.4.

| Card | Pitch | LLM source | Trial | Day-one charge |
|------|-------|------------|-------|---------------|
| 1. Sign in with ChatGPT | "Use your ChatGPT subscription. GPT-5.5 included." | `openai-codex` (OAuth → ChatGPT quota) | 14 days, card on file | $0 (charged day 15) |
| 2. Bring your own API key | "Bring an OpenAI or Anthropic API key. Pay your provider direct, pay us $50 for hosting." | `openai` or `anthropic` (API key) | 14 days, card on file | $0 (charged day 15) |
| 3. Powered by Claude | "We run Claude for you. Pre-pay credits, no provider account needed." | `amazon-bedrock` (we own AWS creds) | None | $50 (credit purchase strongly suggested but not required at signup) |

### 3.2 Pricing rationale

**COGS per active user per month (at scale, ≥1000 MAU):**

| Cost line | Monthly per user |
|-----------|------------------|
| Fargate task (0.5 vCPU + 1 GB, 24/7) | $18.00 |
| EFS storage (~50 MB) | $0.02 |
| CloudWatch logs from container | $1.00 |
| Per-user DynamoDB writes | $0.05 |
| Stripe processing (~3% + $0.30 on $50) | $1.80 |
| Amortized fixed infra (NAT, ALB, NLB, backend Fargate, etc.) at 2700 MAU | $0.10 |
| **Total COGS** | **~$20.95** |

**Revenue:** $50 flat fee → **gross margin ~58%** before any credit-revenue from
card 3.

**At 2700 MAU goal:** $135k MRR from flat fees alone (2700 × $50). Gross
profit ~$79k/mo (2700 × $29). Add credit-revenue from card-3 users on top
(estimated $4-6k/mo at 30% adoption with average $20/mo of credits per buyer).

**Cards 1, 2:** All margin is in the flat fee. We don't see a cent of LLM cost.

**Card 3:** Flat fee margin + credit-revenue margin. Credit revenue =
`raw_bedrock_cost × 1.4`. Net margin = `raw_bedrock_cost × 0.4` per dollar
of inference (after AWS pays out). At average $20/mo of credits per card-3
user, that's an extra $5.71/mo per credit-buying user.

### 3.3 What we're killing

- The tier ladder: free / starter / pro / enterprise → gone.
- Per-tier model gating in `_TIER_ALLOWED_MODEL_IDS` → gone.
- The MiniMax M2.5 and Qwen3 VL 235B catalog entries → gone.
- The scale-to-zero plan (`docs/superpowers/plans/2026-04-13-free-tier-scale-to-zero.md`)
  → shelved (not needed; every container is paid always-on).
- Per-tier container sizing in `ecs_manager.py` → gone (single 0.5/1 size).
- The "$2 lifetime free budget" enforcement → gone.

### 3.4 What $50 buys (and why it's not $40)

Every $50 subscription includes the always-on per-user OpenClaw
container, multi-channel delivery (Telegram / Discord / WhatsApp),
persistent EFS workspace, and the standard agent toolset. The $10
delta over a $40 floor reflects premium positioning of dedicated
always-on agent infrastructure — competitors like Cursor ($20) and
Claude Pro ($20) ship shared compute, not per-user containers.

**Future bundled features** (not part of this pivot, listed for context):

- **Paperclip** (agent team orchestration). An existing design lives at
  `docs/superpowers/specs/2026-04-05-paperclip-integration-design.md`
  and is **out of scope for this pivot.** When Paperclip is implemented,
  bundling it cleanly requires solving its per-user-Postgres footprint —
  see the addendum at the end of this section for the validated approach.
- **Other future features** — listed in roadmap docs, not enumerated here.

The flat fee economics in §3.2 (COGS ~$20.95, **58% gross margin**)
assume the v1 product without Paperclip.

#### Addendum: Paperclip footprint solution (for whenever it's built)

Captured here so the work isn't re-discovered later. Paperclip's existing
spec assumes embedded Postgres in a per-user sidecar (+0.5 vCPU + 1 GB
per user → 22% margin if naïvely bundled at $50). The validated cheaper
path:

1. Patch Paperclip in `.worktrees/paperclip` to accept a `DATABASE_URL`
   env var, bypassing the embedded Postgres bootstrap. ~2-3 days.
2. Provision one shared Aurora Serverless v2 cluster (with `pgvector`)
   for all users. Per-user schemas + Postgres roles for isolation.
3. Resize the per-user task to 512 CPU / 2048 MB (slim Paperclip
   sidecar at 256/512 + OpenClaw's 256/512).

Result: +$3.27/user/mo (not +$18). 52% margin at $50. Aurora has a
~$45/mo floor — only switch on past ~100 MAU.

Paperclip is **explicitly not built in this spec.** This addendum
exists so the next person who picks up the Paperclip task starts from
the right architecture.

### 3.5 What's out of scope

- Annual pricing / discount tiers → punt to v2.
- Team / org billing (multiple seats per Stripe sub) → punt to v2. One user = one Stripe sub today.
- Container size upgrades / add-ons → punt; revisit if power users ask.
- New LLM providers beyond OpenAI / Anthropic / Bedrock → punt.
- Reseller / affiliate flows → punt.
- Migration of the 6 existing dev/prod containers → see §11. They're test accounts; we tear them down.

---

## 4. Architecture

### 4.1 High-level

The existing architecture is unchanged in shape:

```
Client → API Gateway WebSocket → FastAPI backend → per-user OpenClaw container (Fargate)
                                                       ↓
                                         Provider plugin (varies per user):
                                           - openai-codex (OAuth)
                                           - openai (API key)
                                           - anthropic (API key)
                                           - amazon-bedrock (we own creds)
```

What changes:

- `write_openclaw_config()` learns to emit the `openai-codex`, `openai`, and
  `anthropic` provider blocks in addition to `bedrock` and `ollama`.
- Container provisioning takes a `provider_choice` parameter (one of
  `chatgpt_oauth | openai_key | anthropic_key | bedrock_claude`) and writes the
  appropriate config + secrets.
- A new credit-ledger service tracks card-3 user balances and deducts on each
  Bedrock chat completion.
- A new auth-secret store holds OAuth tokens (for card 1) and BYO API keys
  (for card 2), encrypted with the existing Fernet key.

### 4.2 Provider config shapes (in `openclaw.json`)

**Card 1 — ChatGPT OAuth (`openai-codex`):**

OAuth tokens are not stored in `openclaw.json` — OpenClaw stores them in its
own auth profile dir. The container's openclaw.json only declares the model
default:

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "openai-codex/gpt-5.5",
        "subagent": "openai-codex/gpt-5.5"
      }
    }
  }
}
```

The OAuth login is performed once during onboarding via OpenClaw's
`models auth login --provider openai-codex` command, which we'll trigger
remotely (see §5.1). The resulting auth profile lives in the container's
home dir (persisted to EFS so it survives task restarts).

**Card 2a — OpenAI API key:**

```json
{
  "env": { "OPENAI_API_KEY": "sk-..." },
  "agents": {
    "defaults": {
      "model": {
        "primary": "openai/gpt-5.4",
        "subagent": "openai/gpt-5.4"
      }
    }
  }
}
```

The `OPENAI_API_KEY` is injected as an ECS task definition `secret` from AWS
Secrets Manager (one secret per user, named `isol8/{env}/user-keys/{user_id}/openai`).
We never write the key into `openclaw.json` directly.

**Card 2b — Anthropic API key:**

```json
{
  "env": { "ANTHROPIC_API_KEY": "sk-ant-..." },
  "agents": {
    "defaults": {
      "model": {
        "primary": "anthropic/claude-opus-4-7",
        "subagent": "anthropic/claude-sonnet-4-6"
      }
    }
  }
}
```

Same secrets-manager injection pattern.

**Card 3 — Bedrock-Claude (we own creds):**

```json
{
  "plugins": {
    "entries": {
      "amazon-bedrock": {
        "config": {
          "discovery": { "enabled": true, "region": "us-east-1" }
        }
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "amazon-bedrock/anthropic.claude-opus-4-7",
        "subagent": "amazon-bedrock/anthropic.claude-sonnet-4-6"
      }
    }
  }
}
```

AWS creds come from the ECS task role (existing setup). No per-user secret.

### 4.3 Backend changes

**Files touched:**

- `apps/backend/core/containers/config.py` — extend `write_openclaw_config()`
  with a `provider_choice` branch covering `chatgpt_oauth | openai_key |
  anthropic_key | bedrock_claude`. Delete the per-tier model whitelist
  (`_TIER_ALLOWED_MODEL_IDS`) and the MiniMax / Qwen catalog entries. Keep
  the `ollama` branch for LocalStack dev.
- `apps/backend/core/containers/ecs_manager.py` — collapse per-tier sizing
  (`_TIER_TASK_RESOURCES`) to a single `0.5 vCPU / 1024 MB` constant. Add
  `inject_user_secrets(user_id, provider_choice)` that registers a task
  definition with the correct Secrets Manager `secret` references for cards
  2a / 2b. Card 1 (OAuth) doesn't need a secret because the auth profile
  is on EFS. Card 3 doesn't need a secret because Bedrock uses the task role.
- `apps/backend/core/services/key_service.py` — extend to support `openai`
  and `anthropic` LLM keys (currently only tool keys: ElevenLabs, OpenAI TTS,
  Perplexity, Firecrawl). Same Fernet encryption path. Push to Secrets
  Manager on save (new behavior — today they're DynamoDB only).
- `apps/backend/core/services/oauth_service.py` (new) — drive the
  backend OAuth handshake with `auth.openai.com` (PKCE authorization-code
  flow, server-side code exchange), store tokens Fernet-encrypted in DDB,
  refresh-on-demand. **No container involvement** (per §5.1).
- `apps/backend/core/services/credit_ledger.py` (new) — DynamoDB-backed
  balance tracking. `get_balance`, `deduct`, `top_up`, `hard_stop_check`,
  `adjustment` (operator-only). See §6.
- `apps/backend/core/services/billing_service.py` — drop tier-aware checkout.
  Add `provider_choice` to checkout. Replace per-tier price IDs with one
  flat `STRIPE_FLAT_PRICE_ID`. Remove `set_metered_overage_item` (overage no
  longer exists; replaced by credit top-ups).
- `apps/backend/core/services/usage_service.py` — change the card-3 path:
  instead of `record_usage` writing to `usage_event` and conditionally
  reporting overage to Stripe Meters, it deducts from `credit_ledger`. Cards 1, 2:
  no usage tracking at all (we don't see their LLM cost).
- `apps/backend/routers/billing.py` — add `POST /credits/top_up` and
  `PUT /credits/auto_reload` endpoints. Drop the overage opt-in endpoint.
- `apps/backend/routers/settings_keys.py` — extend to support saving
  `openai` and `anthropic` LLM keys (in addition to tool keys).
- `apps/backend/routers/oauth.py` (new) — `POST /oauth/chatgpt/start` returns
  device code + verification URL; `POST /oauth/chatgpt/poll` polls for
  completion; `POST /oauth/chatgpt/disconnect` revokes.
- `apps/backend/main.py` — register new routers.

**Files / code we delete:**

- The `_TIER_ALLOWED_MODEL_IDS`, `_TIER_TASK_RESOURCES` maps.
- The `set_metered_overage_item` flow in `billing_service.py`.
- The `STRIPE_STARTER_PRICE_ID`, `STRIPE_PRO_PRICE_ID`, `STRIPE_ENTERPRISE_PRICE_ID`
  env vars and code paths. Replaced by `STRIPE_FLAT_PRICE_ID`.
- The MiniMax / Qwen catalog entries in `config.py`.
- `core/services/usage_poller.py` — the existing background poller for
  overage metering. Card 3 deducts synchronously on each chat; cards 1, 2
  don't track usage. Delete this file.
- `models/billing.py` — `usage_event` and `usage_daily` tables. Replaced by
  `credit_transactions` (see §6.1).

### 4.4 OpenClaw image

What we actually run in production is the **extended image** at
`877352799272.dkr.ecr.us-east-1.amazonaws.com/isol8/openclaw-extended:<env-tag>`,
built from `alpine/openclaw:2026.4.5` (the pinned upstream) plus
additional Linux skill binaries. Dockerfile lives at
`apps/infra/openclaw/`, build/push pipeline is
`.github/workflows/build-openclaw-image.yml`, tags pinned in
`openclaw-version.json` at the repo root.

No upstream version bump required for this pivot. The `openai-codex`,
`openai`, `anthropic`, and `amazon-bedrock` providers all ship in upstream
`alpine/openclaw:2026.4.5` and therefore in the extended image we run.

The extended image may need a small change in `apps/infra/openclaw/Dockerfile`:
verify that `openclaw models auth login --provider openai-codex` works in a
non-interactive way (device code flow) inside the container. If not, we add a
small wrapper script to the extended image that exposes a programmatic
device-code login command. Any change here ships through the extended-image
build pipeline (CI builds → ECR push → tag bump in `openclaw-version.json`
→ next CDK deploy).

---

## 5. Auth flows

**Design principle: configure provider FIRST, provision container SECOND.**
The user completes their auth choice (OAuth, API key, or credits) before
we spin up any Fargate task. This avoids paying for containers belonging
to abandoned signups, eliminates the "container exists but no auth" failure
state, and gives the user a faster first-paint (no waiting for ECS deploy).

When the container is finally provisioned (after trial Stripe Subscription
is created in §7.1), the backend pre-stages the user's auth artifacts on
their EFS access point and references any per-user secrets in the task
definition. The container starts already authenticated.

### 5.1 ChatGPT OAuth (card 1) — backend-driven, no container involved

OpenClaw stores its OpenAI-Codex auth as a portable JSON file at
`$CODEX_HOME/auth.json` (default `~/.codex/auth.json`) with shape:

```json
{
  "auth_mode": "chatgpt",
  "tokens": {
    "access_token": "<JWT>",
    "refresh_token": "<opaque>",
    "account_id": "<user>"
  }
}
```

The access token is a JWT with `exp` claim — no device binding, no DPoP,
no machine-specific data. Verified in upstream OpenClaw at
`extensions/openai/openai-codex-cli-auth.ts` (`readCodexCliAuthFile()`,
lines 16–48) and `openai-codex-auth-identity.ts` (lines 27–88) — the file
is read cold at container start with no other prerequisites.

**Flow (no container required, no localhost callback required):**

We use the **device-code flow** — officially supported by OpenAI as
`codex login --device-auth`, endpoint
`https://auth.openai.com/codex/device`. This avoids the localhost-1455
callback that pi-ai's library uses, which can't reach a Fargate
container or our backend domain.

1. **Onboarding step "Sign in with ChatGPT" clicked.** Frontend calls
   `POST /api/v1/oauth/chatgpt/start`.
2. **Backend POSTs to `https://auth.openai.com/codex/device`**
   (PKCE-flavored device-code) with our `client_id` (see §5.1.1 below
   for which client_id and why), receives `{device_code, user_code,
   verification_uri, expires_in, interval}`.
3. **Frontend displays the user code:** "Visit https://chatgpt.com/codex
   and enter `ABCD-1234`." User completes login in their browser.
4. **Backend polls** `https://auth.openai.com/oauth/token` every
   `interval` seconds until OpenAI returns `{access_token, refresh_token,
   account_id}` or the device_code expires.
5. **Backend stores the tokens encrypted** in DynamoDB
   (`isol8-{env}-oauth-tokens`, Fernet-encrypted, keyed by `user_id`).
6. **Onboarding wizard advances** to the next step (subscription /
   container provisioning). At this point we have a verified
   ChatGPT-Plus-or-better account on file.

#### 5.1.1 Which `client_id` do we use, and is it ours?

**We use `client_id="app_EMoamEEZ73f0CkXaXp7hrann"` — the same OAuth
client the official OpenAI Codex CLI uses, and the same one OpenClaw's
upstream auth library (`@mariozechner/pi-ai`) hardcodes.** Verified at
[`badlogic/pi-mono/packages/ai/src/utils/oauth/openai-codex.ts:25`](https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/utils/oauth/openai-codex.ts).

**This `client_id` is shared across every install of OpenClaw, every
install of pi-ai, and the official OpenAI Codex CLI.** That's by design
— OpenAI's docs at https://developers.openai.com/codex/auth list
"tools like OpenClaw" as supported third-party consumers of this OAuth
flow. We're not registering our own — we're using the public OAuth
client that the entire OpenClaw ecosystem already uses.

Implications:
- **No partner deal with OpenAI required.** This was previously listed
  as the spec's load-bearing risk; it's resolved.
- **No public secret stored on our side** — `client_id` is a public
  identifier (PKCE flow doesn't use a `client_secret`).
- **Risk if OpenAI ever revokes this `client_id`:** simultaneously breaks
  Codex CLI, OpenClaw, dozens of derivative tools, and us. Realistically
  OpenAI cannot revoke without breaking their own product, so the risk
  approaches zero.
- **Caveat for ChatGPT Enterprise users:** per OpenAI issue
  [openai/codex#9253](https://github.com/openai/codex/issues/9253),
  device-code login is gated by workspace-admin opt-in for Enterprise
  workspaces. ChatGPT Plus/Pro/Free personal accounts are not affected.
  We surface a clear error if the user hits this gate ("Your ChatGPT
  Enterprise admin has not enabled Device Code login. Use a personal
  ChatGPT account, or switch to BYO API key").

When the container is later provisioned, `core/containers/workspace.py`
writes the auth file to the user's EFS access point at
`/mnt/efs/users/{user_id}/codex/auth.json` (which OpenClaw mounts as
`$CODEX_HOME/auth.json`) — pre-staged and ready before OpenClaw boots.

**Token refresh:** OpenClaw's `openai-codex` provider auto-refreshes
in-container, using the `refresh_token` from the auth file and writing
the rotated tokens back to the same path. Refresh requires no backend
involvement once the file is staged. The backend's encrypted DDB copy
is a one-time bootstrap; we do **not** keep it in sync after staging.

**Disconnect / revoke:** `POST /api/v1/oauth/chatgpt/disconnect` →
deletes the EFS auth file via the existing config-patch RPC, deletes
the encrypted DDB row. User must re-OAuth or switch to a different
card to keep using the product.

**Risk surface for card 1 — meaningfully smaller than originally thought:**

- The `client_id` we use is shared with Codex CLI + every OpenClaw
  install (see §5.1.1). Revocation by OpenAI would simultaneously break
  their own product and the broader OpenClaw ecosystem; effectively
  zero risk.
- Device-code flow is officially documented by OpenAI as a supported
  Codex auth path. No partner deal needed.
- The remaining edge case: ChatGPT Enterprise users whose workspace
  admin has disabled device-code login. We surface a clear error and
  redirect them to card 2 (BYO API key) for the same OpenAI persona.

### 5.2 BYO API key (card 2) — no container required

1. **Onboarding step "Bring your own API key" clicked.** Frontend shows
   a chooser: "OpenAI" or "Anthropic" radio + key input.
2. **User pastes key.** Frontend `POST /api/v1/settings/keys` with
   `{ provider: "openai" | "anthropic", api_key: "sk-..." }`.
3. **Backend `key_service.py`:**
   - Validates the key with a 1-token test call to the provider's API.
     Reject on auth failure with a clear error.
   - Stores plaintext in AWS Secrets Manager at
     `isol8/{env}/user-keys/{user_id}/{provider}`. (No double-storage in
     DDB — Secrets Manager is the source of truth; DDB only stores the
     secret ARN reference.)
   - DDB stores `{ user_id, provider, secret_arn, created_at }` (no key
     material).
4. **Onboarding wizard advances** to the next step.

When the container is later provisioned, the backend registers a per-user
ECS task definition revision that references the secret as an env-var
`secret` (`secrets: [{ name: "OPENAI_API_KEY", valueFrom: "<arn>" }]` or
`ANTHROPIC_API_KEY`). ECS pulls the secret at task-start and injects it
into the container's environment — never seen by our backend.

**Key rotation:** User can replace the key any time. Backend updates the
Secrets Manager secret in place. The running container picks up the new
value on next task restart; for immediate effect we redeploy the service
(rolling, ~30s).

**Switching between OpenAI and Anthropic:** Same flow — re-submit with
the new provider. Old secret is deleted; backend re-registers the task
def with the new secret reference.

### 5.3 Bedrock-Claude (card 3) — no container required

User-side: nothing to set up. Onboarding wizard advances to the credit
top-up step (§6.2). When container is later provisioned, AWS creds come
from the ECS task role (existing infra setup). The only auth-adjacent
runtime step is the pre-chat balance check (§6.3).

---

## 6. Credit ledger system

### 6.1 Data model

New DynamoDB table `isol8-{env}-credits`:

| Attribute | Type | Notes |
|-----------|------|-------|
| `user_id` (PK) | string | Clerk user ID |
| `balance_microcents` | number | Atomic counter, ≥0 |
| `auto_reload_enabled` | bool | Default false |
| `auto_reload_threshold_cents` | number | If balance drops below this, auto-charge (default null) |
| `auto_reload_amount_cents` | number | Amount to charge on auto-reload (default null) |
| `last_top_up_at` | string (ISO) | Last successful top-up |
| `updated_at` | string (ISO) | |

New DynamoDB table `isol8-{env}-credit-transactions` (audit log, not load-bearing):

| Attribute | Type | Notes |
|-----------|------|-------|
| `user_id` (PK) | string | |
| `tx_id` (SK) | string | ULID |
| `type` | string | `top_up | deduct | adjustment` (refund handled as a manual `adjustment` per §6.5) |
| `amount_microcents` | number | Positive for top_up/adjustment, negative for deduct |
| `balance_after_microcents` | number | Balance after this tx |
| `stripe_payment_intent_id` | string? | For `top_up` |
| `chat_session_id` | string? | For `deduct` |
| `bedrock_invocation_id` | string? | For `deduct`, for support debugging |
| `raw_cost_microcents` | number? | For `deduct`, the un-marked-up cost |
| `markup_multiplier` | number? | For `deduct`, locked-in at deduction time (default 1.4) |
| `created_at` | string (ISO) | |

### 6.2 Top-up flow

1. User clicks "Add credits" in settings → modal asks for amount ($5 minimum,
   no max).
2. Frontend `POST /api/v1/billing/credits/top_up { amount_cents: int }`.
3. Backend creates a Stripe PaymentIntent (one-time charge, off-subscription).
4. Frontend confirms with Stripe.js.
5. Stripe webhook `payment_intent.succeeded` →
   `credit_ledger.top_up(user_id, amount_microcents, payment_intent_id)`.
6. Atomic UpdateExpression `ADD balance_microcents :amt` on the credits table.
7. Append a `top_up` row to `credit-transactions`.
8. Return updated balance to the frontend (via WebSocket push or SWR refetch).

### 6.3 Deduct flow (per chat)

Card 3 only. Other cards skip this entirely.

1. **Pre-chat balance check.** Before forwarding `chat.send` to the user's
   OpenClaw container, gateway checks `credit_ledger.get_balance(user_id)`.
   If balance ≤ 0, return error to frontend: `{ type: "error", code:
   "out_of_credits", message: "You're out of Claude credits. Top up to continue." }`.
   Frontend renders a "Top up now" CTA inline.
2. **Chat completes.** OpenClaw emits `chat.final` with token counts
   (`input_tokens`, `output_tokens`, model id). The existing event-transformation
   path in `connection_pool.py` already extracts these.
3. **Cost calc.** New helper `core/billing/bedrock_pricing.py` returns
   `cost_microcents = (input_tokens × in_rate) + (output_tokens × out_rate)`
   for the given Claude model. Rates are hardcoded constants (Sonnet 4.6,
   Opus 4.7) — when AWS changes pricing we update the constant and ship.
4. **Apply markup.** `marked_up = cost_microcents × 1.4` (constant).
5. **Atomic deduct.** UpdateExpression `ADD balance_microcents :neg` with a
   `ConditionExpression: balance_microcents >= :amt` to prevent overdraft.
6. **If condition fails** (raced with another chat): the chat already
   completed, so we accept a one-time small overdraft (≤ one chat's worth)
   and log a warning. Set balance to 0 instead of rejecting the deduction.
   This is rare and the alternative (refunding the chat) is worse UX.
7. **Append `deduct` row** to `credit-transactions`.
8. **If `auto_reload_enabled` and post-deduct balance < threshold:** queue an
   auto-reload Stripe charge (off-session, on the saved payment method).

### 6.4 Auto-reload flow

User toggles in settings: "When my balance drops below `$X`, charge `$Y`."

- Default off.
- Uses the saved payment method on the Stripe customer (set up at trial
  signup or on first top-up).
- Charged off-session; if it fails (3D Secure required, card declined),
  user gets an email and the auto-reload is paused until they re-enable.
- Hard cap: max one auto-reload per hour to prevent runaway charges if a
  bug causes rapid deduction.

### 6.5 Refunds — not offered

Credit purchases are non-refundable. State this clearly at top-up
("Credits are non-refundable. Auto-reload can be turned off at any
time.") and in the receipt email. Matches industry norm (Anthropic,
OpenAI, Twilio, Vercel credits all behave this way).

If a user reaches out with a legitimate complaint (wrong amount
charged, double-billed via a Stripe replay we missed), an operator can
issue a manual Stripe refund + a manual `refund`-type ledger
adjustment. No self-serve UI, no public endpoint. Keep the operational
surface small.

### 6.6 Hard stop on $0

When `balance_microcents == 0`:
- Pre-chat check returns the `out_of_credits` error.
- Frontend banner shows persistently.
- All other product surfaces (channels, cron, MCP) are also gated — no chat,
  no agent runs, no scheduled work.
- Container stays running (we still pay $18/mo for it; covered by the $50 flat fee).
- User can top up at any time → instant unblock on next chat.

---

## 7. Trial state machine (cards 1, 2)

State lives on the Stripe Subscription (`status` field, values:
`incomplete | trialing | active | past_due | canceled | unpaid`). The
user record stores only `stripe_customer_id` and `stripe_subscription_id`
— the rest is derived.

**Design principle: Stripe owns the trial lifecycle. We listen.**

Conversion, retry, expiry, and grace-period semantics all live in Stripe
via the native `trial_period_days` parameter on Subscriptions. The backend
runs no conversion cron, no daily DDB scan, no clock comparison. Our
`subscription.status` field is *derived* from Stripe webhooks, not
maintained independently — one source of truth.

### 7.1 Signup

1. User picks card 1 or 2 on landing page.
2. Sign up via Clerk (existing flow).
3. Onboarding step: "Add a payment method." Stripe Elements collects a
   payment method via SetupIntent (or PaymentElement equivalent); no charge.
4. Backend creates the Stripe Subscription **immediately**:
   ```python
   stripe.Subscription.create(
       customer=customer_id,
       items=[{"price": STRIPE_FLAT_PRICE_ID}],
       trial_period_days=14,
       default_payment_method=pm_id,
       automatic_tax={"enabled": True},
       payment_behavior="default_incomplete",  # surface 3DS if required
       payment_settings={
           "save_default_payment_method": "on_subscription",
           "payment_method_types": ["card"],
       },
       idempotency_key=f"trial_signup:{owner_id}",
   )
   ```
   Subscription is born in `status: trialing` with `trial_end` 14 days out.
   Backend stores `subscription_id` on the user record.
5. Provision container (existing `ecs_manager` flow).
6. Run the auth flow for the chosen card (OAuth or BYO key).
7. User is in.

### 7.2 During trial

- Same product as paid. No restrictions.
- In-app trial banner reads its end date from `subscription.trial_end`
  fetched from Stripe (cached locally), not from a duplicated DDB column.
- **Stripe sends the trial-end reminder email automatically** (configurable
  in dashboard, default ~7 days before end). For a branded reminder we
  also subscribe to the `customer.subscription.trial_will_end` webhook,
  which Stripe fires 3 days before the trial ends, and send our own email.
  No "day 7, day 12, day 14" cron — Stripe + one webhook handler covers it.
- User cancels via Customer Portal (or our settings UI calling the same
  Stripe API) → `customer.subscription.deleted` webhook fires → backend
  tears down container. No "no charge ever" bookkeeping needed; Stripe
  handles it because the trial period was active at cancellation.

### 7.3 Trial conversion (day 15) — handled by Stripe, observed by us

- **Stripe handles the conversion.** On day 15, Stripe attempts the
  first charge against the saved default payment method.
- On success: Stripe fires `invoice.payment_succeeded` and updates the
  subscription to `status: active`. The webhook handler updates the user's
  derived status. Container keeps running, no UX change.
- On failure: Stripe **Smart Retries** kick in (configurable in dashboard,
  default schedule retries over up to 21 days). During this window the
  subscription is in `status: past_due` — we surface a banner asking the
  user to update their payment method via the Customer Portal. Container
  stays running so an updating user can self-recover.
- When retries exhaust, Stripe fires `customer.subscription.deleted`
  (or transitions to `unpaid`, depending on dashboard config). Webhook
  handler tears down the container.

This eliminates the "cron job at 00:00 UTC" / `trial_status =
expired_no_card` / "3-day cliff" custom logic entirely. Stripe's
behavior is more permissive than our prior design (21-day retry vs
3-day cliff) — that's the user-friendly default and it's the right
choice.

### 7.4 Anti-abuse

- Block repeat trials via **Stripe Radar custom rule** (see §8.4):
  block when >2 trials per `payment_method_fingerprint` per 90 days.
  Stripe enforces this at payment-method-attach time — we don't need
  custom dedup code.
- Block disposable emails at signup via a maintained blocklist
  (frontend signup gate; cheaper than waiting for Stripe).
- Container is always-on during trial (no scale-to-zero) — abuse cost
  is bounded by Fargate per-task cost (~$10 over 14 days).

### 7.5 Backend state minimization

The user record stores **only** `stripe_customer_id` and
`stripe_subscription_id`. Trial-window booleans (`trial_status`,
`trial_ends_at`, `trial_started_at`) **do not** exist on our side — they
were a symptom of the old design where we tried to duplicate Stripe's
clock. Code that needs the current state queries the live subscription
(cached for ~60s) and reads `subscription.status` and
`subscription.trial_end`. This kills a class of "DDB and Stripe drifted"
bugs at the source.

---

## 8. Stripe integration

### 8.1 Products and prices (Stripe dashboard, set up manually before launch)

| Stripe object | Purpose |
|---------------|---------|
| Product: "Isol8 Hosted Agent" | The product |
| Price: `STRIPE_FLAT_PRICE_ID` ($50/mo recurring) | The flat fee, all 3 cards |
| Product: "Isol8 Claude Credits" | The credit product |
| (No price needed — credits use ad-hoc PaymentIntents.) | |

The existing `STRIPE_STARTER_PRICE_ID`, `STRIPE_PRO_PRICE_ID`,
`STRIPE_ENTERPRISE_PRICE_ID`, `STRIPE_METERED_PRICE_ID`, `STRIPE_METER_ID`
env vars are dropped from the new code. Leave the old Stripe products in
place for reference; archive them in the Stripe dashboard but don't delete.

### 8.2 Webhooks

Existing webhook router (`POST /api/v1/billing/webhooks/stripe`) handles:

- `customer.subscription.created` / `.updated` / `.deleted` → update user record.
- `invoice.payment_succeeded` / `.payment_failed` → update billing state.
- **New:** `payment_intent.succeeded` for credit top-ups → call
  `credit_ledger.top_up(...)`.
- **New:** `customer.subscription.trial_will_end` (fires 3 days before
  trial end) → optional branded reminder email to the user.

### 8.3 Failure modes

- Subscription payment fails after trial → Stripe Smart Retries (default
  4 retries over up to 21 days) → if all retries exhaust, Stripe fires
  `customer.subscription.deleted` → backend tears down container. During
  the retry window the subscription is `past_due` and we surface a banner
  prompting the user to update their payment method via Customer Portal.
- Subscription cancelled by user → Stripe fires `customer.subscription.deleted` →
  container torn down at end of current period (let them use what they paid for).
- Top-up fails → user sees error in modal, balance unchanged.
- Auto-reload fails → email user, pause auto-reload, balance unchanged.
- Refund: standard Stripe refund + balance adjustment.

### 8.4 Stripe surface audit — what we use, what's missing

Audit of every Stripe capability we either rely on today or should adopt
as part of this pivot.

**Already wired in the existing backend (keep, no change needed):**

| Stripe surface | Where | Notes |
|---|---|---|
| Customer (create/delete with race-deletion) | `billing_service.py:71-95` | Reuse for new flow |
| Checkout Session (subscription mode) | `billing.py:233` | Replace with SetupIntent for trial flow + direct subscription create on conversion (see §7) |
| **Customer Portal** | `billing.py:270` (`POST /billing/portal`) | **Keep.** Self-serve cancel / update payment method / view invoices / download receipts. Don't re-build any of this UI ourselves. |
| Subscription lifecycle webhooks | `billing.py:330-410` | Keep all 4 events |
| Webhook signature verification | `billing.py:338` | Keep |
| Smart Retries | Stripe-side, automatic | Keep |
| `stripe.api.latency` + `stripe.webhook.*` CloudWatch metrics | `billing_service.py` (`with timing(...)`, `put_metric`) | Keep — wrap any new Stripe calls in the same pattern |

**New surfaces this pivot adds (covered earlier in spec, listed for completeness):**

| Stripe surface | Where in spec | Notes |
|---|---|---|
| SetupIntent (trial card-on-file) | §7.1 | Replaces Checkout for trial signups |
| PaymentIntent (credit top-up) | §6.2 | One-shot, not subscription |
| `payment_intent.succeeded` webhook | §8.2 | Drives credit ledger top-up |
| `setup_intent.succeeded` webhook | §8.2 | Stores payment method id |
| Off-session charge (auto-reload) | §6.4 | Uses saved payment method |
| Refund API | §6.5 | Credit refunds within 30 days |

**Stripe surfaces we're NOT currently using and SHOULD adopt as part of this pivot:**

1. **Stripe Tax** — at $50/mo selling globally we owe sales tax in several
   US states (TX, NY, WA, etc. tax digital services) and VAT in EU/UK.
   Stripe Tax automates collection, registration tracking, and reporting.
   Enable in Stripe dashboard, set `automatic_tax: { enabled: true }` on
   the Subscription create call. Without this we're either (a) breaking
   the law or (b) eating tax out of margin.

2. **Stripe Radar** — fraud and abuse rules beyond disposable-email
   blocklists. Trial abuse with stolen cards / synthetic identities is the
   biggest risk in §7.4. Enable Radar's default rule set in the dashboard;
   add a custom rule blocking >2 trials per `payment_method_fingerprint`
   per quarter. Free with standard Stripe pricing.

3. **Idempotency keys on every Stripe write** — verified gap: 0 of the
   ~14 `stripe.X.create/modify/delete` calls in `billing_service.py`
   currently pass `idempotency_key=`. A retried API call (network blip,
   worker restart, FastAPI request retry) can double-create customers,
   double-charge cards, or double-refund. Fix: add an `idempotency_key`
   parameter to every Stripe write, derived from the operation + a
   stable id (e.g. `f"top_up:{payment_intent_id}"`,
   `f"customer_create:{owner_id}"`).

   *Note: the existing `idempotency` decorator at
   `core/services/idempotency.py` is HTTP-endpoint-level (in-memory
   60s TTL, caller-provided `Idempotency-Key` header, used by admin
   endpoints). It's not directly reusable here — Stripe needs the key
   as an SDK kwarg, not an inbound HTTP header — but the existing
   decorator stays in place for the admin surfaces it already protects.*

4. **Webhook event dedup** — verified gap: the handler at
   `routers/billing.py:330-410` calls `stripe.Webhook.construct_event`
   for signature verification but does NOT dedupe by `event.id`.
   Stripe replays webhooks on any non-2xx, on internal retries, and
   sometimes for at-least-once-delivery insurance. A replay of a
   `payment_intent.succeeded` would credit the user's balance twice.
   Fix: add a `processed_stripe_events` DDB table keyed by `event.id`
   with 30-day TTL; conditional `PutItem` (attribute-not-exists) at
   the top of the handler — if the put fails, return 200 immediately
   (already processed). This is small, mechanical, and load-bearing.

5. **Customer email sync** — when a Clerk user changes email, update
   the Stripe customer too (so receipts/invoices go to the right
   address). Hook into the Clerk `user.updated` webhook in
   `clerk_sync_service.py`, push to `stripe.Customer.modify(email=...)`.

6. **Stripe Billing Customer Portal config** — by default the portal
   exposes EVERYTHING (sub change, cancel, payment update, invoice
   history). For the new flow we only want: update payment method,
   cancel sub, view invoice history. Configure in the dashboard; lock
   down what users can self-serve.

**Explicitly deferred:** Stripe Promotion Codes / coupons. We can ship
the pivot without them; add later if a launch campaign needs one.

**Stripe surfaces we explicitly DON'T need (call out so future-us doesn't
re-investigate):** Sigma, Revenue Recognition, Invoicing for B2B,
Connect, Identity, Issuing, Treasury, Atlas, Climate. These are real
products but irrelevant to a flat-fee consumer SaaS.

---

## 9. Frontend changes

### 9.1 Landing page (`/`)

Replace the existing pricing section in `src/components/landing/Pricing.tsx`
with a 3-card layout:

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Sign in with    │  │ Bring your own  │  │ Powered by      │
│   ChatGPT       │  │    API key      │  │     Claude      │
│                 │  │                 │  │                 │
│   $50/month     │  │   $50/month     │  │   $50/month     │
│ + your sub      │  │ + your API bill │  │ + Claude credits│
│                 │  │                 │  │                 │
│ 14-day free trial│  │14-day free trial│  │ Pay-as-you-go   │
│                 │  │                 │  │ credits, 1.4x   │
│ ✓ GPT-5.5       │  │ ✓ OpenAI or     │  │ ✓ Sonnet 4.6   │
│ ✓ All channels  │  │   Anthropic     │  │ ✓ Opus 4.7     │
│ ✓ Always on     │  │ ✓ All channels  │  │ ✓ All channels │
│                 │  │ ✓ Always on     │  │ ✓ Always on    │
│  [Start trial]  │  │  [Start trial]  │  │  [Get started] │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

The CTA on each card preserves the choice into the signup flow via a query
param: `/sign-up?provider=chatgpt_oauth | byo_key | bedrock_claude`.

### 9.2 Onboarding wizard

Update `src/components/chat/ProvisioningStepper.tsx` to branch on
`provider_choice`:

- **chatgpt_oauth:** existing steps + new "Sign in with ChatGPT" step that
  shows the device-code flow (user code + verification URL + polling spinner).
- **byo_key:** existing steps + new "Add your API key" step with provider
  toggle (OpenAI / Anthropic) and key input.
- **bedrock_claude:** existing steps + new "Add Claude credits" step with
  amount picker and Stripe.js payment form.

### 9.3 Settings

New `/settings/llm` panel:
- Shows current provider choice and lets user switch.
- For card 1: "Connected to ChatGPT (OAuth)" with disconnect button.
- For card 2: shows masked key, lets user replace it or switch provider.
- For card 3: shows current credit balance, top-up button, auto-reload toggle.

Reuse the existing `panels/UsagePanel.tsx` for cards 1 and 2 to show
"We don't track your inference cost; check your provider for usage."
(Just a static message — they'll see real usage on OpenAI / Anthropic dashboards.)

For card 3, `UsagePanel.tsx` shows credit transaction history (top-ups, deductions).

### 9.4 Trial banner

New `<TrialBanner>` component shown above the chat UI when
`subscription.status == "trialing"`: "Your free trial ends in N days. You'll be charged $50 on `<date>`. [Cancel trial]" (the date and N come from `subscription.trial_end`).

### 9.5 Out-of-credits banner

For card 3 when balance ≤ 0: persistent banner blocking the chat input,
"You're out of Claude credits. [Top up now]".

---

## 10. Container provisioning changes

**Provisioning order:** auth setup (§5) and Stripe Subscription create
(§7.1) happen FIRST; container provisioning is the last step of
onboarding. By the time `provision_container` runs, the user already has:

- A `stripe_customer_id` and `stripe_subscription_id` (status `trialing`
  or `active`).
- A `provider_choice` of `chatgpt_oauth | byo_key | bedrock_claude`.
- For `chatgpt_oauth`: OAuth tokens stored encrypted in DDB
  (`isol8-{env}-oauth-tokens`).
- For `byo_key`: a Secrets Manager secret ARN for their OpenAI or
  Anthropic key.
- For `bedrock_claude`: nothing extra at user level.

`apps/backend/core/containers/ecs_manager.py`:

- Single task definition base, single CPU/memory (`512` / `1024`).
- New parameter `provider_choice` to `provision_container`. Affects:
  - Which Secrets Manager `secrets` to attach (card 2 only).
  - Which `openclaw.json` to write (via `write_openclaw_config`).
  - Whether to pre-stage an EFS auth file (card 1 only).

`apps/backend/core/containers/workspace.py`:

- New helper `pre_stage_codex_auth(user_id, oauth_tokens)` that writes
  `/mnt/efs/users/{user_id}/codex/auth.json` with the Codex auth file
  shape from §5.1. Called once during provisioning for card 1 users.
  Token rotation post-provision is handled in-container by OpenClaw.

`apps/backend/core/containers/config.py`:

- `write_openclaw_config(provider_choice, ...)` emits one of four blocks
  per §4.2.
- For card 1: sets `models.providers.openai-codex.codexHome` to the EFS
  auth path so OpenClaw reads the pre-staged auth file at boot.
- Delete the per-tier model whitelist and tier branching.
- Keep the `ollama` branch for LocalStack dev (LocalStack still uses
  Ollama as a local stand-in for Bedrock).

**Why this matters for cost:** abandoned signups (user clicks "Sign in
with ChatGPT," fails OAuth, leaves) cost us $0 in container time under
this design. Under the old design (provision-then-OAuth) we'd have paid
for ~30s+ of Fargate before knowing the user wasn't going to complete.
At 2700 MAU funnel volume that's real money — and avoids the "ghost
container" failure state where provisioning succeeds but OAuth never
does.

---

## 11. Existing dev/prod containers

The 6 existing containers (4 prod / 2 dev) are throwaway test accounts.
**No migration code.** On cutover:

1. Deploy the new backend.
2. Run `DELETE /api/v1/debug/provision` for each existing user to tear down
   their containers.
3. They re-onboard via the new flow if/when they sign in again.

If the user wants to preserve a specific test account's agent state, do it
manually before cutover (one-line script using the fleet PATCH endpoint to
push a card-3 / Bedrock-Claude config).

---

## 12. Testing strategy

**Unit tests:**
- `credit_ledger`: top-up, deduct, refund, hard-stop, auto-reload,
  overdraft race condition.
- `bedrock_pricing`: rate constants for each Claude model.
- `oauth_service`: PKCE state generation, code exchange, token storage,
  refresh-on-demand.
- `key_service`: validate, encrypt, push to Secrets Manager.
- `write_openclaw_config`: each provider branch produces correct JSON shape.

**Integration tests** (against LocalStack):
- Full provisioning flow for each of the 4 paths (`chatgpt_oauth`,
  `openai_key`, `anthropic_key`, `bedrock_claude`).
- Trial conversion: simulate Stripe trial-end via Stripe test clocks
  (advance customer's clock past `trial_end`); confirm webhook handlers
  drive the correct user-record state transitions and container teardown.
- Top-up via Stripe test mode → balance updated.
- Auto-reload trigger → second charge → balance updated.

**E2E (Playwright):**
- Update the existing `isol8-e2e-testing@mailsac.com` journey to cover the
  new flow: signup → pick card 3 (cheapest to test, no OAuth complexity) →
  add credits → send a chat → verify deduction.
- Add a second journey for card 2 with a test Anthropic key (use a real
  test key in CI Secrets).
- Skip card 1 OAuth in E2E (would require real ChatGPT account); cover
  manually.

**Load test:**
- Simulate 100 concurrent card-3 chats hitting the credit ledger to verify
  the atomic deduct holds under contention.

---

## 13. Rollout plan

1. **Phase 1 — Backend, no UI surface (week 1):**
   - Add `provider_choice` parameter end-to-end (config, ecs_manager, billing).
   - Default unspecified callers to `bedrock_claude` so old request shapes
     keep working through phase 1 (existing per-tier code paths still serve
     today's containers; new code is exercised only by tests).
   - Land the credit ledger schema + service but don't wire it to the chat path yet.
   - Stripe products created in dashboard.
   - Deploys to dev, no user-visible change.

2. **Phase 2 — Frontend onboarding wizard (week 2):**
   - New 3-card landing page.
   - New onboarding for each provider choice.
   - New settings panels.
   - Behind a feature flag (`NEW_PRICING_FLOW=true` env var), default off in prod.
   - Deploys to dev, internal QA.

3. **Phase 3 — Trial + credits wiring (week 3):**
   - Trial state machine.
   - Stripe SetupIntent.
   - Credit deduction on chat (gated to `bedrock_claude` users).
   - Auto-reload.
   - Out-of-credits hard stop.
   - Deploys to dev.

4. **Phase 4 — Cutover (week 4):**
   - Tear down the 6 existing test containers.
   - Flip `NEW_PRICING_FLOW=true` in prod.
   - Old `/sign-up` flow stops working; redirects to new landing.
   - Watch errors closely for 48 hours.
   - Old code paths (per-tier sizing, `usage_poller`, MiniMax/Qwen catalog,
     `STRIPE_*_PRICE_ID` env vars) deleted in a follow-up PR after one week
     of stability.

---

## 14. Open questions / risks

**Risks:**

- **Shared OAuth `client_id` revocation.** We use the public Codex CLI
  `client_id` (per §5.1.1). OpenAI revoking it would break their own
  CLI and the OpenClaw ecosystem in addition to us; treat as
  near-zero-probability, but not zero. Mitigation: card 2 (BYO API key)
  covers the same OpenAI persona with no shared-client risk — users can
  switch over in minutes.
- **ChatGPT Enterprise device-code gate.** Per
  [openai/codex#9253](https://github.com/openai/codex/issues/9253),
  Enterprise workspaces require admin opt-in to allow device-code
  login. Surface a clear error and route those users to card 2.
- **OAuth tokens expire / get revoked from the ChatGPT side.** We need a
  user-facing notification ("Your ChatGPT connection expired, reconnect
  to resume"). Backend detects this from a 401 in the next chat attempt
  and surfaces it to the frontend. Re-OAuth uses the same backend flow
  from §5.1 — no container restart needed.
- **Credit ledger race conditions.** Atomic UpdateExpression with
  `ConditionExpression` is the right primitive; documented above. Load test
  in phase 3.
- **Trial abuse** via disposable emails / repeated signups. Stripe customer
  dedup + disposable email blocklist + card-on-file should be enough.
  Monitor signup-to-conversion ratio; if it craters, add CAPTCHA at signup.

**Open questions deferred to v2:**

- Annual pricing / discount.
- Team / org accounts (multiple seats per Stripe sub).
- Container size add-ons.
- Self-serve refund UI for card 3 (admin-only at launch).
- Promo / coupon support.

---

## 15. Files & code surface summary

**New files:**
- `apps/backend/core/services/oauth_service.py`
- `apps/backend/core/services/credit_ledger.py`
- `apps/backend/core/billing/bedrock_pricing.py`
- `apps/backend/routers/oauth.py`
- `apps/backend/models/credit_ledger.py` (DDB schema)
- `apps/backend/models/processed_stripe_events.py` (DDB schema for webhook idempotency)
- `apps/frontend/src/components/landing/PricingThreeCard.tsx`
- `apps/frontend/src/components/chat/ChatGPTOAuthStep.tsx`
- `apps/frontend/src/components/chat/ByoKeyStep.tsx`
- `apps/frontend/src/components/chat/CreditsStep.tsx`
- `apps/frontend/src/components/control/panels/LLMPanel.tsx`
- `apps/frontend/src/components/control/panels/CreditsPanel.tsx`
- `apps/frontend/src/components/TrialBanner.tsx`
- `apps/frontend/src/components/OutOfCreditsBanner.tsx`

**Modified files:**
- `apps/backend/core/containers/config.py` (provider branch)
- `apps/backend/core/containers/ecs_manager.py` (single size, secrets injection)
- `apps/backend/core/services/key_service.py` (extend to LLM keys)
- `apps/backend/core/services/billing_service.py` (drop tier ladder; add idempotency keys + `automatic_tax` on every Stripe write)
- `apps/backend/core/services/usage_service.py` (delete; replaced by credit_ledger)
- `apps/backend/core/services/clerk_sync_service.py` (push email changes to `stripe.Customer.modify`)
- `apps/backend/routers/billing.py` (credit endpoints; webhook event dedup against `processed_stripe_events`)
- `apps/backend/routers/settings_keys.py` (LLM key support)
- `apps/backend/main.py` (register new routers)
- `apps/backend/core/config.py` (delete tier configs, add flat price id)
- `apps/frontend/src/components/landing/Pricing.tsx` → replaced by `PricingThreeCard.tsx`
- `apps/frontend/src/components/chat/ProvisioningStepper.tsx` (branch on provider)
- `apps/frontend/src/middleware.ts` (no change expected)

**Stripe dashboard configuration (manual, before phase 4 cutover):**
- Enable Stripe Tax; configure tax registrations for jurisdictions where MAU expected.
- Enable Stripe Radar default ruleset; add custom rule "block >2 trials per `payment_method_fingerprint` per 90 days".
- Configure Customer Portal: allow only "update payment method", "cancel subscription", "view invoice history". Disable plan-change UI.

**Deleted files:**
- `apps/backend/core/services/usage_poller.py`
- `apps/backend/models/billing.py` (`usage_event`, `usage_daily` tables)

**Infrastructure (CDK) changes:**
- `apps/infra/lib/stacks/database-stack.ts` — add `isol8-{env}-credits`,
  `isol8-{env}-credit-transactions`, `isol8-{env}-processed-stripe-events`
  (TTL-enabled, 30 days), and `isol8-{env}-oauth-tokens` (Fernet-encrypted
  ChatGPT OAuth bootstrap tokens, keyed by user_id) DynamoDB tables.
- `apps/infra/lib/stacks/container-stack.ts` — collapse per-tier task
  resource configs to a single `512 CPU / 1024 MB` base.
- IAM policy for backend Fargate task: `secretsmanager:CreateSecret`,
  `PutSecretValue`, `DeleteSecret` scoped to `isol8/{env}/user-keys/*`.

---

## 16. Approval

Awaiting user review. After approval, this spec feeds the writing-plans skill
to produce a phased implementation plan (one plan per rollout phase in §13).
