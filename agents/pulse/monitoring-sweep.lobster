name: monitoring-sweep
# Requirements 22-27: Daily autonomous monitoring operations.
# Runs daily on cron (configurable time).
# LLM calls: 0-1 (sentiment analysis on ambiguous mentions only)

steps:
  # Step 1: Brand mention monitoring (Req 22)
  - id: mention-scan
    command: >
      openclaw.invoke --tool tavily --action search --args-json '{
        "query": "\"$BRAND_NAME\" OR \"$PRODUCT_NAME\"",
        "max_results": 20
      }'

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
      openclaw.invoke --tool tavily --action search --args-json '{
        "query": "$competitor-scan.json.names content blog announcement",
        "max_results": 15
      }'

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
      openclaw.invoke --tool tavily --action search --args-json '{
        "query": "$load-subreddits.json.queries site:reddit.com",
        "max_results": 15
      }'

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
  - id: freshness-check
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-content/published/"}'
      | exec --json --shell 'node scripts/pulse-freshness-tracker.js'

  # Step 6: Content calendar conflict check (Req 27)
  - id: load-scheduled
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{"prefix": "pulse-content/approved/"}'

  - id: news-check
    command: >
      openclaw.invoke --tool tavily --action search --args-json '{
        "query": "breaking news today $BRAND_CATEGORY",
        "max_results": 5
      }'

  - id: calendar-conflict
    command: >
      exec --json --shell 'node scripts/pulse-calendar-conflict-checker.js'

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
      openclaw.invoke --tool tavily --action search --args-json '{
        "query": "$check-followups.json.thread_urls",
        "max_results": 5
      }'
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
