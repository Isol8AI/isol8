name: message-outbound
# Requirements 12, 15, 16, 17: Route outbound, draft with channel tone, confirm, send.
# Triggered per user outbound request.
# LLM calls: 1 (draft message with channel-appropriate tone)

args:
  intent:
    required: true    # "follow up with Marcus about the proposal, tell him we're ready to sign"
  contact_name:
    required: true
  explicit_channel:
    default: ""       # User can override channel

steps:
  # Step 1: Resolve contact
  - id: resolve-contact
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "thread-contacts/by-name/{{contact_name}}"
      }'

  # Step 2: Load contact context (Req 20)
  - id: load-context
    command: >
      exec --json --shell 'node scripts/thread-contact-context.js'

  # Step 3: Summarize recent conversation topic
  - id: recent-topic
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": "$load-context.json.recent_messages",
        "format": "executive-summary",
        "max_length": 100
      }'
    condition: $load-context.json.needs_topic_summary

  # Step 4: Route to channel (Req 12)
  - id: route
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "thread-config/auto-send-channels"}'
      | openclaw.invoke --tool fast-io --action read --args-json '{"key": "thread-state/user-overrides"}'
      | exec --json --shell 'node scripts/thread-channel-router.js'

  # Step 5: Override channel if user specified
  - id: apply-override
    command: >
      exec --json --shell 'node -e "
        const route = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const explicit = \"{{explicit_channel}}\";
        if (explicit && explicit !== route.channel) {
          route.channel = explicit;
          route.reason = \"User specified ${explicit} for this message.\";
          route.requires_confirmation = true;
        }
        process.stdout.write(JSON.stringify(route));
      "'
    stdin: $route.stdout

  # Step 6: Draft message with channel-appropriate tone — ADAPTIVE LLM (Req 15)
  - id: draft-message
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Draft a message for this contact on this channel. Adapt tone to the channel: Slack is concise and direct, email is complete with subject line and sign-off, WhatsApp is conversational, LinkedIn is professionally warm, SMS is short. Also adapt to the specific relationship — match the tone the user has used with this contact before. The user wants to: {{intent}}",
        "thinking": "off",
        "input": {
          "channel": "$apply-override.json.channel",
          "contact": "$resolve-contact.json",
          "recent_context": "$recent-topic.stdout",
          "tone_guidance": "$apply-override.json.tone_guidance",
          "relationship_history": "$load-context.json.recent_messages"
        },
        "schema": {
          "type": "object",
          "properties": {
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "channel": {"type": "string"},
            "tone_note": {"type": "string"}
          },
          "required": ["body", "channel"]
        }
      }'

  # Step 7: Present draft for confirmation — TIER 2 GATE for external (Req 16)
  - id: present-draft
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#thread-inbox",
        "text": "📤 OUTBOUND DRAFT — $apply-override.json.channel · $resolve-contact.json.name\n\n${draft-message.json.subject ? \"Subject: \" + draft-message.json.subject + \"\n\n\" : \"\"}$draft-message.json.body\n\nRouting: $apply-override.json.reason\n\n[Send] [Edit] [Change Channel] [Cancel]"
      }'
    condition: $apply-override.json.requires_confirmation

  - id: await-confirmation
    command: >
      openclaw.invoke --tool lobster --action await-approval --args-json '{
        "prompt": "Waiting for user to confirm outbound message",
        "timeout_hours": 24
      }'
    condition: $apply-override.json.requires_confirmation

  # Step 8: Send via appropriate channel
  - id: send-slack
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "$resolve-contact.json.slack_channel",
        "text": "$draft-message.json.body"
      }'
    condition: ($await-confirmation.json.approved || !$apply-override.json.requires_confirmation) && $apply-override.json.channel == "slack"

  - id: send-email
    command: >
      openclaw.invoke --tool gog --action gmail-send --args-json '{
        "to": "$resolve-contact.json.email",
        "subject": "$draft-message.json.subject",
        "body": "$draft-message.json.body"
      }'
    condition: $await-confirmation.json.approved && $apply-override.json.channel == "email"

  - id: send-whatsapp
    command: >
      openclaw.invoke --tool message --action send --args-json '{
        "channel": "whatsapp",
        "to": "$resolve-contact.json.phone",
        "text": "$draft-message.json.body"
      }'
    condition: $await-confirmation.json.approved && $apply-override.json.channel == "whatsapp"

  - id: send-linkedin
    command: >
      exec --json --shell 'curl -s -X POST "https://api.linkedin.com/v2/messages" -H "Authorization: Bearer $LINKEDIN_TOKEN" -H "Content-Type: application/json" -d "{\"recipients\":[\"$resolve-contact.json.linkedin_id\"],\"body\":\"$draft-message.json.body\"}"'
    condition: $await-confirmation.json.approved && $apply-override.json.channel == "linkedin"

  - id: send-sms
    command: >
      exec --json --shell 'curl -s -X POST "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_SID/Messages.json" -u "$TWILIO_SID:$TWILIO_AUTH" -d "To=$resolve-contact.json.phone" -d "From=$TWILIO_NUMBER" -d "Body=$draft-message.json.body"'
    condition: $await-confirmation.json.approved && $apply-override.json.channel == "sms"

  # Step 9: Track for follow-up (Req 21)
  - id: track-outbound
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "thread-outbound/{{timestamp}}/{{message_id}}",
        "data": {
          "id": "{{message_id}}",
          "contact_id": "$resolve-contact.json.id",
          "contact_name": "$resolve-contact.json.name",
          "contact_email": "$resolve-contact.json.email",
          "channel": "$apply-override.json.channel",
          "subject": "$draft-message.json.subject",
          "preview": "$draft-message.json.body",
          "sent_at": "{{timestamp}}",
          "relationship_tier": "$resolve-contact.json.relationship_tier",
          "awaiting_response": true
        }
      }'

  # Step 10: Update relationship thread
  - id: update-thread
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "thread-contacts/$resolve-contact.json.id/history/{{timestamp}}",
        "data": {
          "timestamp": "{{timestamp}}",
          "channel": "$apply-override.json.channel",
          "direction": "outbound",
          "preview": "$draft-message.json.body",
          "message_id": "{{message_id}}"
        }
      }'

  # Step 11: Audit log (Req 11)
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "thread-audit/{{date}}/outbound/{{message_id}}",
        "data": {
          "action": "message_sent",
          "contact": "$resolve-contact.json.name",
          "channel": "$apply-override.json.channel",
          "routing_reason": "$apply-override.json.reason",
          "confirmed_by": "$apply-override.json.requires_confirmation ? \"user_confirmed\" : \"auto_send\"",
          "timestamp": "{{timestamp}}"
        }
      }'
