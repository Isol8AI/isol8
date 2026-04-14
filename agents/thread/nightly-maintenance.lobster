name: nightly-maintenance
# Requirements 13, 14, 22, 27: Preference learning + follow-up check + triage calibration.
# Runs nightly on cron.
# LLM calls: 1 (capability-evolver weekly, otherwise 0)

steps:
  # Step 1: Load message history for preference learning
  - id: load-history
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "thread-contacts/",
        "include_history": true
      }'

  # Step 2: Update channel preference model for all contacts (Req 13, 14)
  - id: learn-preferences
    command: >
      exec --json --shell 'node scripts/thread-preference-learner.js'

  # Step 3: Store updated preferences
  - id: store-preferences
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "thread-contacts/preferences-batch",
        "data": $learn-preferences.json.preferences
      }'

  # Step 4: Follow-up threshold check (Req 21, 22)
  - id: load-outbound
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "thread-outbound/",
        "filter": "awaiting_response:true"
      }'

  - id: load-inbound-recent
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "thread-stream/",
        "filter": "timestamp:last_7d"
      }'

  - id: check-followups
    command: >
      exec --json --shell 'node scripts/thread-followup-tracker.js'

  # Step 5: Surface overdue follow-ups as Slack suggestions
  - id: followup-suggestions
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#thread-inbox",
        "text": "📬 FOLLOW-UP SUGGESTIONS\n\n$check-followups.json.overdue"
      }'
    condition: $check-followups.json.overdue_count > 0

  # Step 6: Weekly capability-evolver (runs Sunday only)
  - id: learn-triage
    command: >
      openclaw.invoke --tool capability-evolver --action analyze --args-json '{
        "data": {
          "triage_overrides": "from fast-io thread-state/triage-overrides",
          "routing_accuracy": "from fast-io thread-state/routing-outcomes",
          "briefing_engagement": "from fast-io thread-state/briefing-actions",
          "injection_dismissals": "from fast-io thread-state/safe-senders"
        },
        "focus": "Which triage weight adjustments would better match the users actual priorities? Which channel routing predictions were wrong? Which briefing items did the user act on vs defer? Which injection flags were false positives?"
      }'

  # Step 7: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "thread-audit/{{date}}/nightly-maintenance",
        "data": {
          "action": "nightly_maintenance",
          "preferences_updated": $learn-preferences.json.contacts_updated,
          "followups_overdue": $check-followups.json.overdue_count,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
