# Flat-Fee Pivot Testing Plan

> **Date:** 2026-04-27
> **Targets:** dev (`dev.isol8.co`) first, then prod (`app.isol8.co`)
> **Scope:** 3 provider paths × trial mechanics × billing flow × container lifecycle
> **Builds on:** PR #389, #391, #393, #396 (all merged)

## Pre-flight

### 0.0 — One-time Stripe setup (REQUIRED before any flow can complete)

The flat-fee subscription needs a Stripe Price configured. Without it, every onboarding flow fails with `STRIPE_FLAT_PRICE_ID not configured`.

- [ ] In Stripe **test mode** (dev): Products → create product "Isol8 Subscription" → Add price → Recurring monthly → $50.00 USD → save → copy the `price_xxx`
- [ ] In Stripe **live mode** (prod): same as above, separately
- [ ] Add as GitHub Actions repo secrets:
  - [ ] `STRIPE_FLAT_PRICE_ID_DEV` ← test-mode price
  - [ ] `STRIPE_FLAT_PRICE_ID_PROD` ← live-mode price
- [ ] Re-run the deploy workflow so the new env vars land on ECS

### 0.1 — Confirm deploy succeeded

- [ ] `gh run watch <run-id> --repo Isol8AI/isol8 --exit-status` → green
- [ ] `aws ecs describe-services --cluster isol8-prod-* --services isol8-prod-service-*` → `runningCount=1` and `taskDefinition` revision incremented post-merge
- [ ] CloudWatch `/ecs/isol8-prod` shows the backend booted without exceptions
- [ ] Dev counterpart: same checks against dev cluster
- [ ] Frontend: `dev.isol8.co` and `app.isol8.co` load — Vercel auto-deploy completed
- [ ] Sanity check the env var landed in the ECS task: `aws ecs describe-task-definition --task-definition isol8-dev-service --query 'taskDefinition.containerDefinitions[0].environment[?name==\`STRIPE_FLAT_PRICE_ID\`]'` → returns the Price ID, NOT empty string

### 0.2 — Dev env clean-slate (Optional, only if dev state is dirty)

Per CLAUDE.md "Clean-Slate Dev Reset" — wipes ECS services, EFS user dirs, DynamoDB tables, Stripe test customers, Clerk test users.

```bash
aws sso login --profile isol8-admin
# Then run the 5-step wipe from CLAUDE.md
```

**Skip if:** you can use a fresh Clerk account that's never signed in before. Faster than a full reset.

### 0.3 — Test accounts

- **DO NOT use** `isol8-e2e-testing@mailsac.com` — reserved for Playwright E2E gate
- Create 3 fresh Clerk accounts via `https://dev.isol8.co/sign-up`:
  - `flat-fee-test-oauth-<date>@<your-domain>` for ChatGPT path
  - `flat-fee-test-byo-<date>@<your-domain>` for BYO key path
  - `flat-fee-test-credits-<date>@<your-domain>` for Bedrock credits path
- Confirm each via the Clerk magic link

### 0.4 — Test resources you'll need

