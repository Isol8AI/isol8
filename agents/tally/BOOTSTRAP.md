# Tally — First Run Bootstrap

This file runs once on first activation. Complete all steps, then delete this file.

Tally does not interrogate the user during bootstrap. Accounting software, Stripe, and optional integrations are click-to-connect toggles in the Isol8 settings UI — Tally only mentions them when the user actually asks for something that needs them.

## Step 1: Validate Prerequisites

Required environment:
- `PLAID_CLIENT_ID` + `PLAID_SECRET` + `PLAID_ACCESS_TOKEN`
- `PERPLEXITY_API_KEY`
- `GCP_PROJECT_ID` + `GCP_LOCATION` + `PROCESSOR_ID` + `GCP_ACCESS_TOKEN` (Google Document AI)
- `OPENCLAW_HOOK_TOKEN`

That's it. No accounting software is required at bootstrap — the user connects one from the settings UI before asking Tally to post entries. If the user asks Tally to do ledger work before connecting accounting software, Tally responds per the click-to-connect pattern in AGENTS.md.

Optional:
- `STRIPE_API_KEY` (read-only scope — revenue tracking and payment matching)
- Stripe is strongly recommended but not a blocker if the business doesn't use Stripe

If required keys are missing, message the user via Slack. Do not proceed.

## Step 2: Connect Financial Accounts

### Bank Accounts (Plaid)
Verify Plaid connection. Pull a test transaction batch to confirm the feed is working. Store connection status in fast-io at `tally-config/activation`.

**Critical:** Verify Plaid is configured with read-only transaction access. Write operations (payments, transfers) must NOT be in scope.

### Stripe
If `STRIPE_API_KEY` is set, verify the connection by reading recent charges. Confirm read-only scope.

## Step 3: Initialize Default State

Create fast-io keys with defaults:
- `tally-config/connected-accounting` → `{}` (populated when the user connects accounting software in settings; the settings webhook writes this key)
- `tally-config/chart-of-accounts` → `{}` (populated when accounting software is connected and chart is read)
- `tally-config/approval-preferences` → `{"auto_confirm_vendors": [], "review_threshold": 500, "notification_channel": "#tally-approvals", "batch_routine": true}` (defaults; user adjusts later)
- `tally-config/accounting-policies` → `{}` (populated when user configures accruals, prepaids, depreciation)
- `tally-config/metric-thresholds` → `{"burn_rate_increase_pct": 15, "receivable_overdue_days": 30, "runway_months_min": 6, "gross_margin_compression_points": 3, "opex_increase_pct": 20}`
- `tally-config/benchmarks` → `{"ltv_cac": {"minimum": 3.0, "median_saas_2024": 3.6, "growth_equity": 4.0, "source": "SaaS Capital 2024", "applies_to": "SaaS companies"}, "burn_multiple": {"early_stage_avg": 3.4, "scale_25_50m": 1.4, "source": "Benchmarkit 2024", "applies_to": "Venture-backed companies"}, "gross_margin": {"healthy_saas": 70, "median_saas": 72, "source": "KeyBanc SaaS Survey 2024", "applies_to": "SaaS companies"}}`
- `tally-config/tax-deadlines` → `{"Q1": "04-15", "Q2": "06-15", "Q3": "09-15", "Q4": "01-15"}`
- `tally-learning/vendor-map` → `{}`
- `tally-learning/corrections` → `{}`

## Step 4: Verify Slack Channels

Verify or request creation of:
- `#tally-approvals` — Tier 2 approval requests, month-end journal entries
- `#tally-alerts` — anomaly flags, metric alerts, tax deadline reminders
- `#tally-digest` — Monday briefing, weekly summaries
- `#expenses` — plain language expense input from anyone in org

## Step 5: Set Up Google Sheets Dashboard

Create via gog:
- "Tally Dashboard" spreadsheet with tabs: Live (metrics), AR Aging, AP Aging, Cash Flow
- "Tally Weekly Reports" spreadsheet
- "Tally Monthly Close" spreadsheet
- "Tally Audit Archive" folder in Google Drive

## Step 6: Set Up Cron Jobs

```
openclaw cron add --name "tally-daily-feed" --cron "0 6 * * *" --tz "America/New_York" --session isolated --message "Run daily-feed pipeline" --thinking low --light-context

openclaw cron add --name "tally-weekly-summary" --cron "0 8 * * 1" --tz "America/New_York" --session isolated --message "Run weekly-summary pipeline" --thinking low --light-context

openclaw cron add --name "tally-month-end" --cron "0 9 L * *" --tz "America/New_York" --session isolated --message "Run month-end-close pipeline" --thinking low --light-context

openclaw cron add --name "tally-dashboard-update" --cron "0 */4 * * *" --session isolated --message "Update dashboard metrics" --thinking low --light-context

openclaw cron add --name "tally-audit-backup" --cron "0 2 1 * *" --tz "America/New_York" --session isolated --message "Monthly audit trail backup to Google Drive" --thinking low --light-context
```

Each cron job reads `tally-config/connected-accounting` at the start of its pipeline and handles the no-accounting-connected case gracefully.

## Step 7: Configure Webhooks

**Plaid transaction webhook** → `POST /hooks/agent`
```json
{"message": "New transactions from Plaid. Run daily-feed pipeline for new batch.", "name": "tally-plaid"}
```

**Stripe payment webhook** → `POST /hooks/agent`
```json
{"message": "New Stripe payment event. Match against open invoices.", "name": "tally-stripe"}
```

**Slack #expenses message** → `POST /hooks/agent`
```json
{"message": "New expense input from {{user}}: {{text}}. Run expense-intake pipeline.", "name": "tally-expense"}
```

## Step 8: Security Checks

Run skill-vetter against every skill. Tally handles the most sensitive data in the business — bank feeds, payment processor data, accounting records.

Special attention:
- `stripe-api` — ClawHavoc target. Vet from source code only.
- Verify Stripe is read-only scope
- Verify Plaid is read-only scope
- Enable sona-security-audit and bankofbots for runtime monitoring

## Step 9: Run Activation Check

Run `tally-activation-check.js`:
- Bank connection active ✓
- Accounting software connected (warning if not — click-to-connect)
- Chart of accounts loaded (warning if not — depends on accounting software)
- Approval preferences configured ✓

## Step 10: Announce Readiness

Post to `#tally-approvals`:

"Tally is live. I'm pulling transactions from your bank feeds daily, categorizing them, and queuing them for your review in #tally-approvals. When you connect your accounting software in settings, I'll start posting approved entries to your ledger."

## Step 11: Delete This File

Delete BOOTSTRAP.md after all steps are complete.
