name: message-inbound
# Requirements 1-4, 7-11: Process incoming messages from any channel.
# Triggered per incoming message via webhook.
# LLM calls: 0 (fully deterministic processing)

args:
  channel:
    required: true
  sender:
    required: true
  content:
    required: true
  message_id:
    required: true

steps:
  # Step 1: Sanitize message content (Req 8)
  - id: sanitize
    command: >
      exec --json --shell 'node scripts/thread-message-sanitizer.js'
    stdin: '{"content": "{{content}}", "channel": "{{channel}}"}'

  # Step 2: Run email-security for email channel (additional layer)
  - id: email-security-check
    command: >
      openclaw.invoke --tool email-security --action scan --args-json '{
        "content": "{{content}}",
        "sender": "{{sender}}",
        "message_id": "{{message_id}}"
      }'
    condition: $channel == "email"

  # Step 3: Injection detection (Req 9)
  - id: injection-check
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "thread-state/safe-senders"}'
      | exec --json --shell 'node scripts/thread-injection-detector.js'
    stdin: '{"text": "$sanitize.json.sanitized_text", "sender_email": "{{sender}}"}'

  # Step 4: Flag injection in Slack if detected
  - id: injection-alert
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#thread-inbox",
        "text": "$injection-check.json.message\n\nFrom: {{sender}} via {{channel}}\n\n[Review Message] [Mark Sender Safe] [Discard]"
      }'
    condition: $injection-check.json.flagged

  # Step 5: Resolve contact identity
  - id: resolve-contact
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "thread-contacts/by-address/{{sender}}"
      }'

  # Step 6: Load relationship tier
  - id: load-tier
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "thread-config/relationship-tiers"
      }'

  # Step 7: Check calendar for time-sensitivity context (Req 26)
  - id: calendar-context
    command: >
      openclaw.invoke --tool gog --action gcal-list-events --args-json '{
        "date": "{{today}}",
        "attendee": "{{sender}}"
      }'

  # Step 8: Triage score (Req 3, 4)
  - id: triage
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "thread-config/triage-weights"}'
      | exec --json --shell 'node scripts/thread-triage-scorer.js'
    stdin: '{"messages": [{"id": "{{message_id}}", "sender": "{{sender}}", "channel": "{{channel}}", "timestamp": "{{timestamp}}", "preview": "$sanitize.json.sanitized_text", "sender_tier": "$resolve-contact.json.relationship_tier", "is_reply_to_user": "$resolve-contact.json.has_pending_outbound", "calendar_match_today": "$calendar-context.json.has_meeting_today"}]}'

  # Step 9: Compress long messages for stream preview
  - id: compress-preview
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": "$sanitize.json.sanitized_text",
        "format": "bullet-points",
        "max_length": 200
      }'

  # Step 10: Store in unified stream (Req 1, 2)
  - id: store-stream
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "thread-stream/{{timestamp}}/{{message_id}}",
        "data": {
          "id": "{{message_id}}",
          "sender": "{{sender}}",
          "contact_id": "$resolve-contact.json.id",
          "contact_name": "$resolve-contact.json.name",
          "channel": "{{channel}}",
          "channel_label": "{{channel}} · $resolve-contact.json.name",
          "preview": "$compress-preview.stdout",
          "triage_score": $triage.json.ranked[0].final_score,
          "triage_breakdown": $triage.json.ranked[0].breakdown,
          "relationship_tier": "$resolve-contact.json.relationship_tier",
          "injection_flagged": $injection-check.json.flagged,
          "sanitization_notes": "$sanitize.json.elements_stripped",
          "timestamp": "{{timestamp}}",
          "status": "unread"
        }
      }'

  # Step 11: Update relationship thread (Req 19)
  - id: update-thread
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "thread-contacts/$resolve-contact.json.id/history/{{timestamp}}",
        "data": {
          "timestamp": "{{timestamp}}",
          "channel": "{{channel}}",
          "direction": "inbound",
          "preview": "$compress-preview.stdout",
          "message_id": "{{message_id}}"
        }
      }'

  # Step 12: Audit log (Req 11)
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "thread-audit/{{date}}/inbound/{{message_id}}",
        "data": {
          "action": "message_received",
          "sender": "{{sender}}",
          "channel": "{{channel}}",
          "triage_score": $triage.json.ranked[0].final_score,
          "injection_flagged": $injection-check.json.flagged,
          "sanitized": $sanitize.json.had_suspicious_content,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
