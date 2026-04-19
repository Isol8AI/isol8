pipeline: cicd-monitor
description: Triggered by deploy failure webhook. Classify failure, alert Slack in plain English, create Linear issue.
trigger: webhook
webhook_path: /hooks/deploy

steps:

  - id: classify-failure
    type: script
    run: node scripts/bolt-deploy-monitor.js '{{webhook_payload}}'
    output: deploy_result

  - id: slack-alert
    type: message
    channel: "{{user.alert_channel}}"
    content: "{{deploy_result.alert_message}}"

  - id: explain-failure
    type: llm-task
    prompt: |
      A deployment just failed. Here are the details:
      - Service: {{deploy_result.service}}
      - Failure type: {{deploy_result.failure_type}}
      - What it means: {{deploy_result.plain_label}}
      - Production impact: {{deploy_result.production_impact}}
      
      Write a 2-3 sentence explanation for a non-technical founder. 
      No jargon. Say whether users are affected. Say what they should do (if anything).
    output: plain_explanation

  - id: create-linear-issue
    type: linear
    action: create_issue
    title: "Deploy failure — {{deploy_result.service}} ({{deploy_result.failure_type}})"
    description: |
      **What happened:** {{deploy_result.plain_label}}
      **Service:** {{deploy_result.service}}
      **Environment:** {{deploy_result.environment}}
      **Time:** {{deploy_result.timestamp}}
      **Production impact:** {{deploy_result.production_impact}}
      
      ---
      {{plain_explanation}}
    priority: "{{deploy_result.linear_priority}}"
    output: linear_issue

  - id: followup-slack
    type: message
    channel: "{{user.alert_channel}}"
    content: |
      {{plain_explanation}}
      
      I've logged this as {{deploy_result.linear_priority}} in Linear: {{linear_issue.url}}
