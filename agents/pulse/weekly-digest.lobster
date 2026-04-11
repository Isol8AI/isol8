name: weekly-digest
# Requirements 5, 21, 24, 33, 37, 39, 41-42: Monday marketing intelligence digest.
# Runs Monday 7 AM on cron.
# LLM calls: 3 (voice drift scan, email pattern synthesis, digest narrative)

steps:
  # Step 1: Content performance from biz-reporter + posthog (Req 42)
  - id: load-performance
    command: >
      openclaw.invoke --tool biz-reporter --action report --args-json '{
        "period": "last_7d",
        "include": ["traffic", "conversions", "revenue_attribution"]
      }'

  - id: connect-outcomes
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{"prefix": "pulse-content/published/"}'
      | exec --json --shell 'node scripts/pulse-performance-connector.js'

  # Step 2: GEO Share of Model tracking (Req 24, 39)
  - id: load-geo-queries
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/geo-queries"}'

  - id: geo-sweep
    command: >
      openclaw.invoke --tool tavily --action search --args-json '{
        "query": "$load-geo-queries.json.queries",
        "max_results": 20
      }'

  - id: geo-analysis
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{"prefix": "pulse-geo/share-of-model/"}'
      | exec --json --shell 'node scripts/pulse-geo-monitor.js'

  # Step 3: Email performance (Req 33)
  - id: email-data
    command: >
      exec --json --shell 'node scripts/pulse-email-analyzer.js'

  - id: email-synthesis
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Synthesize these email performance patterns into one actionable insight. What do the best-performing subject lines have in common? Which segment is responding strongest? Where does engagement drop off? Give the marketer one specific thing to change next week.",
        "thinking": "off",
        "input": $email-data.json,
        "schema": {
          "type": "object",
          "properties": {
            "insight": {"type": "string"},
            "best_pattern": {"type": "string"},
            "recommendation": {"type": "string"}
          },
          "required": ["insight", "recommendation"]
        }
      }'

  # Step 4: Voice drift scan on published content (Req 5)
  - id: load-voice-doc
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/brand-voice"}'

  - id: load-published-week
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "pulse-content/published/",
        "filter": "timestamp:last_7d"
      }'

  - id: voice-drift-scan
    command: >
      exec --json --shell 'node scripts/pulse-voice-scorer.js'
    stdin: '{"mode": "batch_drift", "pieces": $load-published-week.json, "voice_doc": $load-voice-doc.json}'

  - id: voice-drift-tone
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Review these published pieces for brand voice drift. Flag specific sentences that sound generic, corporate, or off-brand. Compare the overall tone against the brand voice adjectives. Is the brand voice holding or drifting toward corporate beige?",
        "thinking": "off",
        "input": {
          "pieces": $load-published-week.json,
          "voice_doc": $load-voice-doc.json,
          "deterministic_scores": $voice-drift-scan.json
        },
        "schema": {
          "type": "object",
          "properties": {
            "drift_detected": {"type": "boolean"},
            "drift_direction": {"type": "string"},
            "worst_sentences": {"type": "array", "items": {"type": "string"}},
            "recommendation": {"type": "string"}
          },
          "required": ["drift_detected"]
        }
      }'

  # Step 5: Load monitoring data from the week
  - id: load-monitoring
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "pulse-monitoring/",
        "filter": "timestamp:last_7d"
      }'

  # Step 6: Freshness refresh queue (Req 37)
  - id: freshness-queue
    command: >
      exec --json --shell 'node scripts/pulse-freshness-tracker.js'

  # Step 7: Capability-evolver — weekly learning
  - id: learn
    command: >
      openclaw.invoke --tool capability-evolver --action analyze --args-json '{
        "data": {
          "voice_overrides": "from fast-io pulse-state/voice-overrides",
          "dismissed_claims": "from fast-io pulse-state/approved-claims",
          "review_history": "from fast-io pulse-state/review-history"
        },
        "focus": "Which voice score thresholds are too conservative? Which claim types are consistently approved? Which content formats produce the best outcomes?"
      }'

  # Step 8: Store GEO data for trending
  - id: store-geo
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "pulse-geo/share-of-model/{{date}}",
        "data": $geo-analysis.json
      }'

  # Step 9: Generate digest narrative — ADAPTIVE LLM (Req 21, 41)
  - id: generate-digest
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a Monday marketing intelligence digest. Fit in 5 minutes of reading. End with exactly three action items: one thing to do more of, one thing to change or cut, one opportunity the data surfaced. Adapt your format and tone to this marketer — concise and direct, no fluff. Lead with outcomes, not output volume.",
        "thinking": "low",
        "input": {
          "content_performance": $connect-outcomes.json.top_3_by_outcome,
          "total_attributed_revenue": $connect-outcomes.json.total_attributed_revenue,
          "email": $email-synthesis.json,
          "geo": $geo-analysis.json,
          "voice_drift": $voice-drift-tone.json,
          "monitoring": $load-monitoring.json,
          "freshness": $freshness-queue.json.refresh_queue,
          "learning": $learn.json
        },
        "schema": {
          "type": "object",
          "properties": {
            "digest": {"type": "string"},
            "action_items": {
              "type": "object",
              "properties": {
                "do_more": {"type": "string"},
                "change_or_cut": {"type": "string"},
                "opportunity": {"type": "string"}
              }
            }
          },
          "required": ["digest", "action_items"]
        }
      }'

  # Step 10: Deliver
  - id: notify
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#pulse-content",
        "text": "📊 MONDAY MARKETING DIGEST — {{date}}\n\n$generate-digest.json.digest"
      }'

  # Step 11: Write to Google Sheet for history
  - id: write-sheet
    command: >
      openclaw.invoke --tool gog --action sheets-write --args-json '{
        "spreadsheet": "Pulse Weekly Reports",
        "sheet": "{{date}}",
        "data": {
          "performance": $connect-outcomes.json,
          "geo": $geo-analysis.json,
          "voice": $voice-drift-scan.json,
          "email": $email-data.json
        }
      }'

  # Step 12: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/weekly-digest",
        "data": {
          "action": "weekly_digest",
          "share_of_model": $geo-analysis.json.share_of_model,
          "voice_drift": $voice-drift-tone.json.drift_detected,
          "top_content": $connect-outcomes.json.top_3_by_outcome,
          "refresh_queue_size": $freshness-queue.json.flagged_count,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
