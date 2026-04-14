name: weekly-report
# Requirements 22, 23, 25, 45, 46, 47: Weekly metrics + learning.
# Runs Monday 8 AM on cron.
# LLM calls: 2 (CSAT failure classification batch, KB gap clustering)

steps:
  # Step 1: Load all ticket data for the week
  - id: load-tickets
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "audit/",
        "filter": "action:ticket_handled AND timestamp:last_7d"
      }'

  # Step 2: Load all escalation data
  - id: load-escalations
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "audit/",
        "filter": "action:escalation AND timestamp:last_7d"
      }'

  # Step 3: Load CSAT scores
  - id: load-csat
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "vera-csat/",
        "filter": "timestamp:last_7d"
      }'

  # Step 4: Load KB gaps
  - id: load-kb-gaps
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "vera-kb-gaps/",
        "filter": "timestamp:last_7d"
      }'

  # Step 5: Load KB conflicts
  - id: load-kb-conflicts
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "vera-kb-conflicts/",
        "filter": "timestamp:last_7d"
      }'

  # Step 6: Load stale articles
  - id: load-stale
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "vera-kb-stale/"
      }'

  # Step 7: Calculate all metrics deterministically (Req 45, 47)
  - id: calculate-metrics
    command: >
      exec --json --shell 'node scripts/vera-metrics-calculator.js'

  # Step 8: Cluster KB gaps by topic — LLM CALL 1 (Req 22)
  - id: cluster-gaps
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Group these unanswered customer questions into themes. Questions that ask the same thing in different words should be in the same group. Return groups ranked by frequency.",
        "thinking": "low",
        "input": $load-kb-gaps.json,
        "schema": {
          "type": "object",
          "properties": {
            "gap_clusters": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "theme": {"type": "string"},
                  "count": {"type": "number"},
                  "example_questions": {"type": "array", "items": {"type": "string"}},
                  "recommended_kb_article": {"type": "string"}
                },
                "required": ["theme", "count"]
              }
            },
            "total_gaps": {"type": "number"}
          },
          "required": ["gap_clusters"]
        }
      }'
    condition: $load-kb-gaps.json.length > 0

  # Step 9: Classify CSAT failures — LLM CALL 2 (Req 46)
  - id: classify-failures
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "For each low-CSAT ticket, read the conversation and classify the failure root cause. Categories: kb_gap (answer wasnt in knowledge base), incorrect_escalation (should have escalated sooner or shouldnt have escalated), sentiment_failure (didnt acknowledge frustration appropriately), confidence_miscalibration (answered when it shouldnt have or escalated when it didnt need to), policy_boundary (customer wanted something outside policy). Be specific about what went wrong.",
        "thinking": "low",
        "input": $load-csat.json,
        "schema": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "ticket_id": {"type": "string"},
              "csat_score": {"type": "number"},
              "failure_type": {"type": "string", "enum": ["kb_gap", "incorrect_escalation", "sentiment_failure", "confidence_miscalibration", "policy_boundary", "other"]},
              "explanation": {"type": "string"},
              "recommended_fix": {"type": "string"}
            },
            "required": ["ticket_id", "failure_type", "explanation"]
          }
        }
      }'
    condition: $load-csat.json.length > 0

  # Step 10: Capability-evolver pattern analysis
  - id: pattern-analysis
    command: >
      openclaw.invoke --tool capability-evolver --action analyze --args-json '{
        "metrics": $calculate-metrics.stdout,
        "failures": $classify-failures.json,
        "gaps": $cluster-gaps.json,
        "focus": "identify recurring patterns and recommend specific improvements"
      }'

  # Step 11: Compile full report (zero LLM — summarize CLI)
  - id: compile-report
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": {
          "metrics": $calculate-metrics.stdout,
          "kb_gaps": $cluster-gaps.json,
          "kb_conflicts": $load-kb-conflicts.json,
          "stale_articles": $load-stale.json,
          "csat_failures": $classify-failures.json,
          "patterns": $pattern-analysis.json
        },
        "format": "weekly-support-report"
      }'

  # Step 12: Write to Google Sheet
  - id: write-report
    command: >
      openclaw.invoke --tool gog --action sheets-write --args-json '{
        "spreadsheet": "Vera Weekly Reports",
        "sheet": "{{date}}",
        "data": $calculate-metrics.stdout
      }'

  # Step 13: Write narrative report to Google Doc
  - id: write-narrative
    command: >
      openclaw.invoke --tool gog --action drive-write --args-json '{
        "file": "Vera Weekly Report — {{date}}",
        "content": $compile-report.stdout,
        "folder": "Vera Reports"
      }'

  # Step 14: Post to Slack
  - id: notify
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#vera-digest",
        "text": "📊 WEEKLY SUPPORT REPORT — {{date}}\n\n$compile-report.stdout\n\nFull report: $write-narrative.json.url\nMetrics sheet: $write-report.json.url"
      }'

  # Step 15: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/weekly-report",
        "data": {
          "action": "weekly_report",
          "metrics": $calculate-metrics.stdout,
          "gap_clusters": $cluster-gaps.json,
          "failure_classifications": $classify-failures.json,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
