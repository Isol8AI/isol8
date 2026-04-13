name: escalation
# Requirements 26, 29, 30, 31, 42, 50, 59: Full escalation flow with context.
# Triggered from intake-resolve when escalation conditions are met.
# LLM calls: 1 (suggested resolution path)

args:
  conversation_id:
    required: true
  customer_email:
    required: true
  escalation_trigger:
    required: true
  customer_message:
    default: ""

steps:
  # Step 1: Load full conversation from taskr
  - id: load-conversation
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "vera-conversations/{{conversation_id}}"
      }'

  # Step 1.5: Load helpdesk configuration (click-to-connect)
  - id: load-helpdesk-config
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "vera-config/connected-helpdesk"
      }'

  # Step 2: Load customer profile and history (Req 42)
  # Parallel conditional branches per connected helpdesk provider.
  - id: load-customer-zendesk
    command: >
      exec --json --shell 'curl -s -u "$ZENDESK_EMAIL/token:$ZENDESK_API_TOKEN" "https://$ZENDESK_SUBDOMAIN.zendesk.com/api/v2/search.json?query=type:user+email:{{customer_email}}&include=tickets,orders"'
    condition: $load-helpdesk-config.json.platform == "zendesk"

  - id: load-customer-intercom
    command: >
      exec --json --shell 'curl -s -H "Authorization: Bearer $INTERCOM_ACCESS_TOKEN" -H "Accept: application/json" "https://api.intercom.io/contacts?email={{customer_email}}"'
    condition: $load-helpdesk-config.json.platform == "intercom"

  # Standalone mode: no helpdesk connected — customer data from fast-io
  - id: load-customer-standalone
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "vera-customers/{{customer_email}}"
      }'
    condition: $load-helpdesk-config.json.platform == null

  # Normalize customer data from whichever provider responded
  - id: load-customer
    command: >
      exec --json --shell 'node -e "
        const input = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const zd = input.zendesk; const ic = input.intercom; const sa = input.standalone;
        let c = {};
        if (zd && zd.results) {
          const u = (zd.results || [])[0] || {};
          c = { name: u.name || null, email: u.email || null, account_id: String(u.id || \"\"), tickets: u.tickets || [], orders: u.orders || [], latest_order_id: u.latest_order_id || null, phone: u.phone || null, csat: u.csat || [] };
        } else if (ic && ic.data) {
          const u = (ic.data || [])[0] || {};
          c = { name: u.name || null, email: u.email || null, account_id: u.id || null, tickets: [], orders: [], latest_order_id: null, phone: u.phone || null, csat: [] };
        } else {
          c = sa || {};
        }
        process.stdout.write(JSON.stringify(c));
      "'
    stdin: '{"zendesk": $load-customer-zendesk.json, "intercom": $load-customer-intercom.json, "standalone": $load-customer-standalone.json}'

  # Step 3: Load CSAT history (Req 42)
  - id: load-csat
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "vera-csat/",
        "filter": "customer_email:{{customer_email}}"
      }'

  # Step 4: Load ticket attempts from taskr
  - id: load-attempts
    command: >
      openclaw.invoke --tool taskr --action read --args-json '{
        "key": "vera-tickets/{{conversation_id}}"
      }'

  # Step 5: Summarize conversation transcript (zero LLM — CLI tool)
  - id: summarize-transcript
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $load-conversation.json,
        "format": "escalation-handoff"
      }'

  # Step 6: Build escalation package deterministically (Req 29)
  - id: build-package
    command: >
      exec --json --shell 'node scripts/vera-escalation-builder.js'

  # Step 7: Generate suggested resolution — ONE LLM CALL
  - id: suggest-resolution
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Based on this escalated support ticket, suggest a resolution path for the human agent. Consider the conversation history, what Vera already attempted, the customer sentiment, and any relevant policy context. Be specific and actionable.",
        "thinking": "low",
        "input": {
          "transcript_summary": $summarize-transcript.stdout,
          "escalation_trigger": "{{escalation_trigger}}",
          "attempts": $load-attempts.json,
          "customer_context": $load-customer.json,
          "csat_history": $load-csat.json
        },
        "schema": {
          "type": "object",
          "properties": {
            "suggested_resolution": {"type": "string"},
            "key_info_for_agent": {"type": "string"},
            "recommended_tone": {"type": "string"}
          },
          "required": ["suggested_resolution"]
        }
      }'

  # Step 8: Check business hours for availability (Req 31)
  - id: check-hours
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "vera-config/business-hours"}'
      | exec --json --shell 'node -e "
        const config = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const now = new Date();
        const hour = now.getHours();
        const day = now.getDay();
        const staffed = config.staffed_days?.includes(day) &&
          hour >= parseInt(config.staffed_hours?.start) &&
          hour < parseInt(config.staffed_hours?.end);
        process.stdout.write(JSON.stringify({
          is_staffed: staffed,
          out_of_hours_behavior: config.out_of_hours_behavior || \"queue_with_callback\"
        }));
      "'

  # Step 9a: Post to escalation Slack channel (during business hours)
  - id: escalate-to-slack
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#vera-escalations",
        "text": "🚨 ESCALATION — {{customer_email}}\n\n**Trigger:** {{escalation_trigger}}\n**Priority:** $build-package.json.priority\n**Sentiment:** $build-package.json.sentiment.current\n\n**Summary:** $summarize-transcript.stdout\n\n**Customer CSAT History:** Avg $build-package.json.customer.csat_history.average, Last $build-package.json.customer.csat_history.last_score\n**Repeat issue:** $build-package.json.customer.is_repeat_issue\n\n**Vera attempted:** $build-package.json.resolution_attempts\n\n**Suggested resolution:** $suggest-resolution.json.suggested_resolution\n**Recommended tone:** $suggest-resolution.json.recommended_tone"
      }'
    condition: $check-hours.json.is_staffed

  # Step 9b: Out-of-hours handling (Req 31)
  - id: out-of-hours-message
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a transparent out-of-hours message for this customer. Acknowledge no human is available right now. State business hours. Offer three options: leave a message, schedule a callback, or receive an email update. Be honest and warm, not corporate.",
        "thinking": "low",
        "input": {
          "customer_name": "$load-customer.json.name",
          "business_hours": $check-hours.json,
          "issue_summary": $summarize-transcript.stdout
        },
        "schema": {
          "type": "object",
          "properties": {
            "message": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["message"]
        }
      }'
    condition: $check-hours.json.is_staffed == false

  # Step 10: Send customer escalation confirmation (Req 30)
  - id: send-confirmation
    command: >
      openclaw.invoke --tool message --action send --args-json '{
        "channel": "{{channel}}",
        "to": "{{customer_email}}",
        "text": "$check-hours.json.is_staffed ? \"A human agent is now reviewing your conversation. Your ticket number is $build-package.json.ticket_id. They already know about your issue and will pick up right where we left off.\" : $out-of-hours-message.json.message"
      }'

  # Step 11: Queue for next staffed hour if out-of-hours
  - id: queue-callback
    command: >
      openclaw.invoke --tool taskr --action create --args-json '{
        "key": "vera-callbacks/{{conversation_id}}",
        "data": {
          "customer_email": "{{customer_email}}",
          "ticket_id": "$build-package.json.ticket_id",
          "escalation_package": $build-package.json,
          "suggested_resolution": $suggest-resolution.json,
          "queued_at": "{{timestamp}}"
        }
      }'
    condition: $check-hours.json.is_staffed == false

  # Step 12: Voice escalation for distress (telcall-twilio)
  - id: voice-escalation
    command: >
      openclaw.invoke --tool telcall-twilio --action call --args-json '{
        "to": "$load-customer.json.phone",
        "message": "Priority support escalation for $load-customer.json.name. Ticket $build-package.json.ticket_id."
      }'
    condition: $build-package.json.priority == "urgent" && $load-customer.json.phone

  # Step 13: Log escalation event with trigger type (Req 47, 48)
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/escalation/{{conversation_id}}",
        "data": {
          "action": "escalation",
          "conversation_id": "{{conversation_id}}",
          "customer_email": "{{customer_email}}",
          "trigger": "{{escalation_trigger}}",
          "priority": "$build-package.json.priority",
          "sentiment": "$build-package.json.sentiment.current",
          "is_staffed": $check-hours.json.is_staffed,
          "compliance_flag": "$build-package.json.issue.compliance_flag",
          "ticket_id": "$build-package.json.ticket_id",
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
