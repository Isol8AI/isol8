name: expense-intake
# Requirements 7, 8, 9, 11: Plain language expense input from anyone in org.
# Triggered per message in #expenses Slack channel.
# LLM calls: 1 (plain language extraction)

args:
  message:
    required: true
  submitter:
    required: true
  channel:
    default: "slack"

steps:
  # Step 1: Extract structured data from plain language — GENUINE LLM TASK
  - id: extract
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Extract structured financial data from this plain language expense or income input. If any field is unclear or ambiguous, set confidence below 0.7 and explain what is missing in the ambiguity_note field. Never guess — leave fields null if you cannot determine them.",
        "thinking": "off",
        "input": {"message": "{{message}}", "submitter": "{{submitter}}"},
        "schema": {
          "type": "object",
          "properties": {
            "amount": {"type": ["number", "null"]},
            "vendor": {"type": ["string", "null"]},
            "category": {"type": ["string", "null"]},
            "subcategory": {"type": ["string", "null"]},
            "date": {"type": ["string", "null"]},
            "description": {"type": ["string", "null"]},
            "type": {"type": "string", "enum": ["expense", "income"]},
            "confidence_score": {"type": "number"},
            "ambiguity_note": {"type": ["string", "null"]}
          },
          "required": ["amount", "type", "confidence_score"]
        }
      }'

  # Step 2: Load vendor mapping and chart of accounts
  - id: load-vendor-map
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "tally-learning/vendor-map"}'

  - id: load-chart
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "tally-config/chart-of-accounts"}'

  # Step 3: Apply vendor mapping + confidence check (Req 9, 10)
  - id: validate
    command: >
      exec --json --shell 'node scripts/tally-categorization-engine.js'
    stdin: '{"mode": "check", "extraction": $extract.json, "vendor_map": $load-vendor-map.json}'

  # Step 4a: If ambiguous, ask submitter for clarification (Req 9)
  - id: clarify
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#expenses",
        "thread": "{{thread_id}}",
        "text": "Hey {{submitter}}, I need a bit more info on this one:\n\n$extract.json.ambiguity_note\n\nCan you clarify so I can categorize it correctly?"
      }'
    condition: $validate.json.confidence_check.route == "ambiguity_flow"

  # Step 4b: If clear, confirm interpretation back to submitter (Req 8)
  - id: confirm-interpretation
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#expenses",
        "thread": "{{thread_id}}",
        "text": "Got it — $${extract.json.amount} classified as $validate.json.category ($validate.json.subcategory) from $validate.json.vendor. This will go to your finance person for review. ✅"
      }'
    condition: $validate.json.confidence_check.route != "ambiguity_flow"

  # Step 5: Tax tagging (Req 45)
  - id: tax-tag
    command: >
      exec --json --shell 'node scripts/tally-tax-tracker.js'
    stdin: '{"mode": "tag", "transaction": $validate.json}'
    condition: $validate.json.confidence_check.route != "ambiguity_flow"

  # Step 6: Queue for finance person approval (Req 11)
  - id: queue-approval
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "tally-approvals/pending/{{timestamp}}-{{submitter}}",
        "data": {
          "entry": $validate.json,
          "tax_tag": $tax-tag.json.tax_tag,
          "cpa_flags": $tax-tag.json.cpa_flags,
          "submitter": "{{submitter}}",
          "original_message": "{{message}}",
          "source": "plain_language_input",
          "status": "pending_approval",
          "queued_at": "{{timestamp}}"
        }
      }'
    condition: $validate.json.confidence_check.route != "ambiguity_flow"

  # Step 7: Notify finance person
  - id: notify-finance
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#tally-approvals",
        "text": "📝 NEW EXPENSE from {{submitter}}\n\n**$${extract.json.amount}** — $validate.json.category\nVendor: $validate.json.vendor\nDescription: $extract.json.description\nConfidence: $validate.json.mapping_confidence\n\n[Approve] [Edit] [Reject]"
      }'
    condition: $validate.json.confidence_check.route != "ambiguity_flow"

  # Step 8: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/expense-intake/{{submitter}}",
        "data": {
          "action": "expense_intake",
          "submitter": "{{submitter}}",
          "amount": $extract.json.amount,
          "category": "$validate.json.category",
          "confidence": $extract.json.confidence_score,
          "source": "plain_language_slack",
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
