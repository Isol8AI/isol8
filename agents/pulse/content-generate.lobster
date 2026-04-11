name: content-generate
# Requirements 1, 6, 8-11, 13-14, 16, 48: Full content generation with research, voice, GEO.
# Triggered per content request from marketer or content calendar.
# LLM calls: 3-5 (research synthesis, draft generation, voice tone check, per-adaptation)

args:
  topic:
    required: true
  content_type:
    default: "blog_post"
  target_platform:
    default: ""
  repurpose:
    default: true

steps:
  # Step 1: Queue limit check (Req 48)
  - id: queue-check
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-state/queue-size"}'
      | exec --json --shell 'node scripts/pulse-queue-limiter.js'

  - id: queue-gate
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#pulse-content",
        "text": "$queue-check.json.message"
      }'
    condition: $queue-check.json.at_limit || $queue-check.json.rubber_stamping_detected

  # Step 2: Load brand voice document (Req 1)
  - id: load-voice
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/brand-voice"}'
    condition: $queue-check.json.at_limit == false

  # Step 3: Research pull — 5 sources (Req 8, 9)
  - id: research-competitors
    command: >
      openclaw.invoke --tool tavily --action search --args-json '{
        "query": "{{topic}} competitor content",
        "max_results": 10
      }'

  - id: research-community
    command: >
      openclaw.invoke --tool tavily --action search --args-json '{
        "query": "{{topic}} reddit questions discussion",
        "max_results": 10
      }'

  - id: research-search
    command: >
      openclaw.invoke --tool tavily --action search --args-json '{
        "query": "{{topic}} search trends data 2026",
        "max_results": 5
      }'

  - id: research-industry
    command: >
      openclaw.invoke --tool agent-browser --action read --args-json '{
        "query": "{{topic}} industry analysis report",
        "max_results": 3
      }'

  - id: research-internal
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "pulse-content/published/",
        "filter": "topic:{{topic}}"
      }'

  # Step 4: Compress research into structured brief
  - id: compile-brief
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": {
          "competitors": $research-competitors.json,
          "community": $research-community.json,
          "search": $research-search.json,
          "industry": $research-industry.json,
          "internal": $research-internal.json
        },
        "format": "content-brief"
      }'

  # Step 5: Load platform tone guidance and GEO requirements
  - id: load-platform-config
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/platform-tones"}'

  # Step 6: Generate draft — LLM CALL (Req 10)
  - id: generate-draft
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a {{content_type}} on the topic: {{topic}}. Apply the brand voice document strictly. Structure for GEO: direct answer in first 40-60 words, specific statistic with source every 150-200 words, definitive language, FAQ section, comparative tables where relevant. Ground every claim in the research brief — do not invent statistics or capabilities.",
        "thinking": "low",
        "input": {
          "brand_voice": $load-voice.json,
          "research_brief": $compile-brief.stdout,
          "platform": "{{target_platform}}",
          "content_type": "{{content_type}}"
        },
        "schema": {
          "type": "object",
          "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "meta_description": {"type": "string"},
            "target_query": {"type": "string"},
            "sources_used": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["title", "body"]
        }
      }'

  # Step 7: Voice score — deterministic + LLM tone check (Req 6)
  - id: voice-score-deterministic
    command: >
      exec --json --shell 'node scripts/pulse-voice-scorer.js'
    stdin: '{"mode": "score", "text": "$generate-draft.json.body", "voice_doc": $load-voice.json}'

  - id: voice-score-tone
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Score this content against the brand voice tone scales. For each tone dimension, rate 1-10 and flag any sentences that pull the score down. Also check: does this sound like the brand, or does it sound like generic AI output?",
        "thinking": "off",
        "input": {
          "text": "$generate-draft.json.body",
          "tone_scales": $load-voice.json.tone_scales,
          "adjectives": $load-voice.json.adjectives
        },
        "schema": {
          "type": "object",
          "properties": {
            "tone_scores": {"type": "object"},
            "overall_voice_score": {"type": "number"},
            "flagged_sentences": {"type": "array", "items": {"type": "string"}},
            "sounds_like_brand": {"type": "boolean"}
          },
          "required": ["overall_voice_score", "sounds_like_brand"]
        }
      }'

  # Step 8: GEO structural check (Req 10, 11)
  - id: geo-check
    command: >
      exec --json --shell 'node scripts/pulse-geo-checker.js'
    stdin: '{"text": "$generate-draft.json.body", "target_platform": "{{target_platform}}"}'

  # Step 9: Sensitive claim detection (Req 35)
  - id: claim-check
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-state/approved-claims"}'
      | exec --json --shell 'node scripts/pulse-sensitive-claim-detector.js'

  # Step 10: Calendar conflict check (Req 17)
  - id: calendar-check
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "pulse-config/cultural-calendar"}'
      | exec --json --shell 'node scripts/pulse-calendar-conflict-checker.js'

  # Step 11: Generate repurposing set if requested (Req 13, 14)
  - id: repurpose-set
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Repurpose this long-form content into platform-specific adaptations. Each is a DISTINCT piece with its own voice application — not a copy-paste. Apply the brand voice independently to each. LinkedIn should sound professional and insight-driven. Twitter should be punchy and quotable. Email should be personal and direct. Reddit-ready should sound like a genuine community member sharing expertise.",
        "thinking": "off",
        "input": {
          "original": "$generate-draft.json.body",
          "brand_voice": $load-voice.json,
          "platform_tones": $load-platform-config.json
        },
        "schema": {
          "type": "object",
          "properties": {
            "linkedin": {"type": "string"},
            "twitter": {"type": "string"},
            "email_snippet": {"type": "string"},
            "reddit_ready": {"type": "string"},
            "short_summary": {"type": "string"}
          },
          "required": ["linkedin", "twitter", "email_snippet"]
        }
      }'
    condition: $repurpose == true

  # Step 12: Queue all content for review
  - id: queue-draft
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "pulse-content/drafts/{{timestamp}}",
        "data": {
          "draft": $generate-draft.json,
          "repurposing_set": $repurpose-set.json,
          "voice_score": {
            "deterministic": $voice-score-deterministic.json,
            "tone": $voice-score-tone.json,
            "combined": $voice-score-tone.json.overall_voice_score
          },
          "geo_check": $geo-check.json,
          "claim_flags": $claim-check.json,
          "calendar_check": $calendar-check.json,
          "research_brief": "$compile-brief.stdout",
          "status": "pending_review",
          "created_at": "{{timestamp}}"
        }
      }'

  # Step 13: Notify marketer — full review package (Req 16)
  - id: notify-review
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#pulse-content",
        "text": "📝 NEW DRAFT — $generate-draft.json.title\n\n🎯 Voice Score: $voice-score-tone.json.overall_voice_score/100\n$voice-score-deterministic.json.flags\n\n📊 GEO Score: $geo-check.json.geo_score/100 ($geo-check.json.passed/$geo-check.json.total checks passed)\n\n⚠️ Claims to verify: $claim-check.json.needs_review\n📅 Calendar conflicts: $calendar-check.json.has_conflicts\n\n📖 Read this aloud. If any sentence sounds like it came from a committee, flag it before approving.\n\n[Approve] [Revise] [Reject]"
      }'

  # Step 14: Audit log (Req 20)
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/content-generate",
        "data": {
          "action": "content_generated",
          "topic": "{{topic}}",
          "content_type": "{{content_type}}",
          "voice_score": $voice-score-tone.json.overall_voice_score,
          "geo_score": $geo-check.json.geo_score,
          "claims_flagged": $claim-check.json.needs_review,
          "calendar_conflicts": $calendar-check.json.has_conflicts,
          "repurposed": $repurpose,
          "authorized_by": "autonomous_draft",
          "timestamp": "{{timestamp}}"
        }
      }'
