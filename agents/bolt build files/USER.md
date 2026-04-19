# User Profile

<!-- Replace all brackets before going live -->

name: [Founder Name]
role: [Founder / CEO / CTO]
company: [Company Name]
timezone: America/New_York
preferred_name: [How they want to be addressed]

## Repo

github_org: [org-name]
github_repo: [repo-name]
primary_branch: main

## Issue Tracker

issue_tracker: linear
linear_team_id: [LINEAR_TEAM_ID]
linear_project_id: [LINEAR_PROJECT_ID]

## Deployment

deploy_platform: vercel
production_url: [https://yourapp.com]
health_check_path: /api/health
health_check_timeout_ms: 3000
deploy_failure_threshold: 2

## Sensitive Paths (never touch autonomously)

sensitive_paths:
  - "src/auth/**"
  - "src/payments/**"
  - "src/billing/**"
  - ".env*"
  - "migrations/**"
  - "prisma/migrations/**"

## Slack Alerts

alert_channel: "#bolt-alerts"
digest_channel: "#bolt-alerts"
mention_on_critical: true

## Hygiene Thresholds

stale_branch_days: 14
idle_pr_days: 7
old_issue_days: 30

## Notes

<!-- Anything Bolt should know about the codebase -->
<!-- e.g., "We use Next.js 14 with Supabase" -->
<!-- e.g., "Our payments are handled by Stripe — all files in src/payments are off limits" -->
<!-- e.g., "Main branch deploys automatically to production" -->
