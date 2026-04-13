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
  # Run each GEO query against Perplexity sonar individually, then count brand
  # citations across responses. Deterministic: one call per query, structured
  # response shape. NOT an LLM reasoning call — Perplexity sonar is a search API,
  # and its answer is the actual Share-of-Model signal we're measuring (did
  # Perplexity cite the brand when asked a customer query). Iteration has to
  # happen in node because curl can't loop, so this step is inline node fetch
  # rather than curl | node. Same API, same deterministic character.
  - id: load-geo-queries
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/geo-queries"}'

  - id: load-competitors
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/competitors"}'

  - id: load-prior-geo
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{"prefix": "pulse-geo/share-of-model/"}'

  - id: geo-sweep
    command: >
      exec --json --shell 'node -e "
        const input = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const queries = input.queries || [];
        (async () => {
          const out = [];
          for (const q of queries) {
            try {
              const res = await fetch(\"https://api.perplexity.ai/chat/completions\", {
                method: \"POST\",
                headers: {\"Authorization\": \"Bearer \" + process.env.PERPLEXITY_API_KEY, \"Content-Type\": \"application/json\"},
                body: JSON.stringify({model: \"sonar\", messages: [{role: \"user\", content: q}]})
              });
              const j = await res.json();
              const content = (j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content) || \"\";
              const citations = j.citations || [];
              out.push({query: q, platform: \"perplexity\", response: content, sources_cited: citations});
            } catch (e) {
              out.push({query: q, platform: \"perplexity\", response: \"\", sources_cited: [], error: e.message});
            }
          }
          process.stdout.write(JSON.stringify({query_results: out}));
        })();
      "'
    stdin: '{"queries": $load-geo-queries.json.queries}'

  - id: geo-analysis
    command: >
      exec --json --shell 'node scripts/pulse-geo-monitor.js'
    stdin: '{
      "query_results": $geo-sweep.json.query_results,
      "brand_name": "$BRAND_NAME",
      "competitors": $load-competitors.json.names,
      "prior_weeks": $load-prior-geo.json
    }'

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
  - id: load-archive
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{"prefix": "pulse-content/published/"}'

  - id: freshness-queue
    command: >
      exec --json --shell 'node scripts/pulse-freshness-tracker.js'
    stdin: '{"content_archive": $load-archive.json, "citation_data": {}}'

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
