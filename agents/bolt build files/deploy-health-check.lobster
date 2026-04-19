pipeline: deploy-health-check
description: Daily cron. Hit all configured production service URLs, check health, alert Slack if anything is down.
trigger: cron
cron: "0 8 * * *"

steps:

  - id: run-health-check
    type: script
    run: |
      node scripts/bolt-health-check.js '[
        {
          "name": "{{user.company}} App",
          "url": "{{user.production_url}}{{user.health_check_path}}",
          "timeout_ms": {{user.health_check_timeout_ms}},
          "expected_status": 200
        }
      ]'
    output: health_report

  - id: alert-if-unhealthy
    type: message
    channel: "{{user.alert_channel}}"
    condition: "{{health_report.all_healthy}} === false"
    content: "{{health_report.alert_message}}"

  - id: create-linear-on-critical
    type: linear
    action: create_issue
    condition: "{{health_report.all_healthy}} === false"
    title: "Production health check failed — {{health_report.results | filter: 'healthy:false' | map: 'name' | join: ', '}}"
    description: |
      **Daily health check detected an issue.**
      
      {{health_report.alert_message}}
      
      **Checked at:** {{health_report.checked_at}}
      **Full results:** {{health_report.results}}
    priority: "P0"
    label: "incident"
    output: linear_issue

  - id: log-healthy
    type: message
    channel: "{{user.digest_channel}}"
    condition: "{{health_report.all_healthy}} === true"
    content: "{{health_report.summary}}"
