pipeline: bug-digest
description: Weekly cron. Fetch open Linear issues, rank by severity, send plain-English digest to Slack.
trigger: cron
cron: "0 9 * * 1"

steps:

  - id: fetch-open-issues
    type: linear
    action: list_issues
    team_id: "{{user.linear_team_id}}"
    project_id: "{{user.linear_project_id}}"
    filter:
      state: "open"
      label: "bug"
    output: open_issues

  - id: build-digest
    type: llm-task
    prompt: |
      Here are the open bugs in Linear (JSON):
      {{open_issues}}
      
      Write a plain-English weekly bug digest for a non-technical founder.
      Format:
      - Start with a one-line summary: "You have X open bugs. Here's what needs attention."
      - Group by priority: P0 (critical), P1 (feature broken), P2 (minor)
      - For each bug, one sentence in plain English — what's broken, not the technical cause
      - End with a recommended action: what to focus on this week
      
      No jargon. Keep it under 20 lines total.
    output: digest_text

  - id: send-digest
    type: message
    channel: "{{user.digest_channel}}"
    content: |
      📊 *Weekly Bug Digest*
      
      {{digest_text}}
