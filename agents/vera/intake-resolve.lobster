name: intake-resolve
# Requirements 7-19, 26-28, 33-36, 44, 48: Core ticket handling pipeline.
# Triggered per incoming customer message via webhook.
# LLM calls: 2-3 per ticket (classification if ambiguous, confidence check, response generation)

args:
  customer_message:
    required: true
  customer_email:
    required: true
  channel:
    default: "chat"
  conversation_id:
    default: ""

steps:
  # Step 1: Activation gate — is escalation path healthy?
  - id: health-check
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "vera-state/escalation-health"
      }'

  # Step 2: Classify the message deterministically (Req 9)
  - id: classify
    command: >
      exec --json --shell 'node scripts/vera-intake-classifier.js'
    stdin: '{"message": "{{customer_message}}"}'

  # Step 3: LLM classification for ambiguous messages only
  - id: llm-classify
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Classify this customer support message into exactly one category: routine_resolution, needs_clarification, needs_human, or urgent_escalation. Consider tone, complexity, and whether this requires human judgment.",
        "thinking": "off",
        "input": {"message": "{{customer_message}}"},
        "schema": {
          "type": "object",
          "properties": {
            "category": {"type": "string", "enum": ["routine_resolution", "needs_clarification", "needs_human", "urgent_escalation"]},
            "subcategory": {"type": "string"},
            "reasoning": {"type": "string"}
          },
          "required": ["category"]
        }
      }'
    condition: $classify.json.needs_llm

  # Step 4: Sentiment detection (Req 11, 33)
  - id: sentiment
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "vera-conversations/{{conversation_id}}/sentiment-history"}'
      | exec --json --shell 'node scripts/vera-sentiment-detector.js'

  # Step 5: IMMEDIATE ESCALATION if needed (Req 26, 27, 35)
  # If classified as needs_human or urgent_escalation, skip resolution entirely
  - id: check-immediate-escalation
    command: >
      exec --json --shell 'node -e "
        const classify = JSON.parse(process.env.CLASSIFY || \"{}\");
        const llm = JSON.parse(process.env.LLM_CLASSIFY || \"{}\");
        const sentiment = JSON.parse(process.env.SENTIMENT || \"{}\");
        const category = classify.classified ? classify.category : (llm.category || \"routine_resolution\");
        const needsEscalation = category === \"needs_human\" || category === \"urgent_escalation\" || sentiment.action === \"priority_escalate\";
        process.stdout.write(JSON.stringify({needs_escalation: needsEscalation, category, trigger: needsEscalation ? (category === \"urgent_escalation\" ? \"distress\" : \"request\") : null}));
      "'

  # Step 5.5: Load helpdesk configuration (click-to-connect)
  - id: load-helpdesk-config
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "vera-config/connected-helpdesk"
      }'
    condition: $check-immediate-escalation.json.needs_escalation == false

  # Step 6: Pull customer context — never ask them to repeat (Req 10)
  # Parallel conditional branches per connected helpdesk provider.
  - id: load-customer-zendesk
    command: >
      exec --json --shell 'curl -s -u "$ZENDESK_EMAIL/token:$ZENDESK_API_TOKEN" "https://$ZENDESK_SUBDOMAIN.zendesk.com/api/v2/search.json?query=type:user+email:{{customer_email}}"'
    condition: $load-helpdesk-config.json.platform == "zendesk" && $check-immediate-escalation.json.needs_escalation == false

  - id: load-customer-intercom
    command: >
      exec --json --shell 'curl -s -H "Authorization: Bearer $INTERCOM_ACCESS_TOKEN" -H "Accept: application/json" "https://api.intercom.io/contacts?email={{customer_email}}"'
    condition: $load-helpdesk-config.json.platform == "intercom" && $check-immediate-escalation.json.needs_escalation == false

  # Standalone mode: no helpdesk connected — customer data from fast-io
  - id: load-customer-standalone
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "vera-customers/{{customer_email}}"
      }'
    condition: $load-helpdesk-config.json.platform == null && $check-immediate-escalation.json.needs_escalation == false

  # Normalize customer data from whichever provider responded
  - id: load-customer
    command: >
      exec --json --shell 'node -e "
        const input = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const zd = input.zendesk; const ic = input.intercom; const sa = input.standalone;
        let c = {};
        if (zd && zd.results) {
          const u = (zd.results || [])[0] || {};
          c = { name: u.name || null, email: u.email || null, account_id: String(u.id || \"\"), tickets: u.tickets || [], orders: u.orders || [], latest_order_id: u.latest_order_id || null, phone: u.phone || null };
        } else if (ic && ic.data) {
          const u = (ic.data || [])[0] || {};
          c = { name: u.name || null, email: u.email || null, account_id: u.id || null, tickets: [], orders: [], latest_order_id: null, phone: u.phone || null };
        } else {
          c = sa || {};
        }
        process.stdout.write(JSON.stringify(c));
      "'
    stdin: '{"zendesk": $load-customer-zendesk.json, "intercom": $load-customer-intercom.json, "standalone": $load-customer-standalone.json}'
    condition: $check-immediate-escalation.json.needs_escalation == false

  # Step 7: Load conversation history if continuing conversation
  - id: load-conversation
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "vera-conversations/{{conversation_id}}"
      }'
    condition: $check-immediate-escalation.json.needs_escalation == false

  # Step 8: Check exchange count — max 2 before offering escalation (Req 28)
  - id: exchange-check
    command: >
      exec --json --shell 'node -e "
        const conv = JSON.parse(process.env.CONV || \"{}\");
        const exchanges = (conv.exchanges || 0) + 1;
        const offerEscalation = exchanges >= 2 && !conv.resolved;
        process.stdout.write(JSON.stringify({exchanges, offer_escalation: offerEscalation}));
      "'

  # Step 9: RAG retrieval from knowledge base (Req 13)
  - id: rag-retrieve
    command: >
      openclaw.invoke --tool local-rag-qdrant --action query --args-json '{
        "query": "{{customer_message}}",
        "collection": "vera-knowledge-base",
        "limit": 5
      }'
    condition: $check-immediate-escalation.json.needs_escalation == false

  # Step 10: Confidence check (Req 14, 15)
  - id: confidence-check
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Check whether the retrieved knowledge base content directly and unambiguously answers this customer question. Check for: 1) Is the answer directly supported by current documentation? 2) Does any conflicting information exist across the retrieved chunks? 3) Does the topic fall within verified coverage? Return confidence score 0-100.",
        "thinking": "off",
        "input": {
          "question": "{{customer_message}}",
          "retrieved_chunks": $rag-retrieve.json,
          "customer_context": $load-customer.json
        },
        "schema": {
          "type": "object",
          "properties": {
            "confident": {"type": "boolean"},
            "score": {"type": "number"},
            "conflicts_detected": {"type": "boolean"},
            "conflict_details": {"type": ["string", "null"]},
            "stale_articles": {"type": "array", "items": {"type": "string"}},
            "reasoning": {"type": "string"}
          },
          "required": ["confident", "score"]
        }
      }'
    condition: $check-immediate-escalation.json.needs_escalation == false

  # Step 11: Check confidence threshold (Req 15)
  - id: threshold-check
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "vera-config/confidence-threshold"}'
      | exec --json --shell 'node -e "
        const threshold = JSON.parse(process.env.THRESHOLD || \"{}\").value || 0.85;
        const confidence = JSON.parse(process.env.CONFIDENCE || \"{}\");
        const pass = confidence.score >= (threshold * 100);
        process.stdout.write(JSON.stringify({pass, score: confidence.score, threshold: threshold * 100, escalation_trigger: pass ? null : \"confidence\"}));
      "'
    condition: $check-immediate-escalation.json.needs_escalation == false

  # Step 12: Check if action is within authorized scope (Req 17, 18, 49)
  - id: scope-check
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "vera-config/authorized-actions"}'
      | exec --json --shell 'node -e "
        const scope = JSON.parse(process.env.SCOPE || \"{}\");
        const classify = JSON.parse(process.env.CLASSIFY || \"{}\");
        const subcategory = classify.subcategory;
        let withinScope = true;
        let action = null;
        if (subcategory === \"refund\") {
          action = \"refund\";
          // Amount check happens during action execution with actual order data
          withinScope = scope.refunds_enabled !== false;
        } else if (subcategory === \"returns\") {
          action = \"return\";
          withinScope = scope.returns_enabled !== false;
        }
        process.stdout.write(JSON.stringify({within_scope: withinScope, action, subcategory}));
      "'
    condition: $threshold-check.json.pass

  # Step 13: Generate response (Req 16, 34, 38)
  - id: generate-response
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a customer support response. RULES: 1) Answer directly from the retrieved KB content — do not redirect to documentation links. 2) If sentiment is frustrated or angry, open with explicit acknowledgment before the resolution. 3) Respond in the same language as the customer message. 4) If this is exchange 2+ without resolution, include an explicit offer to connect with a human agent. 5) Include what was done, what to expect next. 6) End with a single CSAT question if this resolves the issue: Did we resolve your issue today?",
        "thinking": "low",
        "input": {
          "customer_message": "{{customer_message}}",
          "customer_name": "$load-customer.json.name",
          "kb_content": $rag-retrieve.json,
          "sentiment": $sentiment.json,
          "exchange_count": $exchange-check.json.exchanges,
          "offer_escalation": $exchange-check.json.offer_escalation,
          "conversation_history": $load-conversation.json,
          "action_type": "$scope-check.json.action"
        },
        "schema": {
          "type": "object",
          "properties": {
            "response": {"type": "string"},
            "action_taken": {"type": ["string", "null"]},
            "resolves_issue": {"type": "boolean"},
            "kb_source": {"type": "string"},
            "includes_csat": {"type": "boolean"},
            "includes_escalation_offer": {"type": "boolean"}
          },
          "required": ["response", "resolves_issue"]
        }
      }'
    condition: $threshold-check.json.pass && $check-immediate-escalation.json.needs_escalation == false

  # Step 14: Execute action if needed (Req 17 — refund via Stripe)
  - id: execute-refund
    command: >
      exec --json --shell 'curl -s -X POST "https://api.stripe.com/v1/refunds" -u "$STRIPE_API_KEY:" -d "charge=$ORDER_CHARGE_ID" -d "amount=$REFUND_AMOUNT"'
    condition: $scope-check.json.action == "refund"

  # Step 15: Execute return action if needed (Req 18)
  # Return logged to taskr — actual label creation handled by the agent loop
  # via the user's fulfillment system (direct API integration).
  - id: execute-return
    command: >
      openclaw.invoke --tool taskr --action create --args-json '{
        "key": "vera-returns/{{conversation_id}}",
        "data": {
          "order_id": "$load-customer.json.latest_order_id",
          "customer_email": "{{customer_email}}",
          "return_type": "$scope-check.json.subcategory",
          "status": "pending_fulfillment",
          "timestamp": "{{timestamp}}"
        }
      }'
    condition: $scope-check.json.action == "return"

  # Step 16: Send response to customer
  - id: send-response
    command: >
      openclaw.invoke --tool message --action send --args-json '{
        "channel": "{{channel}}",
        "to": "{{customer_email}}",
        "text": "$generate-response.json.response"
      }'
    condition: $generate-response.json.response

  # Step 17: Update ticket state (Req 44)
  - id: update-state
    command: >
      openclaw.invoke --tool taskr --action update --args-json '{
        "key": "vera-tickets/{{conversation_id}}",
        "data": {
          "status": "$generate-response.json.resolves_issue ? \"pending_confirmation\" : \"open\"",
          "exchanges": $exchange-check.json.exchanges,
          "last_response": "{{timestamp}}",
          "pending_since": "$generate-response.json.resolves_issue ? \"{{timestamp}}\" : null",
          "resolution_method": "autonomous"
        }
      }'

  # Step 18: Update conversation history
  - id: update-conversation
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "vera-conversations/{{conversation_id}}",
        "data": {
          "exchanges": $exchange-check.json.exchanges,
          "resolved": $generate-response.json.resolves_issue,
          "sentiment_history": [$sentiment.json]
        }
      }'

  # Step 19: Log KB gaps if confidence was low (Req 22)
  - id: log-kb-gap
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "vera-kb-gaps/{{date}}/{{conversation_id}}",
        "data": {
          "question": "{{customer_message}}",
          "confidence_score": $confidence-check.json.score,
          "topic": "$confidence-check.json.reasoning",
          "timestamp": "{{timestamp}}"
        }
      }'
    condition: $threshold-check.json.pass == false

  # Step 20: Log KB conflicts (Req 23)
  - id: log-kb-conflict
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "vera-kb-conflicts/{{date}}/{{conversation_id}}",
        "data": {
          "question": "{{customer_message}}",
          "conflict_details": "$confidence-check.json.conflict_details",
          "timestamp": "{{timestamp}}"
        }
      }'
    condition: $confidence-check.json.conflicts_detected

  # Step 21: Log stale articles (Req 25)
  - id: log-stale
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "vera-kb-stale/{{date}}",
        "data": {"articles": $confidence-check.json.stale_articles}
      }'
    condition: $confidence-check.json.stale_articles.length > 0

  # Step 22: Route to escalation pipeline if needed
  - id: route-escalation
    command: >
      openclaw.invoke --tool lobster --action run --args-json '{
        "pipeline": "pipelines/escalation.lobster",
        "argsJson": "{\"conversation_id\": \"{{conversation_id}}\", \"customer_email\": \"{{customer_email}}\", \"escalation_trigger\": \"$check-immediate-escalation.json.trigger || $threshold-check.json.escalation_trigger\", \"customer_message\": \"{{customer_message}}\"}"
      }'
    condition: $check-immediate-escalation.json.needs_escalation || $threshold-check.json.pass == false

  # Step 23: Audit log (Req 48)
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/ticket/{{conversation_id}}",
        "data": {
          "action": "ticket_handled",
          "conversation_id": "{{conversation_id}}",
          "customer_email": "{{customer_email}}",
          "channel": "{{channel}}",
          "classification": "$classify.json.category || $llm-classify.json.category",
          "sentiment": "$sentiment.json.sentiment",
          "confidence_score": "$confidence-check.json.score",
          "kb_source": "$generate-response.json.kb_source",
          "action_taken": "$generate-response.json.action_taken",
          "resolved": "$generate-response.json.resolves_issue",
          "escalated": "$check-immediate-escalation.json.needs_escalation || $threshold-check.json.pass == false",
          "escalation_trigger": "$check-immediate-escalation.json.trigger || $threshold-check.json.escalation_trigger",
          "response_time_ms": "{{response_time}}",
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
