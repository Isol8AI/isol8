name: morning-briefing
# Requirements 8, 10, 11, 12, 34: Daily calendar health check and briefing.
# Runs daily 7 AM on cron.
# LLM calls: 1 (briefing narrative — adaptive to user's style)

steps:
  # Step 1: Read the user's connected calendar config. The Isol8 settings UI
  # writes this key when the user connects a calendar. Supports multiple
  # connected calendars simultaneously (work Google + personal iCloud, etc).
  - id: load-connected
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/connected-calendars"}'

  # If nothing is connected, surface the click-to-connect prompt and exit.
  - id: no-calendar-notice
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-calendar",
        "text": "To run morning briefings, connect a calendar in your settings. Supported: Google Calendar, Microsoft 365 / Outlook, Apple Calendar, or any CalDAV provider (iCloud, Fastmail, Nextcloud)."
      }'
    condition: $load-connected.json.gog.connected != true && $load-connected.json.ms365.connected != true && $load-connected.json.caldav.connected != true && $load-connected.json.calctl.connected != true

  # Step 2: Pull today's events from every connected calendar source
  # (deterministic API calls, routed through the native calendar skill
  # for each connected provider)
  - id: load-gog-events
    command: >
      openclaw.invoke --tool gog --action calendar-list-events --args-json '{
        "calendar_id": "primary",
        "date": "{{today}}"
      }'
    condition: $load-connected.json.gog.connected == true

  - id: load-ms365-events
    command: >
      openclaw.invoke --tool ms365 --action calendar-list-events --args-json '{
        "date": "{{today}}"
      }'
    condition: $load-connected.json.ms365.connected == true

  - id: load-caldav-events
    command: >
      openclaw.invoke --tool caldav-calendar --action list-events --args-json '{
        "date": "{{today}}"
      }'
    condition: $load-connected.json.caldav.connected == true

  - id: load-calctl-events
    command: >
      openclaw.invoke --tool calctl --action list-events --args-json '{
        "date": "{{today}}"
      }'
    condition: $load-connected.json.calctl.connected == true

  # Step 3: Merge every connected calendar's events into a unified busy set
  - id: merge-events
    command: >
      exec --json --shell 'node scripts/ora-availability-merger.js'
    stdin: '{
      "mode": "merge_busy",
      "events_by_source": {
        "gog": $load-gog-events.json.events,
        "ms365": $load-ms365-events.json.events,
        "caldav": $load-caldav-events.json.events,
        "calctl": $load-calctl-events.json.events
      },
      "block_all_day": false
    }'

  # Step 4: Load scheduling rules
  - id: load-rules
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/scheduling-rules"}'

  # Step 5: Conflict detection across all calendars (Req 10)
  - id: conflict-check
    command: >
      exec --json --shell 'node scripts/ora-conflict-detector.js'
    stdin: '{"events": $merge-events.json.busy_intervals}'

  # Step 6: Buffer violation check (Req 11)
  - id: buffer-check
    command: >
      exec --json --shell 'node scripts/ora-buffer-checker.js'
    stdin: '{"events": $merge-events.json.busy_intervals, "buffer_minutes": $load-rules.json.buffer_minutes}'

  # Step 7: Focus block check — is there one today? (Req 8)
  - id: focus-check
    command: >
      exec --json --shell 'node -e "
        const intervals = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\")).busy_intervals || [];
        const focusBlocks = intervals.filter(iv => iv.is_focus_block);
        process.stdout.write(JSON.stringify({
          has_focus_block: focusBlocks.length > 0,
          focus_blocks: focusBlocks.length,
          needs_suggestion: focusBlocks.length === 0
        }));
      "'
    stdin: '{"busy_intervals": $merge-events.json.busy_intervals}'

  # Step 8: Find free slots for a missing focus block (deterministic)
  - id: suggest-focus
    command: >
      exec --json --shell 'node scripts/ora-availability-merger.js'
    stdin: '{
      "mode": "find_free_slots",
      "busy_intervals": $merge-events.json.busy_intervals,
      "duration_minutes": $load-rules.json.focus_block.duration_minutes,
      "working_hours": $load-rules.json.working_hours,
      "timezone": "$USER_TIMEZONE",
      "max_results": 3,
      "no_meeting_days": $load-rules.json.no_meeting_days
    }'
    condition: $focus-check.json.needs_suggestion

  # Step 9: Meeting quality check — no-agenda flags (Req 34)
  - id: load-dismissals
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-state/agenda-dismissals"}'

  - id: quality-check
    command: >
      exec --json --shell 'node scripts/ora-meeting-quality-checker.js'
    stdin: '{"meetings": $merge-events.json.busy_intervals, "dismissal_history": $load-dismissals.json}'

  # Step 10: Flag meetings that need a video link (deterministic filter)
  - id: find-missing-video-links
    command: >
      exec --json --shell 'node -e "
        const intervals = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\")).busy_intervals || [];
        const needsLink = intervals.filter(iv =>
          !iv.is_focus_block && (iv.attendees || []).length > 0 && !iv.video_link
        );
        process.stdout.write(JSON.stringify({needs_link: needsLink, count: needsLink.length}));
      "'
    stdin: '{"busy_intervals": $merge-events.json.busy_intervals}'

  # Step 11: Generate briefing narrative — LLM CALL
  - id: generate-briefing
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a concise morning calendar briefing for the user. Adapt your tone and format to their preferences — some users want bullet points, some want a narrative, some just want the alerts. Lead with conflicts and issues, then the day overview. If there are no issues, keep it short.",
        "thinking": "low",
        "input": {
          "todays_events": $merge-events.json.busy_intervals,
          "conflicts": $conflict-check.json,
          "buffer_violations": $buffer-check.json,
          "focus_status": $focus-check.json,
          "focus_suggestion": $suggest-focus.json,
          "no_agenda_meetings": $quality-check.json,
          "missing_video_links": $find-missing-video-links.json.count
        },
        "schema": {
          "type": "object",
          "properties": {
            "briefing": {"type": "string"},
            "has_issues": {"type": "boolean"},
            "action_items": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["briefing", "has_issues"]
        }
      }'

  # Step 12: Deliver to Slack
  - id: notify
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-calendar",
        "text": "$generate-briefing.json.briefing"
      }'

  # Step 13: Transform connected-calendars config into the shape
  # ora-connection-health.js expects (array of per-provider objects)
  - id: build-health-input
    command: >
      exec --json --shell 'node -e "
        const cfg = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const connections = [];
        for (const [key, val] of Object.entries(cfg || {})) {
          if (val && val.connected) {
            connections.push({
              platform: key,
              type: key,
              api_test: val.api_test || null,
              webhook_status: val.webhook_status || null,
              token_status: val.token_status || null
            });
          }
        }
        process.stdout.write(JSON.stringify({connections}));
      "'
    stdin: '$load-connected.json'

  - id: health-check
    command: >
      exec --json --shell 'node scripts/ora-connection-health.js'
    stdin: '$build-health-input.json'

  - id: health-alert
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-alerts",
        "text": "$health-check.json.emoji CALENDAR CONNECTION: $health-check.json.overall_status\n\n$health-check.json.connections"
      }'
    condition: $health-check.json.alert

  # Step 14: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/morning-briefing",
        "data": {
          "action": "morning_briefing",
          "events_today": $merge-events.json.total_intervals,
          "conflicts": $conflict-check.json.has_conflicts,
          "buffer_violations": $buffer-check.json.has_violations,
          "focus_block_present": $focus-check.json.has_focus_block,
          "no_agenda_flagged": $quality-check.json.flagged_count,
          "missing_video_links": $find-missing-video-links.json.count,
          "connection_health": "$health-check.json.overall_status",
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
