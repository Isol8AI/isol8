name: scheduling-request
# Requirements 9, 13-16, 18-19, 22-26: Full scheduling flow from request to confirmed booking.
# Triggered per scheduling request (Slack message, booking link selection, email invite).
# LLM calls: 3 (creative solutions when no good slot, trade-off narrative, confirmation messages)

args:
  request_type:
    default: "internal"
  participants:
    required: true
  duration_minutes:
    default: 30
  meeting_type:
    default: "general"
  preferred_dates:
    default: ""
  meeting_title:
    default: "Meeting"

steps:
  # Step 1: Read the user's connected calendar config + primary-calendar pointer
  - id: load-connected
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/connected-calendars"}'

  - id: load-user-calendar
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/user-calendar"}'

  # If no calendar is connected, surface click-to-connect and exit early
  - id: no-calendar-notice
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-calendar",
        "text": "To schedule meetings, connect a calendar in your settings. Supported: Google Calendar, Microsoft 365 / Outlook, Apple Calendar, or any CalDAV provider (iCloud, Fastmail, Nextcloud)."
      }'
    condition: $load-connected.json.gog.connected != true && $load-connected.json.ms365.connected != true && $load-connected.json.caldav.connected != true && $load-connected.json.calctl.connected != true

  # Step 2: Resolve participant identities from the user's primary platform's contacts
  - id: resolve-contacts-gog
    command: >
      openclaw.invoke --tool gog --action contacts-search --args-json '{
        "query_list": $participants
      }'
    condition: $load-user-calendar.json.platform == "google"

  - id: resolve-contacts-ms365
    command: >
      openclaw.invoke --tool ms365 --action contacts-search --args-json '{
        "query_list": $participants
      }'
    condition: $load-user-calendar.json.platform == "outlook"

  # Step 2b: Normalize contacts — pick whichever provider ran
  - id: normalize-contacts
    command: >
      exec --json --shell 'node -e "
        const input = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const contacts = input.gog?.contacts || input.ms365?.contacts || input.gog || input.ms365 || [];
        process.stdout.write(JSON.stringify({contacts: Array.isArray(contacts) ? contacts : []}));
      "'
    stdin: '{"gog": $resolve-contacts-gog.json, "ms365": $resolve-contacts-ms365.json}'

  # Step 3: Load cached timezone profiles from fast-io (Req 17)
  - id: load-tz-profiles
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "ora-contacts/"
      }'

  # Step 4: Load scheduling rules + meeting type config
  - id: load-rules
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/scheduling-rules"}'

  - id: load-meeting-type
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/meeting-types"}'

  # Step 5: Pull events from all connected calendars for the date range
  - id: load-gog-events
    command: >
      openclaw.invoke --tool gog --action calendar-list-events --args-json '{
        "calendar_id": "primary",
        "date_range": "{{preferred_dates}}"
      }'
    condition: $load-connected.json.gog.connected == true

  - id: load-ms365-events
    command: >
      openclaw.invoke --tool ms365 --action calendar-list-events --args-json '{
        "date_range": "{{preferred_dates}}"
      }'
    condition: $load-connected.json.ms365.connected == true

  - id: load-caldav-events
    command: >
      openclaw.invoke --tool caldav-calendar --action list-events --args-json '{
        "date_range": "{{preferred_dates}}"
      }'
    condition: $load-connected.json.caldav.connected == true

  - id: load-calctl-events
    command: >
      openclaw.invoke --tool calctl --action list-events --args-json '{
        "date_range": "{{preferred_dates}}"
      }'
    condition: $load-connected.json.calctl.connected == true

  # Step 6: Merge into a unified busy set (deterministic script)
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
      }
    }'

  # Step 7: Find free slots against the merged busy set (Req 24)
  - id: find-free-slots
    command: >
      exec --json --shell 'node scripts/ora-availability-merger.js'
    stdin: '{
      "mode": "find_free_slots",
      "busy_intervals": $merge-events.json.busy_intervals,
      "duration_minutes": {{duration_minutes}},
      "working_hours": $load-rules.json.working_hours,
      "buffer_minutes": $load-rules.json.buffer_minutes,
      "timezone": "$USER_TIMEZONE",
      "no_meeting_days": $load-rules.json.no_meeting_days,
      "max_results": 10
    }'

  # Step 8: Resolve timezone for each slot and participant (Req 14, 16)
  # Deterministic — DST applied per meeting date
  - id: resolve-timezones
    command: >
      exec --json --shell 'node scripts/ora-datetime-engine.js'
    stdin: '{
      "mode": "batch_convert",
      "slots": $find-free-slots.json.free_slots,
      "participants": $normalize-contacts.json.contacts
    }'

  # Step 9: Rule enforcement on each candidate slot (Req 9)
  - id: load-exceptions
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-state/exception-history"}'

  - id: enforce-rules
    command: >
      exec --json --shell 'node scripts/ora-rule-enforcer.js'
    stdin: '{
      "slots": $resolve-timezones.json.slots,
      "rules": $load-rules.json,
      "exception_history": $load-exceptions.json,
      "today_meetings": $merge-events.json.busy_intervals
    }'

  # Step 10: Rank slots (Req 24, 26)
  - id: rank-slots
    command: >
      exec --json --shell 'node scripts/ora-slot-ranker.js'
    stdin: '{
      "slots": $enforce-rules.json.passing_slots,
      "participants": $normalize-contacts.json.contacts,
      "user_preferences": $load-rules.json
    }'

  # Step 11: If ranker returns needs_agent_loop — creative solutions (LLM)
  - id: creative-solutions
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "No good meeting slot exists for these participants within their constraints. Consider creative alternatives: async meeting with shared doc, splitting into two smaller sessions with different participant subsets, suggesting a different week, or asking which constraint the user is most willing to relax. Present 2-3 options.",
        "thinking": "low",
        "input": {
          "participants": $normalize-contacts.json,
          "constraints_violated": $rank-slots.json.ranked,
          "meeting_type": "{{meeting_type}}"
        },
        "schema": {
          "type": "object",
          "properties": {
            "alternatives": {"type": "array", "items": {
              "type": "object",
              "properties": {
                "option": {"type": "string"},
                "trade_off": {"type": "string"}
              }
            }},
            "recommendation": {"type": "string"}
          },
          "required": ["alternatives"]
        }
      }'
    condition: $rank-slots.json.needs_agent_loop

  # Step 12: Generate trade-off narrative for imperfect slots — LLM
  - id: trade-off-narrative
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Present these scheduling options to the user naturally. For each option, show the time in every participants local timezone and explain the trade-off in human terms — not just which rule is violated, but what it means for the people involved. Adapt your tone to the users communication style.",
        "thinking": "off",
        "input": {
          "ranked_slots": $rank-slots.json.ranked,
          "participants": $normalize-contacts.json,
          "scenario": "$rank-slots.json.scenario"
        },
        "schema": {
          "type": "object",
          "properties": {
            "message": {"type": "string"},
            "options_count": {"type": "number"}
          },
          "required": ["message"]
        }
      }'
    condition: $rank-slots.json.scenario != "perfect_match" && $rank-slots.json.needs_agent_loop == false

  # Step 13: Present options to user in Slack — TIER 2 GATE
  - id: present-options
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-calendar",
        "text": "$trade-off-narrative.json.message || $creative-solutions.json.recommendation\n\n[Option 1] [Option 2] [Option 3] [None of these]"
      }'

  # Step 14: Wait for user confirmation (Lobster approval gate)
  - id: await-confirmation
    command: >
      openclaw.invoke --tool lobster --action await-approval --args-json '{
        "prompt": "Waiting for user to select a time slot",
        "timeout_hours": 24
      }'

  # Step 15: Build the booking payload (deterministic)
  - id: prepare-booking
    command: >
      exec --json --shell 'node scripts/ora-booking-engine.js'
    stdin: '{
      "mode": "prepare_booking",
      "slot": $await-confirmation.json.selected_slot,
      "participants": $normalize-contacts.json.contacts,
      "title": "{{meeting_title}}",
      "meeting_type": "{{meeting_type}}",
      "user_calendar": $load-user-calendar.json,
      "add_video_link": true
    }'
    condition: $await-confirmation.json.approved

  # Step 16: Book via the chosen calendar platform (deterministic API call)
  - id: book-gog
    command: >
      openclaw.invoke --tool gog --action calendar-create-event --args-json '$prepare-booking.json.args'
    condition: $prepare-booking.json.provider == "gog"

  - id: book-ms365
    command: >
      openclaw.invoke --tool ms365 --action calendar-create-event --args-json '$prepare-booking.json.args'
    condition: $prepare-booking.json.provider == "ms365"

  - id: book-caldav
    command: >
      openclaw.invoke --tool caldav-calendar --action create-event --args-json '$prepare-booking.json.args'
    condition: $prepare-booking.json.provider == "caldav-calendar"

  - id: book-calctl
    command: >
      openclaw.invoke --tool calctl --action create-event --args-json '$prepare-booking.json.args'
    condition: $prepare-booking.json.provider == "calctl"

  # Step 17: Normalize the booking result so downstream steps are provider-agnostic
  - id: normalize-booking
    command: >
      exec --json --shell 'node scripts/ora-booking-normalizer.js'
    stdin: '{
      "gog": $book-gog.json,
      "ms365": $book-ms365.json,
      "caldav": $book-caldav.json,
      "calctl": $book-calctl.json
    }'

  # Step 18: Post-hoc conflict verification — reload every connected calendar
  # (parallel branches, each conditional on whether that provider is connected)
  - id: post-book-reload-gog
    command: >
      openclaw.invoke --tool gog --action calendar-list-events --args-json '{
        "calendar_id": "primary",
        "date": "$await-confirmation.json.selected_slot.start"
      }'
    condition: $load-connected.json.gog.connected == true

  - id: post-book-reload-ms365
    command: >
      openclaw.invoke --tool ms365 --action calendar-list-events --args-json '{
        "date": "$await-confirmation.json.selected_slot.start"
      }'
    condition: $load-connected.json.ms365.connected == true

  - id: post-book-reload-caldav
    command: >
      openclaw.invoke --tool caldav-calendar --action list-events --args-json '{
        "date": "$await-confirmation.json.selected_slot.start"
      }'
    condition: $load-connected.json.caldav.connected == true

  - id: post-book-reload-calctl
    command: >
      openclaw.invoke --tool calctl --action list-events --args-json '{
        "date": "$await-confirmation.json.selected_slot.start"
      }'
    condition: $load-connected.json.calctl.connected == true

  # Step 19: Re-merge the post-book reload into a unified busy set
  - id: post-book-merge
    command: >
      exec --json --shell 'node scripts/ora-availability-merger.js'
    stdin: '{
      "mode": "merge_busy",
      "events_by_source": {
        "gog": $post-book-reload-gog.json.events,
        "ms365": $post-book-reload-ms365.json.events,
        "caldav": $post-book-reload-caldav.json.events,
        "calctl": $post-book-reload-calctl.json.events
      }
    }'

  # Step 20: Verify the booking against the fresh merged busy set (deterministic)
  - id: verify-booking
    command: >
      exec --json --shell 'node scripts/ora-booking-engine.js'
    stdin: '{
      "mode": "verify_booking",
      "event_id": "$normalize-booking.json.event_id",
      "slot": $await-confirmation.json.selected_slot,
      "fresh_busy_intervals": $post-book-merge.json.busy_intervals
    }'
    condition: $normalize-booking.json.ok

  # Step 21: Rollback via whichever provider did the original write
  - id: rollback-gog
    command: >
      openclaw.invoke --tool gog --action calendar-delete-event --args-json '{
        "calendar_id": "primary",
        "event_id": "$normalize-booking.json.event_id",
        "send_updates": "none"
      }'
    condition: $verify-booking.json.needs_rollback && $normalize-booking.json.provider == "gog"

  - id: rollback-ms365
    command: >
      openclaw.invoke --tool ms365 --action calendar-delete-event --args-json '{
        "event_id": "$normalize-booking.json.event_id"
      }'
    condition: $verify-booking.json.needs_rollback && $normalize-booking.json.provider == "ms365"

  - id: rollback-caldav
    command: >
      openclaw.invoke --tool caldav-calendar --action delete-event --args-json '{
        "event_id": "$normalize-booking.json.event_id"
      }'
    condition: $verify-booking.json.needs_rollback && $normalize-booking.json.provider == "caldav"

  - id: rollback-calctl
    command: >
      openclaw.invoke --tool calctl --action delete-event --args-json '{
        "event_id": "$normalize-booking.json.event_id"
      }'
    condition: $verify-booking.json.needs_rollback && $normalize-booking.json.provider == "calctl"

  - id: rollback-alert
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-alerts",
        "text": "⚠️ Booking rolled back — a conflict appeared in the verify window. The slot is no longer available. Let me know if you want me to find another time."
      }'
    condition: $verify-booking.json.needs_rollback

  # Step 22: Send confirmation to all participants — LLM
  - id: send-confirmation
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a meeting confirmation message for each participant. Include: the meeting time in their local timezone, the video link, and any prep materials configured for this meeting type. Adapt tone to the relationship — professional for clients, casual for internal teammates.",
        "thinking": "off",
        "input": {
          "booking": $normalize-booking.json.raw,
          "participants": $normalize-contacts.json,
          "video_link": "$normalize-booking.json.video_link",
          "meeting_type": "{{meeting_type}}"
        },
        "schema": {
          "type": "object",
          "properties": {
            "messages": {"type": "array", "items": {
              "type": "object",
              "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"}
              }
            }}
          },
          "required": ["messages"]
        }
      }'
    condition: $verify-booking.json.confirmed

  # Step 23: Schedule reminders (Req 23)
  - id: schedule-reminders
    command: >
      openclaw.invoke --tool taskr --action create --args-json '{
        "key": "ora-reminders/$normalize-booking.json.event_id",
        "data": {
          "event_id": "$normalize-booking.json.event_id",
          "participants": $normalize-contacts.json,
          "remind_at_24h": true,
          "remind_at_1h": true,
          "video_link": "$normalize-booking.json.video_link"
        }
      }'

  # Step 24: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/scheduling/{{meeting_title}}",
        "data": {
          "action": "meeting_scheduled",
          "request_type": "{{request_type}}",
          "meeting_type": "{{meeting_type}}",
          "participants": $normalize-contacts.json,
          "slot_selected": $await-confirmation.json.selected_slot,
          "options_presented": $rank-slots.json.ranked,
          "scenario": "$rank-slots.json.scenario",
          "provider": "$normalize-booking.json.provider",
          "event_id": "$normalize-booking.json.event_id",
          "verify_confirmed": $verify-booking.json.confirmed,
          "rolled_back": $verify-booking.json.needs_rollback,
          "authorized_by": "user_confirmed",
          "timestamp": "{{timestamp}}"
        }
      }'
