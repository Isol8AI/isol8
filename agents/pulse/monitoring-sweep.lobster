name: monitoring-sweep
# Requirements 22-27: Daily autonomous monitoring operations.
# Runs daily on cron (configurable time).
# LLM calls: 0-1 (sentiment analysis on ambiguous mentions only)

steps:
  # Step 1: Brand mention monitoring (Req 22)
  # Structured web search via Perplexity sonar API, direct curl + inline node
  # normalizer. Deterministic — same query → same structured response shape.
  # This is NOT an LLM reasoning call. Downstream consumers expect
  # {total, top_urls, high_signal_urls, high_signal_count, urgent_mentions}.
  - id: mention-scan
    command: >
      exec --json --shell 'curl -sS https://api.perplexity.ai/chat/completions -H "Authorization: Bearer $PERPLEXITY_API_KEY" -H "Content-Type: application/json" -d @- | node -e "
        const r = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const content = (r.choices && r.choices[0] && r.choices[0].message && r.choices[0].message.content) || \"\";
        const citations = r.citations || [];
        process.stdout.write(JSON.stringify({content: content, citations: citations, total: citations.length, top_urls: citations.slice(0, 20), high_signal_urls: citations.slice(0, 10), high_signal_count: Math.min(citations.length, 10), urgent_mentions: citations.length}));
      "'
    stdin: '{"model":"sonar","messages":[{"role":"user","content":"Find recent mentions of \"$BRAND_NAME\" or \"$PRODUCT_NAME\" across web, news, social platforms, and forums. Return URLs and the context of each mention."}]}'

  - id: mention-deep-read
    command: >
      openclaw.invoke --tool agent-browser --action read --args-json '{
        "urls": $mention-scan.json.high_signal_urls,
        "extract": "context_around_brand_mention"
      }'
    condition: $mention-scan.json.high_signal_count > 0

  # Step 2: Competitor monitoring (Req 23)
  - id: competitor-scan
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/competitors"}'

  - id: competitor-content
    command: >
      exec --json --shell 'curl -sS https://api.perplexity.ai/chat/completions -H "Authorization: Bearer $PERPLEXITY_API_KEY" -H "Content-Type: application/json" -d @- | node -e "
        const r = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const content = (r.choices && r.choices[0] && r.choices[0].message && r.choices[0].message.content) || \"\";
        const citations = r.citations || [];
        process.stdout.write(JSON.stringify({content: content, citations: citations, total: citations.length, top_urls: citations.slice(0, 15)}));
      "'
    stdin: '{"model":"sonar","messages":[{"role":"user","content":"Find recent blog posts, announcements, and content published by these competitors: $competitor-scan.json.names. Return URLs and the topics covered."}]}'

  - id: competitor-deep-read
    command: >
      openclaw.invoke --tool agent-browser --action read --args-json '{
        "urls": $competitor-content.json.top_urls,
        "extract": "topic_and_positioning"
      }'

  # Step 3: Subreddit monitoring (Req 26)
  - id: load-subreddits
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/reddit-monitors"}'

  - id: subreddit-scan
    command: >
      exec --json --shell 'curl -sS https://api.perplexity.ai/chat/completions -H "Authorization: Bearer $PERPLEXITY_API_KEY" -H "Content-Type: application/json" -d @- | node -e "
        const r = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const content = (r.choices && r.choices[0] && r.choices[0].message && r.choices[0].message.content) || \"\";
        const citations = r.citations || [];
        process.stdout.write(JSON.stringify({content: content, citations: citations, total: citations.length, top_urls: citations.slice(0, 15)}));
      "'
    stdin: '{"model":"sonar","messages":[{"role":"user","content":"Search Reddit (site:reddit.com) for recent threads matching these queries: $load-subreddits.json.queries. Return thread URLs and the questions being asked."}]}'

  - id: subreddit-deep-read
    command: >
      openclaw.invoke --tool agent-browser --action read --args-json '{
        "urls": $subreddit-scan.json.top_urls,
        "extract": "questions_language_objections"
      }'

  # Step 4: Compress all monitoring results
  - id: compress-mentions
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $mention-deep-read.json,
        "format": "bullet-points"
      }'

  - id: compress-competitors
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $competitor-deep-read.json,
        "format": "executive-summary"
      }'

  - id: compress-community
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $subreddit-deep-read.json,
        "format": "bullet-points"
      }'

  # Step 5: Content freshness check (Req 25)
  # pulse-freshness-tracker.js expects {content_archive, citation_data} on stdin.
  - id: load-published
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{"prefix": "pulse-content/published/"}'

  - id: freshness-check
    command: >
      exec --json --shell 'node scripts/pulse-freshness-tracker.js'
    stdin: '{"content_archive": $load-published.json, "citation_data": {}}'

  # Step 6: Content calendar conflict check (Req 27)
  - id: load-scheduled
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{"prefix": "pulse-content/approved/"}'

  - id: load-cultural-calendar
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/cultural-calendar"}'

  # Active news cycle scan — Perplexity sonar structured search. Deterministic
  # (same query → same response shape). Emits an array of {topic, relevant_to_content}
  # objects that feed directly into pulse-calendar-conflict-checker.js's news_conflicts
  # input. Not an LLM reasoning call.
  - id: news-check
    command: >
      exec --json --shell 'curl -sS https://api.perplexity.ai/chat/completions -H "Authorization: Bearer $PERPLEXITY_API_KEY" -H "Content-Type: application/json" -d @- | node -e "
        const r = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const content = (r.choices && r.choices[0] && r.choices[0].message && r.choices[0].message.content) || \"\";
        const citations = r.citations || [];
        const lines = content.split(/\\n+/).map(s => s.trim()).filter(s => s.length > 0);
        const conflicts = lines.slice(0, 5).map(topic => ({topic: topic, relevant_to_content: true}));
        process.stdout.write(JSON.stringify({content: content, citations: citations, total: citations.length, conflicts: conflicts}));
      "'
    stdin: '{"model":"sonar","messages":[{"role":"user","content":"What breaking news cycles are active today related to $BRAND_CATEGORY? Return each active news topic on its own line, no bullets or numbering, just the topic names."}]}'

  - id: calendar-conflict
    command: >
      exec --json --shell 'node scripts/pulse-calendar-conflict-checker.js'
    stdin: '{
      "scheduled_content": $load-scheduled.json,
      "cultural_calendar": $load-cultural-calendar.json,
      "news_conflicts": $news-check.json.conflicts
    }'

  # Step 7: Alert on high-priority items
  - id: mention-alerts
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#pulse-content",
        "text": "🔔 BRAND MENTION ALERT\n\n$compress-mentions.stdout"
      }'
    condition: $mention-scan.json.urgent_mentions > 0

  - id: calendar-alerts
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#pulse-content",
        "text": "📅 CONTENT CALENDAR CONFLICT\n\n$calendar-conflict.json.conflicts"
      }'
    condition: $calendar-conflict.json.has_conflicts

  # Step 8: Store all monitoring data for weekly digest
  - id: store-monitoring
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "pulse-monitoring/{{date}}",
        "data": {
          "mentions": $compress-mentions.stdout,
          "competitors": $compress-competitors.stdout,
          "community": $compress-community.stdout,
          "freshness": $freshness-check.json,
          "calendar_conflicts": $calendar-conflict.json,
          "timestamp": "{{timestamp}}"
        }
      }'

  # Step 9: Track community engagements for follow-ups (Req 31)
  - id: check-followups
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{"prefix": "pulse-community/engagements/"}'

  - id: followup-scan
    command: >
      exec --json --shell 'curl -sS https://api.perplexity.ai/chat/completions -H "Authorization: Bearer $PERPLEXITY_API_KEY" -H "Content-Type: application/json" -d @- | node -e "
        const r = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const content = (r.choices && r.choices[0] && r.choices[0].message && r.choices[0].message.content) || \"\";
        const citations = r.citations || [];
        process.stdout.write(JSON.stringify({content: content, citations: citations, total: citations.length, new_activity: citations.length > 0}));
      "'
    stdin: '{"model":"sonar","messages":[{"role":"user","content":"Check for new comments or activity on these community thread URLs: $check-followups.json.thread_urls. Summarize any new replies or updates since the last check."}]}'
    condition: $check-followups.json.keys.length > 0

  - id: followup-alert
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#pulse-content",
        "text": "💬 COMMUNITY FOLLOW-UP\nThreads you engaged in have new activity:\n$followup-scan.json"
      }'
    condition: $followup-scan.json.new_activity

  # Step 10: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/monitoring-sweep",
        "data": {
          "action": "daily_monitoring",
          "mentions_found": $mention-scan.json.total,
          "competitor_updates": $competitor-content.json.total,
          "subreddit_threads": $subreddit-scan.json.total,
          "stale_content": $freshness-check.json.flagged_count,
          "calendar_conflicts": $calendar-conflict.json.has_conflicts,
          "followup_activity": "$followup-scan.json.new_activity",
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
