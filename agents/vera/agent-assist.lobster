name: agent-assist
# Requirements 40, 41, 42: Real-time background assist for human agents.
# Triggered when a human agent picks up an escalated ticket in Slack.
# LLM calls: 1 (response draft)

args:
  conversation_id:
    required: true
  customer_email:
    required: true
  agent_message:
    default: ""

steps:
  # Step 1: Load escalation package (already built during escalation)
  - id: load-escalation
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{
        "key": "audit/*/escalation/{{conversation_id}}"
      }'

  # Step 2: RAG retrieval for relevant KB articles (Req 40)
  - id: rag-articles
    command: >
      openclaw.invoke --tool local-rag-qdrant --action query --args-json '{
        "query": "$load-escalation.json.issue_summary",
        "collection": "vera-knowledge-base",
        "limit": 5
      }'

  # Step 3: Draft suggested response (Req 41)
  - id: draft-response
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Draft a suggested response for the human support agent handling this escalated ticket. Ground it in the KB content. Account for the customer sentiment and conversation history. This is a draft for the agent to modify, not a final response.",
        "thinking": "low",
        "input": {
          "escalation_context": $load-escalation.json,
          "kb_articles": $rag-articles.json,
          "agent_message": "{{agent_message}}"
        },
        "schema": {
          "type": "object",
          "properties": {
            "draft_response": {"type": "string"},
            "relevant_policies": {"type": "array", "items": {"type": "string"}},
            "caution_flags": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["draft_response"]
        }
      }'

  # Step 4: Summarize conversation if long (zero LLM — CLI)
  - id: summarize-history
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $load-escalation.json.conversation,
        "format": "agent-brief"
      }'

  # Step 5: Post assist package to agent in Slack thread (not to customer)
  - id: post-assist
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#vera-escalations",
        "thread": "{{escalation_thread_id}}",
        "text": "🤖 **VERA ASSIST**\n\n**Relevant KB articles:**\n$rag-articles.json\n\n**Relevant policies:**\n$draft-response.json.relevant_policies\n\n**Caution flags:**\n$draft-response.json.caution_flags\n\n**Draft response:**\n$draft-response.json.draft_response\n\n_Edit and send from your account — this is a starting point, not a final response._"
      }'
