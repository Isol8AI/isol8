name: morning-briefing
# Requirements 24, 25, 26: Daily briefing before first message.
# Runs on cron before user's configured start time.
# LLM calls: 1 (briefing narrative — adaptive)

steps:
  # Step 1: Load all stream messages
  - id: load-stream
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "thread-stream/",
        "filter": "timestamp:last_24h"
      }'

  # Step 2: Score all messages for triage
  - id: triage-score
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "thread-config/triage-weights"}'
      | exec --json --shell 'node scripts/thread-triage-scorer.js'

  # Step 3: Check calendar for today's meetings (time-sensitivity context)
  - id: calendar-check
    command: >
      openclaw.invoke --tool gog --action gcal-list-events --args-json '{
        "date": "{{today}}",
        "all_calendars": true
      }'

  # Step 4: Load follow-up tracker
  - id: followup-check
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{"prefix": "thread-outbound/"}'
      | exec --json --shell 'node scripts/thread-followup-tracker.js'

  # Step 5: Get top 3 contacts waiting longest
  - id: waiting-longest
    command: >
      exec --json --shell 'node -e "
        const followups = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const top3 = (followups.overdue || [])
          .sort((a, b) => b.days_waiting - a.days_waiting)
          .slice(0, 3);
        process.stdout.write(JSON.stringify(top3));
      "'
    stdin: $followup-check.stdout

  # Step 6: Generate briefing — ADAPTIVE LLM
  - id: generate-briefing
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a morning communication briefing. Under 2 minutes of reading. Decision-forward: what needs the user today, not a list of everything. Include: contacts waiting longest for a response, highest-urgency items, anything time-sensitive from calendar context. Adapt format to users preference — some want just names and channels, others want a sentence of context per item.",
        "thinking": "off",
        "input": {
          "top_urgent": $triage-score.json.top_3,
          "waiting_longest": $waiting-longest.json,
          "time_sensitive": $triage-score.json.time_sensitive_count,
          "todays_meetings": $calendar-check.json,
          "overdue_followups": $followup-check.json.overdue_count
        },
        "schema": {
          "type": "object",
          "properties": {
            "briefing": {"type": "string"},
            "action_count": {"type": "number"}
          },
          "required": ["briefing"]
        }
      }'

  # Step 7: Deliver to Slack
  - id: deliver
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#thread-inbox",
        "text": "☀️ MORNING BRIEFING\n\n$generate-briefing.json.briefing"
      }'

  # Step 8: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "thread-audit/{{date}}/morning-briefing",
        "data": {
          "action": "morning_briefing",
          "stream_size": $triage-score.json.total,
          "overdue_followups": $followup-check.json.overdue_count,
          "time_sensitive": $triage-score.json.time_sensitive_count,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
