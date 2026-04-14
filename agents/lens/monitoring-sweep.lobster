name: monitoring-sweep
# Requirements 32, 33: Monitor primary sources for changes on configured topics.
# Runs daily on cron.
# LLM calls: 0-2 (unstructured change summaries only when changes detected)

steps:
  # Step 1: Load monitoring configuration
  - id: load-config
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "lens-config/monitoring"}'

  # Step 2: Financial monitoring — SEC EDGAR for tracked companies
  - id: financial-monitor
    command: >
      exec --json --shell 'curl -sS https://api.perplexity.ai/chat/completions
        -H "Authorization: Bearer $PERPLEXITY_API_KEY"
        -H "Content-Type: application/json"
        -d '"'"'{"model":"sonar","messages":[{"role":"user","content":"$load-config.json.financial.tracked_companies new SEC filing 8-K 10-Q last 24 hours"}]}'"'"'
        | node -e "const d=JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\",\"utf8\"));const c=d.choices&&d.choices[0]?d.choices[0].message.content:\"\";const urls=d.citations||[];process.stdout.write(JSON.stringify({content:c,citations:urls,high_value_urls:urls.slice(0,10),total:urls.length}));"'
    condition: $load-config.json.financial.enabled

  # Step 3: Academic monitoring — new papers in configured areas
  - id: academic-monitor
    command: >
      exec --json --shell 'curl -sS https://api.perplexity.ai/chat/completions
        -H "Authorization: Bearer $PERPLEXITY_API_KEY"
        -H "Content-Type: application/json"
        -d '"'"'{"model":"sonar","messages":[{"role":"user","content":"$load-config.json.academic.topics new paper arxiv pubmed"}]}'"'"'
        | node -e "const d=JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\",\"utf8\"));const c=d.choices&&d.choices[0]?d.choices[0].message.content:\"\";const urls=d.citations||[];process.stdout.write(JSON.stringify({content:c,citations:urls,high_value_urls:urls.slice(0,10),total:urls.length}));"'
    condition: $load-config.json.academic.enabled

  # Step 4: Tech monitoring — changelogs, docs, repos
  - id: tech-monitor
    command: >
      openclaw.invoke --tool agent-browser --action browse --args-json '{
        "urls": $load-config.json.technology.tracked_urls,
        "extract": "markdown"
      }'
    condition: $load-config.json.technology.enabled

  # Step 5: Legal/regulatory monitoring
  - id: legal-monitor
    command: >
      exec --json --shell 'curl -sS https://api.perplexity.ai/chat/completions
        -H "Authorization: Bearer $PERPLEXITY_API_KEY"
        -H "Content-Type: application/json"
        -d '"'"'{"model":"sonar","messages":[{"role":"user","content":"$load-config.json.legal.tracked_regulations update revision"}]}'"'"'
        | node -e "const d=JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\",\"utf8\"));const c=d.choices&&d.choices[0]?d.choices[0].message.content:\"\";const urls=d.citations||[];process.stdout.write(JSON.stringify({content:c,citations:urls,high_value_urls:urls.slice(0,10),total:urls.length}));"'
    condition: $load-config.json.legal.enabled

  # Step 6: Competitive monitoring
  - id: competitive-monitor
    command: >
      exec --json --shell 'curl -sS https://api.perplexity.ai/chat/completions
        -H "Authorization: Bearer $PERPLEXITY_API_KEY"
        -H "Content-Type: application/json"
        -d '"'"'{"model":"sonar","messages":[{"role":"user","content":"$load-config.json.competitive.tracked_companies announcement launch"}]}'"'"'
        | node -e "const d=JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\",\"utf8\"));const c=d.choices&&d.choices[0]?d.choices[0].message.content:\"\";const urls=d.citations||[];process.stdout.write(JSON.stringify({content:c,citations:urls,high_value_urls:urls.slice(0,10),total:urls.length}));"'
    condition: $load-config.json.competitive.enabled

  # Step 7: Compare against stored previous versions
  - id: load-previous
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "lens-monitoring/previous-state"}'

  - id: describe-changes
    command: >
      exec --json --shell 'node scripts/lens-change-describer.js'

  # Step 8: For unstructured changes, summarize specifically — LLM
  - id: summarize-changes
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Describe specifically what changed in this source. Not vague — name the section, the number, the policy. Focus on changes that affect the accuracy of existing research findings.",
        "thinking": "off",
        "input": $describe-changes.json
      }'
    condition: $describe-changes.json.needs_llm_summary

  # Step 9: Alert on meaningful changes
  - id: alert-changes
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#lens-research",
        "text": "🔄 SOURCE CHANGE DETECTED\n\n$summarize-changes.json || $describe-changes.json.changes\n\nThis may affect previously verified findings. Review recommended."
      }'
    condition: $describe-changes.json.has_changes

  # Step 10: Store current state as new baseline
  - id: store-current
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "lens-monitoring/previous-state",
        "data": {
          "financial": $financial-monitor.json,
          "academic": $academic-monitor.json,
          "technology": $tech-monitor.json,
          "legal": $legal-monitor.json,
          "competitive": $competitive-monitor.json,
          "captured_at": "{{timestamp}}"
        }
      }'

  # Step 11: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/monitoring-sweep",
        "data": {
          "action": "monitoring_sweep",
          "changes_detected": $describe-changes.json.has_changes,
          "verticals_monitored": $load-config.json,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
