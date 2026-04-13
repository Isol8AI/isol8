name: daily-feed
# Requirements 16, 19-22, 45, 49: Daily bank feed processing pipeline.
# Runs daily on cron + on-demand when new transactions arrive via webhook.
# LLM calls: ~5/day (categorization for unknown vendors only)

steps:
  # Step 1: Activation check
  - id: activation
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key":"tally-config/activation"}'
      | exec --json --shell 'node scripts/tally-activation-check.js'

  # Step 2: Pull bank feed via Plaid
  - id: bank-feed
    command: >
      exec --json --shell 'curl -s -X POST "https://production.plaid.com/transactions/get" -H "Content-Type: application/json" -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"access_token\":\"$PLAID_ACCESS_TOKEN\",\"start_date\":\"{{yesterday}}\",\"end_date\":\"{{today}}\"}"'
    condition: $activation.json.pass

  # Step 3: Pull Stripe transactions
  - id: stripe-feed
    command: >
      openclaw.invoke --tool stripe-api --action list-charges --args-json '{
        "created_after": "{{yesterday}}",
        "limit": 100
      }'

  # Step 4: Load vendor mapping and chart of accounts
  - id: load-config
    command: >
      exec --json --shell 'node -e "
        const fs = require(\"fs\");
        process.stdout.write(JSON.stringify({
          vendor_map: {},
          chart_of_accounts: [],
          approval_preferences: {}
        }));
      "'
    # In practice, these read from fast-io — simplified for pipeline structure

  # Step 5: Categorize each transaction (Req 16)
  # Known vendors → deterministic mapping, unknown → llm-task
  - id: categorize-known
    command: >
      exec --json --shell 'node scripts/tally-categorization-engine.js'
    stdin: $bank-feed.stdout

  - id: categorize-unknown
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Categorize these bank transactions against the chart of accounts. For each, return the category, subcategory, vendor name, and confidence score. If uncertain, set confidence below 0.7.",
        "thinking": "off",
        "input": {"transactions": $STDIN, "chart_of_accounts": $load-config.json.chart_of_accounts},
        "schema": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "transaction_id": {"type": "string"},
              "vendor": {"type": "string"},
              "category": {"type": "string"},
              "subcategory": {"type": ["string", "null"]},
              "confidence_score": {"type": "number"}
            },
            "required": ["transaction_id", "vendor", "category", "confidence_score"]
          }
        }
      }'
    condition: $categorize-known.json.confidence_check.route != "standard_approval"

  # Step 6: Anomaly detection on all transactions (Req 22)
  - id: anomaly-scan
    command: >
      exec --json --shell 'node scripts/tally-anomaly-detector.js'
    stdin: $bank-feed.stdout

  # Step 7: Duplicate detection (Req 20)
  - id: duplicate-check
    command: >
      exec --json --shell 'node scripts/tally-reconciliation.js'

  # Step 8: Tax tagging (Req 45)
  - id: tax-tag
    command: >
      exec --json --shell 'node scripts/tally-tax-tracker.js'

  # Step 9: Batch approvals (Req 14)
  - id: batch-approvals
    command: >
      exec --json --shell 'node scripts/tally-approval-batcher.js'

  # Step 10: Post batch approval to Slack
  - id: notify-batch
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#tally-approvals",
        "text": "📊 DAILY TRANSACTION REVIEW\n\n**Quick confirm** ($batch-approvals.json.batch.count transactions, $${batch-approvals.json.batch.total_amount}):\n[Confirm All]\n\n**Individual review** ($batch-approvals.json.individual.count transactions):\n$batch-approvals.json.individual.entries\n\n**Anomaly flags:** $anomaly-scan.json.flagged_count\n**Duplicates found:** $duplicate-check.json.duplicates_found"
      }'

  # Step 11: Post anomaly alerts for warnings
  - id: anomaly-alerts
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#tally-alerts",
        "text": "⚠️ ANOMALY ALERTS\n\n$anomaly-scan.json.results"
      }'
    condition: $anomaly-scan.json.warning_count > 0

  # Step 12: Check quarterly tax deadline (Req 46)
  - id: tax-deadline
    command: >
      exec --json --shell 'node scripts/tally-tax-tracker.js'
    stdin: '{"mode": "deadline", "current_date": "{{today}}", "tax_rate": 0.25, "ytd_income": 0, "ytd_deductions": 0}'

  - id: tax-alert
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#tally-alerts",
        "text": "🏛️ TAX DEADLINE REMINDER\n\n$tax-deadline.json.alerts"
      }'
    condition: $tax-deadline.json.has_upcoming

  # Step 13: Update dashboard (Req 26)
  - id: update-dashboard
    command: >
      exec --json --shell 'node scripts/tally-metrics-calculator.js'

  - id: write-dashboard
    command: >
      openclaw.invoke --tool gog --action sheets-write --args-json '{
        "spreadsheet": "Tally Dashboard",
        "sheet": "Live",
        "data": $update-dashboard.json
      }'

  # Step 14: Post metric alerts (Req 28)
  - id: metric-alerts
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#tally-alerts",
        "text": "📉 METRIC ALERT\n\n$update-dashboard.json.alerts"
      }'
    condition: $update-dashboard.json.alerts.length > 0

  # Step 15: Audit log (Req 49)
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/daily-feed",
        "data": {
          "action": "daily_feed",
          "transactions_processed": $bank-feed.json.total,
          "categorized": $categorize-known.json.count,
          "anomalies_flagged": $anomaly-scan.json.flagged_count,
          "duplicates_found": $duplicate-check.json.duplicates_found,
          "tax_flags": $tax-tag.json.cpa_flags,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