- ChatGPT account with active Plus/Team subscription (for OAuth flow)
- Real OpenAI API key (for BYO key flow) — create a throwaway one in [OpenAI dashboard](https://platform.openai.com/api-keys), revoke after testing
- Stripe test card `4242 4242 4242 4242`, expiry any future date, CVC any 3 digits

## Path 1: ChatGPT OAuth

### 1.1 — Onboarding

- [ ] Sign in to `dev.isol8.co` as the OAuth test account
- [ ] Land on `/onboarding`
- [ ] See the `ProviderPicker` 3-card layout (ChatGPT / BYO key / Bedrock credits)
- [ ] Click "Use my ChatGPT Plus/Team plan"
- [ ] **Expected (device-code flow):** wizard shows a `verification_uri` and a one-time `user_code` to copy. NOT a redirect to a `chat.openai.com/auth/...` URL.
- [ ] Open the verification URL in a new tab → enter the code → authorize Isol8 in the ChatGPT consent screen
- [ ] **Expected:** wizard auto-detects completion (it polls `/oauth/poll` every 5s) and advances to the billing step
- [ ] **Expected:** Stripe Checkout opens in the SAME tab (full-page redirect) for the $50/mo trial. NOT in-app Stripe Elements.
- [ ] Enter test card `4242 4242 4242 4242`, complete checkout
- [ ] **Expected:** Stripe redirects back to `dev.isol8.co/chat?checkout=success&provider=chatgpt_oauth`, wizard finishes, container provisions in background

**Verify in:**
- Stripe dashboard → Customers → new customer with subscription `status=trialing`, `trial_end` ~14 days out
- DDB `isol8-dev-users` table → user row has `provider_choice="chatgpt_oauth"`, `stripe_subscription_id`, `subscription_status="trialing"`
- DDB `isol8-dev-containers` table → container row exists, `status="running"` after ~30-60s
- EFS `/mnt/efs/users/<user_id>/codex/auth.json` exists (verify via ECS exec on backend task)
- CloudWatch `/isol8/dev/openclaw` shows the gateway booted without "Gateway start blocked" errors

### 1.2 — First chat

- [ ] On `/chat`, send "What's 2+2?"
- [ ] **Expected:** response streams back through openai-codex/gpt-5.5
- [ ] Verify in CloudWatch `/isol8/dev/openclaw` log group: see `chat.send` RPC arrives, model invocation logs `openai-codex/gpt-5.5`, `chat.final` event fires
- [ ] No credit deduction (OAuth path doesn't touch credit ledger — confirm DDB `isol8-dev-billing-accounts` row's `credits_balance_microcents` unchanged)

### 1.3 — Settings panel

- [ ] Navigate to `/chat?panel=llm` (LLMPanel)
- [ ] **Expected:** shows "Connected to ChatGPT" + a Disconnect button
- [ ] Click Disconnect
- [ ] **Expected:** OAuth disconnected, `auth.json` removed from EFS, `provider_choice` cleared on user row, redirected to onboarding to re-pick

### 1.4 — Trial banner

- [ ] At top of `/chat`, see "Trial: X days left" banner (computed by Stripe, NOT by us)
- [ ] Click "Manage" → navigates to `/settings?panel=billing` (CreditsPanel)
- [ ] **Expected:** see Stripe Customer Portal link, current trial status, no credit balance displayed (OAuth users don't have credits)

## Path 2: BYO API Key

### 2.1 — Onboarding

- [ ] Sign in as the BYO test account
- [ ] Click "Bring your own API key"
- [ ] Pick OpenAI provider (or Anthropic — test both eventually)
- [ ] Paste your throwaway `sk-...` key
- [ ] **Expected:** key encrypted with Fernet + KMS, stored in DDB `isol8-dev-api-keys`
- [ ] **Expected:** Stripe Checkout opens (full-page redirect) for the $50/mo trial
- [ ] Enter test card `4242 4242 4242 4242`, complete checkout
- [ ] **Expected:** Stripe redirects back to `dev.isol8.co/chat?checkout=success&provider=byo_key`, trial active

**Verify in:**
- DDB `isol8-dev-users` → `provider_choice="byo_key"`, `byo_provider="openai"`
- DDB `isol8-dev-api-keys` → row exists with `provider="openai"`, encrypted ciphertext (NOT plaintext)
- ECS task definition for the user's container has the BYOK secret reference: `OPENAI_API_KEY` from `secretsmanager:isol8-dev/byo-key/<user_id>`
- EFS `/mnt/efs/users/<user_id>/openclaw.json` should NOT contain the API key — only `agents.defaults.model.primary = "openai/gpt-5.4"`

### 2.2 — First chat

- [ ] Send "What's the capital of France?"
- [ ] **Expected:** response streams via openai/gpt-5.4
- [ ] Verify token counts in `chat.final` event match what OpenAI billed (compare against your own OpenAI dashboard)
- [ ] No credit deduction (BYO users don't touch our credit ledger)

### 2.3 — Key rotation

- [ ] Go to `/chat?panel=llm`
- [ ] Click "Rotate key"
- [ ] Paste a new `sk-...` key
- [ ] **Expected:** old Secrets Manager secret value updated; ECS does NOT need re-deploy because secret is referenced by ARN
- [ ] Send another chat — should work with new key (verify by revoking the OLD key in OpenAI dashboard and confirming the chat still works)

**Edge case to verify:** key rotation while container is running picks up the new key (Secrets Manager auto-rotation does NOT happen by default — task continues with cached secret value until restart). **TODO: confirm whether secret value caching means the task uses the OLD key until restart.** If yes, document as a known limitation in the LLMPanel ("changes apply after container restart").

### 2.4 — Invalid key

- [ ] Rotate key to a definitely-invalid value `sk-thisisnotreal12345`
- [ ] Restart container (TBD: is there a restart button? if not, wait for next chat to fail)
- [ ] Send a chat
- [ ] **Expected:** chat fails with a friendly error message ("Your API key is invalid — update it in settings"), NOT a 500 stack trace

## Path 3: Bedrock Claude with Credits

### 3.1 — Onboarding

- [ ] Sign in as the Credits test account
- [ ] Click "Pay $1/credit"
- [ ] **Expected:** Stripe Checkout opens (full-page redirect) for the $50/mo trial. The CreditsStep also shows in-app `<Elements>` to optionally pre-load credits during onboarding (this is the ONE place Stripe Elements is used in the flow).
- [ ] Either complete the in-app top-up form (Stripe Elements) OR skip and complete checkout with the trial only
- [ ] **Expected:** trial subscription `trialing`, container provisions with `provider_choice="bedrock_claude"`

**Verify in:**
- DDB `isol8-dev-users` → `provider_choice="bedrock_claude"`
- DDB `isol8-dev-billing-accounts` → `credits_balance_microcents > 0` (initial trial credit?)
- ECS task IAM role can `bedrock:InvokeModelWithResponseStream` for Anthropic Claude models
- EFS openclaw.json `plugins.entries.amazon-bedrock.config.discovery.enabled = true`, `agents.defaults.model.primary = "amazon-bedrock/anthropic.claude-opus-4-7"`

### 3.2 — First chat

- [ ] Send "Tell me a 2-paragraph story about a robot."
- [ ] **Expected:** streams via amazon-bedrock/anthropic.claude-opus-4-7
- [ ] **After `chat.final`**: credit ledger deducts `(input_tokens × input_price + output_tokens × output_price) × 1.4 markup`
- [ ] Verify in DDB `isol8-dev-billing-accounts`: `credits_balance_microcents` decreased by the expected amount (compute manually from the token counts in the `chat.final` event)

### 3.3 — Out-of-credits gate

- [ ] Manually drain credits via DDB console: set `credits_balance_microcents = 0`
- [ ] Send a chat
- [ ] **Expected:** pre-chat gate blocks with "You're out of credits — top up to continue"
- [ ] `OutOfCreditsBanner` appears at top of chat
- [ ] Banner CTA → `/chat?panel=credits`
- [ ] **Expected:** CreditsPanel shows a top-up form. **Known gap (P0-2 from pre-test review):** the panel currently stubs the PaymentIntent flow and does not render Elements — top-up from settings panel is broken. Test only the onboarding-time top-up via CreditsStep until this is fixed in a follow-up.

### 3.4 — Top-up

- [ ] In CreditsPanel, enter $20, submit Stripe card
- [ ] **Expected:** top-up succeeds, `credits_balance_microcents` increases by $20 worth (= 20_000_000 microcents)
- [ ] Banner disappears, chat works again
- [ ] Send a chat to confirm deduction works post-topup

### 3.5 — Concurrent top-up race

- [ ] (Manual injection) Set credits to a near-empty amount
- [ ] Trigger 2 concurrent chats AND a top-up payment_intent webhook within 1 second
- [ ] **Expected:** both deducts AND the top-up are reflected; no balance lost. (This tests the conditional-write fix from PR #393 round 2.)

## Cross-path verification

### 4.1 — Provider switching mid-trial

- [ ] On the OAuth account, disconnect ChatGPT
- [ ] Re-enter onboarding
- [ ] Pick BYO key instead, paste OpenAI key
- [ ] **Expected:** container reprovisions with new openclaw.json, secret ARN updated
- [ ] Send a chat → routes through openai/gpt-5.4 (NOT openai-codex)

### 4.2 — Trial conversion

This requires Stripe test clock manipulation (advance test clock to trial_end + 1).

- [ ] In Stripe test dashboard: find the trial customer's subscription, attach to a test clock, advance clock by 14 days + 1 hour
- [ ] **Expected:** Stripe webhook `customer.subscription.updated` fires with `status=active`, our handler updates DDB `subscription_status="active"`
- [ ] Trial banner disappears, $50/mo invoice appears in customer portal
- [ ] Chat continues to work uninterrupted

### 4.3 — Trial cancellation before conversion

- [ ] On a trial account, navigate to billing portal
- [ ] Click "Cancel subscription"
- [ ] Confirm cancellation
- [ ] **Expected:** webhook fires, `subscription_status` cleared, `cancel_at_period_end=true`
- [ ] At trial end, container should stop (or stay until end of period — verify the actual behavior)
- [ ] User can re-subscribe → starts a NEW trial? Or no? **TODO: verify intended behavior.**

## Container lifecycle (always-on)

### 5.1 — No scale-to-zero

- [ ] Leave a paid account idle for 10 minutes (>5 min old reaper threshold)
- [ ] **Expected:** container `desiredCount=1` and `runningCount=1` STILL
- [ ] No `stop_user_service` calls in CloudWatch
- [ ] Reload `/chat`, send a message — instant response, NO cold-start latency

### 5.2 — Cron jobs

- [ ] On a paid account, create a cron job via the CronPanel: e.g. "every minute echo hello"
- [ ] **Expected:** job runs every minute, output appears in chat history
- [ ] Survives 5+ minutes of zero user activity (proves no scale-to-zero)

### 5.3 — Channel binding

- [ ] On a paid account, bind a Telegram bot
- [ ] DM the bot from Telegram
- [ ] **Expected:** message appears in /chat as a session, agent responds, response goes back to Telegram
- [ ] (Same for Discord and Slack if bandwidth permits)

## Edge cases / known concerns

### 6.1 — BYOK secret rotation drift (Tech debt #397)

- [ ] Rotate a BYOK user's key (changes the Secrets Manager secret VALUE but not the ARN)
- [ ] Stop their container via admin endpoint
- [ ] Cold-start via `start_user_service`
- [ ] Verify whether the new key is injected (it should be, since ECS pulls by ARN at task start, but the container.byo_secret_arn drift check from #397 hasn't been added yet)
- [ ] **Expected outcome:** works correctly today because secret ARN is stable per-user; document as a known caveat if it breaks

### 6.2 — Stripe webhook duplicate delivery (Tech debt #397)

- [ ] In Stripe test dashboard, manually re-deliver a `customer.subscription.created` webhook event
- [ ] **Expected:** dedup logic catches it, no duplicate DDB writes
- [ ] Verify per the P1 finding in #397: dedup mark is set BEFORE side effects, so a side-effect failure on first delivery would silently lose the event. Reproduce this by failing a side effect (e.g., temporarily break DDB) and seeing if the retry is rejected.

## Rollout to prod

After dev smoke passes:

- [ ] Manual sanity check on `app.isol8.co` (use a real card, refund afterward)
- [ ] Stripe meter dashboard shows the metered overage product is set up correctly
- [ ] Free-tier users (if any remain): grandfather them or migrate? **TODO: decide.**
- [ ] Plan 3 Task 15: tear down 6 legacy test containers
- [ ] Plan 3 Task 16: delete deprecated env vars + code paths

## Sign-off

Before declaring this feature done:

- [ ] All 3 paths (OAuth, BYO key, credits) confirmed working in dev
- [ ] All 3 paths confirmed working in prod with a real card transaction
- [ ] Tech-debt issue #397 has at minimum the P1 Stripe findings fixed
- [ ] Feature flag (if any) is set to "on for everyone"
- [ ] Marketing/landing page reflects the new pricing
- [ ] Old free-tier users have been notified of the change (or grandfathered)
