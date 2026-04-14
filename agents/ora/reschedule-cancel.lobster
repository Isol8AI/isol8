name: reschedule-cancel
# Requirements 40, 41, 42, 43: Rescheduling and cancellation with user confirmation.
# Triggered per user request.
# LLM calls: 1 (message drafting — adaptive tone per relationship)

args:
  action_type:
    required: true
  event_id:
    required: true
  new_date_preference:
    default: ""

steps:
  # Step 1: Read connected calendar config + primary-calendar pointer
  - id: load-connected
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/connected-calendars"}'

  - id: load-user-calendar
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/user-calendar"}'

  # Step 2: Load the target event from the user's primary calendar
  - id: load-event-gog
    command: >
      openclaw.invoke --tool gog --action calendar-get-event --args-json '{
        "calendar_id": "primary",
        "event_id": "{{event_id}}"
      }'
    condition: $load-user-calendar.json.platform == "google"

  - id: load-event-ms365
    command: >
      openclaw.invoke --tool ms365 --action calendar-get-event --args-json '{
        "event_id": "{{event_id}}"
      }'
    condition: $load-user-calendar.json.platform == "outlook"

  - id: load-event-caldav
    command: >
      openclaw.invoke --tool caldav-calendar --action get-event --args-json '{
        "event_id": "{{event_id}}"
      }'
    condition: $load-user-calendar.json.platform == "caldav" || $load-user-calendar.json.platform == "icloud"

  - id: load-event-calctl
    command: >
      openclaw.invoke --tool calctl --action get-event --args-json '{
        "event_id": "{{event_id}}"
      }'
    condition: $load-user-calendar.json.platform == "apple"

  # Step 3: Load participant timezone profiles
  - id: load-participants
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "ora-contacts/"
      }'

  # Step 4: Pull same-day events from all connected calendars for dependency scan
  - id: load-same-day-gog
    command: >
      openclaw.invoke --tool gog --action calendar-list-events --args-json '{
        "calendar_id": "primary",
        "date": "$load-event-gog.json.start"
      }'
    condition: $load-connected.json.gog.connected == true

  - id: load-same-day-ms365
    command: >
      openclaw.invoke --tool ms365 --action calendar-list-events --args-json '{
        "date": "$load-event-ms365.json.start"
      }'
    condition: $load-connected.json.ms365.connected == true

  - id: load-same-day-caldav
    command: >
      openclaw.invoke --tool caldav-calendar --action list-events --args-json '{
        "date": "$load-event-caldav.json.start"
      }'
    condition: $load-connected.json.caldav.connected == true

  - id: load-same-day-calctl
    command: >
      openclaw.invoke --tool calctl --action list-events --args-json '{
        "date": "$load-event-calctl.json.start"
      }'
    condition: $load-connected.json.calctl.connected == true

  - id: merge-same-day
    command: >
      exec --json --shell 'node scripts/ora-availability-merger.js'
    stdin: '{
      "mode": "merge_busy",
      "events_by_source": {
        "gog": $load-same-day-gog.json.events,
        "ms365": $load-same-day-ms365.json.events,
        "caldav": $load-same-day-caldav.json.events,
        "calctl": $load-same-day-calctl.json.events
      }
    }'

  - id: check-dependencies
    command: >
      exec --json --shell 'node scripts/ora-dependency-checker.js'
    stdin: '{
      "event": $load-event-gog.json,
      "all_events": $merge-same-day.json.busy_intervals
    }'

  - id: dependency-alert
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-calendar",
        "text": "⚠️ This meeting has related events:\n$check-dependencies.json.dependencies\n\nCancel/reschedule all, or handle each separately?"
      }'
    condition: $check-dependencies.json.has_dependencies

  # Step 5: For reschedule — pull events across the target date range
  - id: load-range-gog
    command: >
      openclaw.invoke --tool gog --action calendar-list-events --args-json '{
        "calendar_id": "primary",
        "date_range": "{{new_date_preference}}"
      }'
    condition: $action_type == "reschedule" && $load-connected.json.gog.connected == true

  - id: load-range-ms365
    command: >
      openclaw.invoke --tool ms365 --action calendar-list-events --args-json '{
        "date_range": "{{new_date_preference}}"
      }'
    condition: $action_type == "reschedule" && $load-connected.json.ms365.connected == true

  - id: load-range-caldav
    command: >
      openclaw.invoke --tool caldav-calendar --action list-events --args-json '{
        "date_range": "{{new_date_preference}}"
      }'
    condition: $action_type == "reschedule" && $load-connected.json.caldav.connected == true

  - id: load-range-calctl
    command: >
      openclaw.invoke --tool calctl --action list-events --args-json '{
        "date_range": "{{new_date_preference}}"
      }'
    condition: $action_type == "reschedule" && $load-connected.json.calctl.connected == true

  - id: merge-range
    command: >
      exec --json --shell 'node scripts/ora-availability-merger.js'
    stdin: '{
      "mode": "merge_busy",
      "events_by_source": {
        "gog": $load-range-gog.json.events,
        "ms365": $load-range-ms365.json.events,
        "caldav": $load-range-caldav.json.events,
        "calctl": $load-range-calctl.json.events
      }
    }'
    condition: $action_type == "reschedule"

  - id: load-rules
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "ora-config/scheduling-rules"}'
    condition: $action_type == "reschedule"

  - id: find-new-slots
    command: >
      exec --json --shell 'node scripts/ora-availability-merger.js'
    stdin: '{
      "mode": "find_free_slots",
      "busy_intervals": $merge-range.json.busy_intervals,
      "duration_minutes": $load-event-gog.json.duration_minutes,
      "working_hours": $load-rules.json.working_hours,
      "buffer_minutes": $load-rules.json.buffer_minutes,
      "timezone": "$USER_TIMEZONE",
      "no_meeting_days": $load-rules.json.no_meeting_days,
      "max_results": 10
    }'
    condition: $action_type == "reschedule"

  - id: resolve-tz
    command: >
      exec --json --shell 'node scripts/ora-datetime-engine.js'
    stdin: '{
      "mode": "batch_convert",
      "slots": $find-new-slots.json.free_slots,
      "participants": "$load-event-gog.json.attendees"
    }'
    condition: $action_type == "reschedule"

  - id: rank-new
    command: >
      exec --json --shell 'node scripts/ora-slot-ranker.js'
    stdin: '{
      "slots": $resolve-tz.json.slots,
      "participants": "$load-event-gog.json.attendees",
      "user_preferences": $load-rules.json
    }'
    condition: $action_type == "reschedule"

  # Step 6: Draft message — LLM
  - id: draft-message
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Draft a ${action_type} message for the attendees of this meeting. Adapt the tone to the relationship: apologetic and professional for clients/external, casual and direct for internal teammates, warm for partners. For reschedules, include the proposed new times in each recipients local timezone. For cancellations, suggest whether to offer rescheduling based on the meeting type. Never sound robotic or templated.",
        "thinking": "off",
        "input": {
          "action": "{{action_type}}",
          "event": $load-event-gog.json,
          "participants": $load-participants.json,
          "new_options": $rank-new.json,
          "has_dependencies": $check-dependencies.json.has_dependencies
        },
        "schema": {
          "type": "object",
          "properties": {
            "messages": {"type": "array", "items": {
              "type": "object",
              "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "offers_reschedule": {"type": "boolean"}
              }
            }},
            "user_preview": {"type": "string"}
          },
          "required": ["messages", "user_preview"]
        }
      }'

  # Step 7: Present to user for confirmation — TIER 2 GATE (Req 43)
  - id: present-for-confirmation
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-calendar",
        "text": "📝 ${action_type == \"reschedule\" ? \"RESCHEDULE\" : \"CANCEL\"} — $load-event-gog.json.title\n\n$draft-message.json.user_preview\n\n[Confirm and Send] [Edit Message] [Cancel Action]"
      }'

  - id: await-confirmation
    command: >
      openclaw.invoke --tool lobster --action await-approval --args-json '{
        "prompt": "Waiting for user to confirm ${action_type}",
        "timeout_hours": 24
      }'

  # Step 8: Build the reschedule or cancel payload (deterministic)
  - id: prepare-reschedule
    command: >
      exec --json --shell 'node scripts/ora-booking-engine.js'
    stdin: '{
      "mode": "prepare_reschedule",
      "existing_event": $load-event-gog.json,
      "new_slot": $await-confirmation.json.selected_slot,
      "user_calendar": $load-user-calendar.json
    }'
    condition: $await-confirmation.json.approved && $action_type == "reschedule"

  - id: prepare-cancel
    command: >
      exec --json --shell 'node scripts/ora-booking-engine.js'
    stdin: '{
      "mode": "prepare_cancel",
      "existing_event": $load-event-gog.json,
      "user_calendar": $load-user-calendar.json
    }'
    condition: $await-confirmation.json.approved && $action_type == "cancel"

  # Step 9: Execute via the selected provider
  - id: execute-reschedule-gog
    command: >
      openclaw.invoke --tool gog --action calendar-update-event --args-json '$prepare-reschedule.json.args'
    condition: $prepare-reschedule.json.provider == "gog"

  - id: execute-reschedule-ms365
    command: >
      openclaw.invoke --tool ms365 --action calendar-update-event --args-json '$prepare-reschedule.json.args'
    condition: $prepare-reschedule.json.provider == "ms365"

  - id: execute-reschedule-caldav
    command: >
      openclaw.invoke --tool caldav-calendar --action update-event --args-json '$prepare-reschedule.json.args'
    condition: $prepare-reschedule.json.provider == "caldav-calendar"

  - id: execute-reschedule-calctl
    command: >
      openclaw.invoke --tool calctl --action update-event --args-json '$prepare-reschedule.json.args'
    condition: $prepare-reschedule.json.provider == "calctl"

  - id: execute-cancel-gog
    command: >
      openclaw.invoke --tool gog --action calendar-delete-event --args-json '$prepare-cancel.json.args'
    condition: $prepare-cancel.json.provider == "gog"

  - id: execute-cancel-ms365
    command: >
      openclaw.invoke --tool ms365 --action calendar-delete-event --args-json '$prepare-cancel.json.args'
    condition: $prepare-cancel.json.provider == "ms365"

  - id: execute-cancel-caldav
    command: >
      openclaw.invoke --tool caldav-calendar --action delete-event --args-json '$prepare-cancel.json.args'
    condition: $prepare-cancel.json.provider == "caldav-calendar"

  - id: execute-cancel-calctl
    command: >
      openclaw.invoke --tool calctl --action delete-event --args-json '$prepare-cancel.json.args'
    condition: $prepare-cancel.json.provider == "calctl"

  # Step 10: Send messages to participants
  - id: send-messages
    command: >
      openclaw.invoke --tool gog --action gmail-send --args-json '{
        "messages": $draft-message.json.messages
      }'
    condition: $await-confirmation.json.approved

  # Step 11: Cascade dependencies if user chose to
  - id: cascade-dependencies
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#ora-calendar",
        "text": "Related events to handle:\n$check-dependencies.json.dependencies\n\nProcessing each one — you will confirm individually."
      }'
    condition: $check-dependencies.json.has_dependencies && $await-confirmation.json.cascade

  # Step 12: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/${action_type}/{{event_id}}",
        "data": {
          "action": "{{action_type}}",
          "event": "$load-event-gog.json.title",
          "participants": "$load-event-gog.json.attendees",
          "dependencies": $check-dependencies.json.dependencies,
          "new_slot": "$await-confirmation.json.selected_slot",
          "message_sent": $await-confirmation.json.approved,
          "authorized_by": "user_confirmed",
          "timestamp": "{{timestamp}}"
        }
      }'
