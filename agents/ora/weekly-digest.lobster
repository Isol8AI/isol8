name: weekly-digest
# Requirements 36, 37, 38, 39: Monday calendar intelligence digest.
# Runs Monday 7:30 AM on cron.
# LLM calls: 2 (digest narrative, pattern contextualization)

steps:
  # Step 1: Read connected calendar config
  - id: load-connected
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/connected-calendars"}'

  # Step 2: Pull past week's events from every connected calendar
  - id: load-gog-week
    command: >
      openclaw.invoke --tool gog --action calendar-list-events --args-json '{
        "calendar_id": "primary",
        "date_range": "last_7d"
      }'
    condition: $load-connected.json.gog.connected == true

  - id: load-ms365-week
    command: >
      openclaw.invoke --tool ms365 --action calendar-list-events --args-json '{
        "date_range": "last_7d"
      }'
    condition: $load-connected.json.ms365.connected == true

  - id: load-caldav-week
    command: >
      openclaw.invoke --tool caldav-calendar --action list-events --args-json '{
        "date_range": "last_7d"
      }'
    condition: $load-connected.json.caldav.connected == true

  - id: load-calctl-week
    command: >
      openclaw.invoke --tool calctl --action list-events --args-json '{
        "date_range": "last_7d"
      }'
    condition: $load-connected.json.calctl.connected == true

  # Step 3: Merge into a unified event set
  - id: merge-week
    command: >
      exec --json --shell 'node scripts/ora-availability-merger.js'
    stdin: '{
      "mode": "merge_busy",
      "events_by_source": {
        "gog": $load-gog-week.json.events,
        "ms365": $load-ms365-week.json.events,
        "caldav": $load-caldav-week.json.events,
        "calctl": $load-calctl-week.json.events
      },
      "block_all_day": true
    }'

  # Step 4: Load prior weeks for trend comparison
  - id: load-prior
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "ora-analytics/weekly/",
        "limit": 4
      }'

  # Step 5: Load scheduling rules
  - id: load-rules
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/scheduling-rules"}'

  # Step 6: Run full calendar analytics (Req 36, 37, 38, 39)
  - id: analyze
    command: >
      exec --json --shell 'node scripts/ora-calendar-analytics.js'
    stdin: '{
      "events": $merge-week.json.busy_intervals,
      "prior_weeks": $load-prior.json,
      "rules": $load-rules.json
    }'

  # Step 7: Contextualize patterns — LLM
  - id: contextualize-patterns
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Explain these calendar patterns to the user in human terms. Do not just state the pattern — explain WHY it is happening based on the calendar data (which meetings are driving the change, which recurring commitments are accumulating). Suggest specific actions. Adapt your tone to how the user communicates.",
        "thinking": "off",
        "input": {
          "patterns": $analyze.json.patterns,
          "recurring_overruns": $analyze.json.recurring_overruns,
          "by_type": $analyze.json.by_type,
          "comparison": $analyze.json.comparison
        },
        "schema": {
          "type": "object",
          "properties": {
            "pattern_narratives": {"type": "array", "items": {"type": "string"}},
            "overrun_suggestions": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["pattern_narratives"]
        }
      }'
    condition: $analyze.json.patterns.length > 0 || $analyze.json.recurring_overruns.length > 0

  # Step 8: Generate full digest narrative — LLM
  - id: generate-digest
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a Monday calendar digest for the user. Lead with the meeting load score and how it changed. Cover: meeting hours vs focus hours, heaviest and lightest days, meeting type distribution shifts, and any patterns or recurring overruns. End with the coming week preview if available. Keep it concise — this is a briefing the user reads in 60 seconds, not a report. Adapt format and tone to the user.",
        "thinking": "low",
        "input": {
          "analytics": $analyze.json,
          "pattern_context": $contextualize-patterns.json,
          "prior_weeks": $load-prior.json
        },
        "schema": {
          "type": "object",
          "properties": {
            "digest": {"type": "string"},
            "load_score_summary": {"type": "string"},
            "action_items": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["digest"]
        }
      }'

  # Step 9: Store analytics for trend tracking
  - id: store-analytics
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "ora-analytics/weekly/{{date}}",
        "data": $analyze.json
      }'

  # Step 10: Deliver to Slack
  - id: notify
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-calendar",
        "text": "📊 WEEKLY CALENDAR DIGEST — {{date}}\n\n$generate-digest.json.digest"
      }'

  # Step 11: Capability-evolver — learn from the week
  - id: learn
    command: >
      openclaw.invoke --tool capability-evolver --action analyze --args-json '{
        "data": {
          "analytics": $analyze.json,
          "user_overrides": "from fast-io ora-state/exception-history",
          "dismissed_flags": "from fast-io ora-state/agenda-dismissals"
        },
        "focus": "Which scheduling patterns does the user consistently override? Which flags do they dismiss? Which meeting types do they actually engage with prep briefs for?"
      }'

  # Step 12: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/weekly-digest",
        "data": {
          "action": "weekly_digest",
          "load_score": $analyze.json.load_score,
          "meeting_hours": $analyze.json.meeting_hours,
          "focus_pct": $analyze.json.focus_pct,
          "patterns_detected": $analyze.json.patterns.length,
          "overruns_detected": $analyze.json.recurring_overruns.length,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
