pipeline: repo-hygiene-sweep
description: Weekly cron. Fetch repo state from GitHub, scan for hygiene issues, send plain-English Slack digest.
trigger: cron
cron: "0 9 * * 1"

steps:

  - id: fetch-repo-data
    type: github
    action: get_repo_summary
    repo: "{{user.github_org}}/{{user.github_repo}}"
    include: ["branches", "pull_requests", "issues"]
    output: repo_data

  - id: run-hygiene-scan
    type: script
    run: node scripts/bolt-hygiene-scanner.js '{{repo_data}}'
    output: hygiene_report

  - id: send-digest
    type: message
    channel: "{{user.digest_channel}}"
    content: "{{hygiene_report.digest_message}}"

  - id: skip-if-clean
    type: conditional
    condition: "{{hygiene_report.total_flags}} === 0"
    if_true:
      exit: true
