pipeline: pr-summary
description: Triggered by GitHub PR webhook. Scan for sensitive paths, summarize in plain English, alert founder if flagged.
trigger: webhook
webhook_path: /hooks/github
webhook_events: ["pull_request.opened", "pull_request.synchronize"]

steps:

  - id: scan-pr
    type: script
    run: node scripts/bolt-pr-scanner.js '{{webhook_payload}}'
    output: scan_result

  - id: summarize-diff
    type: llm-task
    prompt: |
      A code update was just submitted for review. Here's the context:
      - Title: {{scan_result.llm_context.title}}
      - Type: This update {{scan_result.llm_context.pr_type_plain}}
      - Files changed: {{scan_result.llm_context.file_count}}
      - Author: {{scan_result.llm_context.author}}
      - Sample files: {{scan_result.llm_context.files_sample}}
      {{#if scan_result.sensitive_files}}
      - ⚠️ Sensitive areas touched: {{scan_result.sensitive_files | map: 'label' | join: ', '}}
      {{/if}}
      
      Write a 2-3 sentence plain-English summary of what this update does.
      No technical terms. Assume the reader is not a developer.
      If sensitive files are touched, note that this update touches important parts of the system.
    output: plain_summary

  - id: notify-slack
    type: message
    channel: "{{user.alert_channel}}"
    condition: "{{scan_result.requires_founder_attention}} === true"
    content: |
      {{scan_result.flag_message}}
      
      **Update #{{scan_result.pr_number}}: {{scan_result.title}}**
      {{plain_summary}}

  - id: log-pr
    type: message
    channel: "{{user.digest_channel}}"
    condition: "{{scan_result.requires_founder_attention}} === false"
    content: |
      📝 New code update submitted: *{{scan_result.title}}*
      {{plain_summary}}
