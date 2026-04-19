pipeline: bug-triage
description: Ingest bug report from Slack or message, classify severity, generate repro steps, create Linear issue.
trigger: message
trigger_keywords: ["bug", "broken", "not working", "error", "issue", "crash", "fix"]

steps:

  - id: classify-severity
    type: script
    run: node scripts/bolt-bug-classifier.js "{{input}}"
    output: classification

  - id: generate-repro-steps
    type: llm-task
    prompt: |
      A bug was reported: "{{input}}"
      Severity assessed as: {{classification.plain_label}}
      
      Generate likely reproduction steps in plain English (numbered list, 3-5 steps).
      If there isn't enough info, write what you'd need to reproduce it.
      Keep it simple — no technical jargon.
    output: repro_steps

  - id: create-linear-issue
    type: linear
    action: create_issue
    title: "[{{classification.severity}}] {{input | truncate: 80}}"
    description: |
      **Reported via Slack**
      
      **What was reported:**
      {{input}}
      
      **Severity:** {{classification.label}}
      **What this means:** {{classification.plain_label}}
      
      **Likely reproduction steps:**
      {{repro_steps}}
    priority: "{{classification.linear_priority}}"
    label: "bug"
    output: linear_issue

  - id: confirm-to-founder
    type: message
    channel: "{{user.alert_channel}}"
    content: |
      Got it — logged as a {{classification.severity}} issue.
      
      *{{classification.plain_label}}*
      
      Linear issue created: {{linear_issue.url}}
      {{#if classification.auto_page}}
      🚨 This looks like a production issue. If users are reporting this too, let me know and I'll escalate.
      {{/if}}
