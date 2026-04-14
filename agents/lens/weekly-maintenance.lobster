name: weekly-maintenance
# Requirements 34: Confidence degradation + learning loop.
# Runs weekly on cron (Sunday evening).
# LLM calls: 1-2 (capability-evolver analysis, degradation summary)

steps:
  # Step 1: Load all previously verified findings
  - id: load-verified
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "lens-research/",
        "filter": "confidence_tier:verified OR confidence_tier:supported"
      }'

  # Step 2: Check source accessibility and content changes
  - id: check-sources
    command: >
      openclaw.invoke --tool agent-browser --action browse --args-json '{
        "urls": $load-verified.json.source_urls,
        "extract": "markdown",
        "check_only": true
      }'

  # Step 3: Load dismissal history for suppression
  - id: load-dismissals
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "lens-state/degradation-dismissals"}'

  # Step 4: Run confidence degradation check (Req 34)
  - id: degrade-check
    command: >
      exec --json --shell 'node scripts/lens-confidence-degrader.js'

  # Step 5: Alert on active downgrades
  - id: degrade-alert
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Summarize these confidence downgrades for the user. Be specific about which findings were affected and why. Adapt your tone — this is maintenance, not alarm. For suppressed downgrades, mention them briefly as informational.",
        "thinking": "off",
        "input": $degrade-check.json
      }'
    condition: $degrade-check.json.has_downgrades

  - id: notify-downgrades
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#lens-research",
        "text": "📉 WEEKLY CONFIDENCE REVIEW\n\n$degrade-alert.json || No downgrades this week.\n\nChecked: $degrade-check.json.total_checked findings. Active downgrades: $degrade-check.json.active_downgrades. Suppressed: $degrade-check.json.suppressed_downgrades."
      }'

  # Step 6: Update confidence tiers in stored research
  - id: update-stored
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "lens-state/degradation-log/{{date}}",
        "data": $degrade-check.json
      }'

  # Step 7: Capability-evolver — weekly learning
  - id: learn
    command: >
      openclaw.invoke --tool capability-evolver --action analyze --args-json '{
        "data": {
          "source_overrides": "from fast-io lens-state/source-overrides",
          "confidence_overrides": "from fast-io lens-state/confidence-overrides",
          "degradation_dismissals": "from fast-io lens-state/degradation-dismissals",
          "research_history": "from fast-io lens-state/historical-research"
        },
        "focus": "Which source tiers does the user consistently reclassify? Which confidence thresholds are too conservative or too loose for their domain? Which decomposition styles does the user prefer? Which monitoring alerts get consistently dismissed?"
      }'

  # Step 8: Update Google Sheets confidence tracker
  - id: update-sheets
    command: >
      openclaw.invoke --tool gog --action sheets-write --args-json '{
        "spreadsheet": "Lens Confidence Tracker",
        "sheet": "{{date}}",
        "data": $degrade-check.json
      }'

  # Step 9: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/weekly-maintenance",
        "data": {
          "action": "weekly_maintenance",
          "findings_checked": $degrade-check.json.total_checked,
          "downgrades": $degrade-check.json.active_downgrades,
          "suppressed": $degrade-check.json.suppressed_downgrades,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
