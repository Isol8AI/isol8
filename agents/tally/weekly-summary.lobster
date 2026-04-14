name: weekly-summary
# Requirements 29, 38: Monday financial summary with proactive intelligence.
# Runs Monday 8 AM on cron.
# LLM calls: 0 (summary via summarize CLI, conditional trend research via Perplexity deterministic search)

steps:
  # Step 1: Calculate all metrics
  - id: calculate-metrics
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "tally-state/financial-data"}'
      | exec --json --shell 'node scripts/tally-metrics-calculator.js'

  # Step 2: Load week's transaction summary
  - id: load-transactions
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "audit/",
        "filter": "action:daily_feed AND timestamp:last_7d"
      }'

  # Step 3: Load week's approvals
  - id: load-approvals
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "tally-approvals/",
        "filter": "timestamp:last_7d"
      }'

  # Step 4: Load categorization accuracy
  - id: accuracy-check
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "tally-learning/corrections"}'
      | exec --json --shell 'node scripts/tally-categorization-engine.js'
    stdin: '{"mode": "accuracy", "period_days": 60}'

  # Step 5: Load tax data
  - id: tax-status
    command: >
      exec --json --shell 'node scripts/tally-tax-tracker.js'
    stdin: '{"mode": "deadline"}'

  # Step 6: Check for 3+ month trends — proactive intelligence (Req 38)
  - id: trend-detection
    command: >
      exec --json --shell 'node -e "
        const metrics = JSON.parse(process.env.METRICS || \"{}\");
        const trends = [];
        // Check gross margin trend
        if (metrics.gross_margin_history && metrics.gross_margin_history.length >= 3) {
          const last3 = metrics.gross_margin_history.slice(-3);
          const declining = last3[0] > last3[1] && last3[1] > last3[2];
          if (declining) trends.push({metric: \"gross_margin\", direction: \"declining\", months: 3, values: last3});
        }
        // Check burn rate trend
        if (metrics.burn_rate_history && metrics.burn_rate_history.length >= 3) {
          const last3 = metrics.burn_rate_history.slice(-3);
          const increasing = last3[0] < last3[1] && last3[1] < last3[2];
          if (increasing) trends.push({metric: \"burn_rate\", direction: \"increasing\", months: 3, values: last3});
        }
        process.stdout.write(JSON.stringify({trends, has_trends: trends.length > 0}));
      "'

  # Step 7: Research trend context if detected (Req 38)
  - id: trend-research
    command: >
      exec --shell 'curl -sS https://api.perplexity.ai/chat/completions \
        -H "Authorization: Bearer $PERPLEXITY_API_KEY" \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"sonar\",\"messages\":[{\"role\":\"user\",\"content\":\"SaaS company $trend-detection.json.trends[0].metric benchmark 2025 2026 stage\"}]}" \
        | node -e "
          let d=\"\";process.stdin.on(\"data\",c=>d+=c);process.stdin.on(\"end\",()=>{
            const r=JSON.parse(d);
            const content=r.choices?.[0]?.message?.content||\"\";
            const citations=r.citations||[];
            process.stdout.write(JSON.stringify({content,citations,source:\"perplexity\"}));
          });"'
    condition: $trend-detection.json.has_trends

  # Step 8: Capability-evolver — correction pattern analysis (Req 10)
  - id: correction-analysis
    command: >
      openclaw.invoke --tool capability-evolver --action analyze --args-json '{
        "data": $load-approvals.json,
        "focus": "vendor categorization corrections — which vendors are consistently overridden and what the correct mapping should be"
      }'

  # Step 9: Update vendor mapping from corrections
  - id: update-mapping
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "tally-learning/vendor-map",
        "data": $correction-analysis.json.updated_mapping
      }'

  # Step 10: Compile summary (zero LLM — summarize CLI)
  - id: compile-summary
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": {
          "metrics": $calculate-metrics.json,
          "transactions_this_week": $load-transactions.json,
          "approvals_this_week": $load-approvals.json,
          "accuracy": $accuracy-check.json,
          "tax_deadlines": $tax-status.json,
          "trends": $trend-detection.json,
          "trend_research": $trend-research.json,
          "alerts": $calculate-metrics.json.alerts
        },
        "format": "monday-financial-briefing"
      }'

  # Step 11: Write to Google Sheet
  - id: write-sheet
    command: >
      openclaw.invoke --tool gog --action sheets-write --args-json '{
        "spreadsheet": "Tally Weekly Reports",
        "sheet": "{{date}}",
        "data": $calculate-metrics.json.metrics
      }'

  # Step 12: Post to Slack
  - id: notify
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#tally-digest",
        "text": "📊 MONDAY FINANCIAL BRIEFING — {{date}}\n\n$compile-summary.stdout\n\nDashboard: $write-sheet.json.url"
      }'

  # Step 13: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/weekly-summary",
        "data": {
          "action": "weekly_summary",
          "metrics": $calculate-metrics.json.metrics,
          "accuracy": $accuracy-check.json,
          "trends_detected": $trend-detection.json.has_trends,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
