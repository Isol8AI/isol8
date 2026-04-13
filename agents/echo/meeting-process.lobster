name: meeting-process
# Requirements 5-30: Full pipeline from transcript ingestion to approved distribution.
# Triggered per meeting via webhook or calendar sweep.
# LLM calls: 3 (ambiguous commitment classification, summary generation, follow-up email draft)

args:
  meeting_id:
    required: true

steps:
  # Step 1: Verify consent was in place for this meeting — Tier 2 gate.
  # Hard-blocks processing if echo-config/consent is missing or not confirmed.
  - id: verify-consent
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "echo-config/consent"}'

  - id: consent-gate
    command: >
      exec --json --shell 'node -e "
        const consent = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        if (!consent || !consent.confirmed) {
          process.stderr.write(\"HARD BLOCK: Recording consent not confirmed. Echo cannot process this meeting.\");
          process.exit(1);
        }
        process.stdout.write(JSON.stringify({pass: true}));
      "'
    stdin: $verify-consent.stdout

  # Step 2: Load meeting metadata from calendar
  - id: load-meeting
    command: >
      openclaw.invoke --tool gog --action gcal-get-event --args-json '{
        "event_id": "{{meeting_id}}"
      }'

  # Step 3: Load meeting type templates config (defaults live in the formatter)
  - id: load-templates
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "echo-config/templates"}'

  # Step 4: Load prior meeting context via meeting-prep skill
  - id: prior-context
    command: >
      openclaw.invoke --tool meeting-prep --action prepare --args-json '{
        "attendees": "$load-meeting.json.attendees",
        "meeting_title": "$load-meeting.json.title"
      }'

  # Step 5: Read the user's connected meeting platforms. The Isol8 settings UI
  # writes this key when the user click-to-connects Zoom, Google Meet, or Teams.
  # Multiple platforms can be connected simultaneously — Echo pulls transcripts
  # from whichever platform hosted this meeting.
  - id: load-connected-platforms
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "echo-config/connected-meeting-platforms"}'

  # If nothing is connected, surface the click-to-connect notice and exit early.
  - id: no-platform-notice
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#echo-meetings",
        "text": "To process meeting transcripts, connect a meeting platform in your settings. Supported: Zoom, Google Meet, Microsoft Teams."
      }'
    condition: $load-connected-platforms.json.zoom.connected != true && $load-connected-platforms.json.gmeet.connected != true && $load-connected-platforms.json.teams.connected != true

  # Step 6: Pull the transcript directly from whichever connected meeting platform
  # hosted this meeting (deterministic API calls, parallel conditional branches).
  # Zoom: Cloud Recording Transcript API via direct curl.
  # Google Meet: recordings + captions live in Drive and are pulled via gog.
  # Teams: recordings are pulled via ms365 (Graph API).
  - id: pull-zoom-transcript
    command: >
      exec --json --shell 'curl -s -H "Authorization: Bearer $ZOOM_OAUTH_TOKEN" "https://api.zoom.us/v2/meetings/{{meeting_id}}/recordings/transcript"'
    condition: $load-connected-platforms.json.zoom.connected == true

  - id: pull-gmeet-transcript
    command: >
      openclaw.invoke --tool gog --action drive-get-meet-captions --args-json '{
        "meeting_id": "{{meeting_id}}",
        "attendees": $load-meeting.json.attendees
      }'
    condition: $load-connected-platforms.json.gmeet.connected == true

  - id: pull-teams-transcript
    command: >
      openclaw.invoke --tool ms365 --action get-meeting-transcript --args-json '{
        "meeting_id": "{{meeting_id}}"
      }'
    condition: $load-connected-platforms.json.teams.connected == true

  # Step 7: Normalize whichever provider's response we got into a canonical
  # segment shape that echo-audio-preprocessor.js consumes (deterministic script).
  - id: normalize-transcript
    command: >
      exec --json --shell 'node scripts/echo-transcript-normalizer.js'
    stdin: '{
      "zoom": $pull-zoom-transcript.json,
      "gmeet": $pull-gmeet-transcript.json,
      "teams": $pull-teams-transcript.json
    }'

  # Step 8: Audio preprocessing — silence flagging + confidence check +
  # speaker attribution mapping (Req 5, 7, 8). The Cornell hallucination fix.
  - id: preprocess
    command: >
      exec --json --shell 'node scripts/echo-audio-preprocessor.js'
    stdin: '{
      "segments": $normalize-transcript.json.segments,
      "confidence_threshold": 0.85,
      "attendees": $load-meeting.json.attendees
    }'

  # Step 9: Load commitment language thresholds (custom per-team adjustments)
  - id: load-thresholds
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "echo-config/commitment-thresholds"}'

  # Step 10: Deterministic commitment classification (Req 18). Keyword matching
  # catches the ~60% clear cases; ambiguous statements flow to the LLM step below.
  - id: classify-commitments
    command: >
      exec --json --shell 'node scripts/echo-commitment-classifier.js'
    stdin: '{
      "statements": $preprocess.json.processed_segments,
      "custom_thresholds": $load-thresholds.json
    }'

  # Step 11: LLM classification for ambiguous commitments — conservative,
  # defaults to tentative when unclear.
  - id: classify-ambiguous
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Classify each of these ambiguous statements. Is it a definitive commitment (someone personally committed to a specific task with a timeline), a tentative proposal (worth discussing but not committed), or not an action item? Be conservative — when in doubt, classify as tentative.",
        "thinking": "off",
        "input": {
          "classified": $classify-commitments.json.classified
        },
        "schema": {
          "type": "object",
          "properties": {
            "classifications": {"type": "array", "items": {
              "type": "object",
              "properties": {
                "segment_id": {"type": "string"},
                "classification": {"type": "string"}
              }
            }}
          },
          "required": ["classifications"]
        }
      }'
    condition: $classify-commitments.json.needs_llm_count > 0

  # Step 12: Extract action items with speaker-verified attribution (Req 16, 17, 19)
  - id: extract-actions
    command: >
      exec --json --shell 'node scripts/echo-action-extractor.js'
    stdin: '{
      "classified": $classify-commitments.json.classified,
      "attendees": $load-meeting.json.attendees,
      "meeting_context": {
        "meeting_id": "{{meeting_id}}",
        "title": "$load-meeting.json.title",
        "date": "$load-meeting.json.date",
        "recording_url": "$load-meeting.json.recording_url"
      }
    }'

  # Step 13: Format for review per meeting type (Req 10-15, 21). Formatter
  # falls back to built-in TEMPLATE_DEFAULTS when custom_template is null.
  - id: format-review
    command: >
      exec --json --shell 'node scripts/echo-synthesis-formatter.js'
    stdin: '{
      "meeting_type": "$load-meeting.json.meeting_type",
      "action_items": $extract-actions.json.action_items,
      "tentative_items": $extract-actions.json.tentative_items,
      "flagged_segments": $preprocess.json.processed_segments,
      "meeting_meta": {
        "title": "$load-meeting.json.title",
        "date": "$load-meeting.json.date",
        "attendees": $load-meeting.json.attendees,
        "duration_minutes": "$load-meeting.json.duration_minutes",
        "reviewer": "$load-meeting.json.reviewer",
        "secretary": "$load-meeting.json.secretary"
      },
      "custom_template": null
    }'

  # Step 14: Generate summary narrative — ADAPTIVE LLM (Req 10-14)
  - id: generate-summary
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a meeting summary from this speaker-attributed transcript. Follow the template instructions exactly — capture what the template says to capture, omit what it says to omit. CRITICAL: attribute ideas to the person who ORIGINATED them, not the senior person who agreed. Include timestamp links for every decision and action item. Adapt your tone to the meeting type.",
        "thinking": "low",
        "input": {
          "transcript_segments": $preprocess.json.processed_segments,
          "template_instructions": $format-review.json.llm_instructions,
          "meeting_type": "$format-review.json.meeting_type",
          "prior_context": $prior-context.json,
          "action_items": $extract-actions.json.action_items,
          "tentative_items": $extract-actions.json.tentative_items
        },
        "schema": {
          "type": "object",
          "properties": {
            "summary": {"type": "string"},
            "decisions": {"type": "array", "items": {"type": "object", "properties": {"decision": {"type": "string"}, "made_by": {"type": "string"}, "timestamp": {"type": "string"}}}},
            "key_discussion_points": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["summary"]
        }
      }'

  # Step 15: Present to reviewer — TIER 2 GATE (Req 20, 21, 22)
  - id: present-review
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#echo-meetings",
        "text": "📋 MEETING SUMMARY — REVIEW REQUIRED\n$load-meeting.json.title ($format-review.json.meeting_type)\n\n$generate-summary.json.summary\n\n📌 ACTION ITEMS ($extract-actions.json.counts.definitive definitive, $extract-actions.json.counts.tentative tentative)\n$extract-actions.json.action_items\n\n⚠️ FLAGS ($format-review.json.flags.count)\n$format-review.json.flags.all\n\n🔍 FOR FOLLOW-UP / TO BE CONFIRMED\n$extract-actions.json.tentative_items\n\n[Approve] [Edit] [Reject]\nReviewer: $format-review.json.reviewer"
      }'

  - id: await-review
    command: >
      openclaw.invoke --tool lobster --action await-approval --args-json '{
        "prompt": "Waiting for reviewer to approve meeting summary",
        "timeout_hours": 48,
        "required_reviewer": "$format-review.json.reviewer"
      }'

  # Step 16: Distribute approved summary (Req 25)
  - id: distribute-email
    command: >
      openclaw.invoke --tool gog --action gmail-send --args-json '{
        "to": "$load-meeting.json.attendees",
        "subject": "Meeting Summary: $load-meeting.json.title",
        "body": "$generate-summary.json.summary"
      }'
    condition: $await-review.json.approved && $format-review.json.distribution_rule != "configured_recipients_only"

  - id: distribute-slack
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#echo-meetings",
        "text": "✅ APPROVED: $load-meeting.json.title\n\n$generate-summary.json.summary"
      }'
    condition: $await-review.json.approved

  # Step 17: Load the user's connected PM tool (click-to-connect, single-platform).
  # If none is connected, action-item routing no-ops — the summary is still
  # distributed and archived, the reviewer just has to track items manually.
  - id: load-connected-pm
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "echo-config/connected-pm-tool"}'
    condition: $await-review.json.approved

  - id: no-pm-notice
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#echo-meetings",
        "text": "Action items for this meeting were not routed to a project tracker. To auto-route approved action items, connect Asana, Linear, or Jira in your settings."
      }'
    condition: $await-review.json.approved && $load-connected-pm.json.platform != "asana" && $load-connected-pm.json.platform != "linear" && $load-connected-pm.json.platform != "jira"

  # Step 18: Push approved action items to the connected PM tool (Req 26).
  # Parallel conditional branches — each a direct API call to the native provider.
  - id: push-actions-asana
    command: >
      exec --json --shell 'curl -s -X POST -H "Authorization: Bearer $ASANA_ACCESS_TOKEN" -H "Content-Type: application/json" -d @- "https://app.asana.com/api/1.0/tasks"'
    stdin: '{
      "data": {
        "workspace": "$load-connected-pm.json.workspace_id",
        "projects": ["$load-connected-pm.json.default_project_id"],
        "name": "Echo action items from $load-meeting.json.title",
        "notes": $extract-actions.json.action_items,
        "assignee": "$load-connected-pm.json.default_assignee"
      }
    }'
    condition: $await-review.json.approved && $load-connected-pm.json.platform == "asana"

  - id: push-actions-linear
    command: >
      exec --json --shell 'curl -s -X POST -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" -d @- "https://api.linear.app/graphql"'
    stdin: '{
      "query": "mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier } } }",
      "variables": {
        "input": {
          "teamId": "$load-connected-pm.json.team_id",
          "title": "Echo action items from $load-meeting.json.title",
          "description": $extract-actions.json.action_items
        }
      }
    }'
    condition: $await-review.json.approved && $load-connected-pm.json.platform == "linear"

  - id: push-actions-jira
    command: >
      exec --json --shell 'curl -s -X POST -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -H "Content-Type: application/json" -d @- "$load-connected-pm.json.base_url/rest/api/3/issue"'
    stdin: '{
      "fields": {
        "project": {"key": "$load-connected-pm.json.project_key"},
        "summary": "Echo action items from $load-meeting.json.title",
        "description": $extract-actions.json.action_items,
        "issuetype": {"name": "Task"}
      }
    }'
    condition: $await-review.json.approved && $load-connected-pm.json.platform == "jira"

  # Step 19: Load the user's connected CRM (click-to-connect, single-platform).
  - id: load-connected-crm
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "echo-config/connected-crm"}'
    condition: $await-review.json.approved && $format-review.json.crm_update

  # Step 20: Update CRM for customer meetings (Req 27). Parallel branches —
  # HubSpot and Attio have click-to-connect ClawHub skills; Salesforce and
  # Pipedrive are direct API calls documented in TOOLS.md.
  - id: update-crm-hubspot
    command: >
      openclaw.invoke --tool hubspot --action upsert-engagement --args-json '{
        "type": "MEETING",
        "contact_email": "$load-meeting.json.client_contact",
        "timestamp": "$load-meeting.json.date",
        "body": "$generate-summary.json.summary",
        "next_steps": $extract-actions.json.action_items
      }'
    condition: $await-review.json.approved && $format-review.json.crm_update && $load-connected-crm.json.platform == "hubspot"

  - id: update-crm-attio
    command: >
      openclaw.invoke --tool attio-enhanced --action create-note --args-json '{
        "contact_email": "$load-meeting.json.client_contact",
        "meeting_date": "$load-meeting.json.date",
        "summary": "$generate-summary.json.summary",
        "action_items": $extract-actions.json.action_items
      }'
    condition: $await-review.json.approved && $format-review.json.crm_update && $load-connected-crm.json.platform == "attio"

  - id: update-crm-salesforce
    command: >
      exec --json --shell 'curl -s -X POST -H "Authorization: Bearer $SALESFORCE_ACCESS_TOKEN" -H "Content-Type: application/json" -d @- "$load-connected-crm.json.instance_url/services/data/v60.0/sobjects/Task"'
    stdin: '{
      "WhoId": "$load-meeting.json.client_contact_id",
      "Subject": "Meeting: $load-meeting.json.title",
      "ActivityDate": "$load-meeting.json.date",
      "Description": "$generate-summary.json.summary"
    }'
    condition: $await-review.json.approved && $format-review.json.crm_update && $load-connected-crm.json.platform == "salesforce"

  - id: update-crm-pipedrive
    command: >
      exec --json --shell 'curl -s -X POST -H "Content-Type: application/json" -d @- "https://api.pipedrive.com/v1/notes?api_token=$PIPEDRIVE_API_TOKEN"'
    stdin: '{
      "person_id": "$load-meeting.json.client_contact_id",
      "content": "Meeting: $load-meeting.json.title\n\n$generate-summary.json.summary"
    }'
    condition: $await-review.json.approved && $format-review.json.crm_update && $load-connected-crm.json.platform == "pipedrive"

  # Step 21: Draft customer follow-up email if applicable (Req 24)
  - id: draft-followup
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Draft a follow-up email to the client based on this meeting summary. Include: thanks for their time, summary of what was discussed, what was committed by each party, and clear next steps with timelines. Write in the reps voice — professional but warm. The rep will review before sending.",
        "thinking": "off",
        "input": {
          "summary": "$generate-summary.json.summary",
          "client": "$load-meeting.json.client_contact",
          "action_items": $extract-actions.json.action_items
        }
      }'
    condition: $await-review.json.approved && $format-review.json.crm_update

  - id: present-followup
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#echo-meetings",
        "text": "📧 FOLLOW-UP EMAIL DRAFT — Review before sending\n\n$draft-followup.json.email\n\n[Send] [Edit] [Skip]"
      }'
    condition: $draft-followup.json

  # Step 22: Store in institutional memory (Req 31)
  - id: store-archive
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "echo-archive/{{meeting_id}}",
        "data": {
          "meeting_id": "{{meeting_id}}",
          "title": "$load-meeting.json.title",
          "date": "$load-meeting.json.date",
          "attendees": $load-meeting.json.attendees,
          "meeting_type": "$format-review.json.meeting_type",
          "summary": "$generate-summary.json.summary",
          "decisions": $generate-summary.json.decisions,
          "action_items": $extract-actions.json.action_items,
          "tentative_items": $extract-actions.json.tentative_items,
          "transcript_ref": "echo-transcripts/{{meeting_id}}",
          "reviewed_by": "$await-review.json.reviewer",
          "reviewed_at": "$await-review.json.timestamp",
          "confidential": $format-review.json.confidential
        }
      }'

  - id: store-drive
    command: >
      openclaw.invoke --tool gog --action drive-write --args-json '{
        "path": "Echo Meeting Archive/$load-meeting.json.date - $load-meeting.json.title",
        "content": "$generate-summary.json.summary"
      }'

  # Step 23: Log review action (Req 23)
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "echo-audit/{{date}}/{{meeting_id}}",
        "data": {
          "action": "meeting_processed",
          "meeting": "$load-meeting.json.title",
          "type": "$format-review.json.meeting_type",
          "transcript_source": "$normalize-transcript.json.source",
          "reviewed_by": "$await-review.json.reviewer",
          "changes_made": "$await-review.json.edits",
          "flags_count": $format-review.json.flags.count,
          "action_items": $extract-actions.json.counts,
          "pm_tool": "$load-connected-pm.json.platform",
          "crm": "$load-connected-crm.json.platform",
          "distributed": $await-review.json.approved,
          "timestamp": "{{timestamp}}"
        }
      }'
