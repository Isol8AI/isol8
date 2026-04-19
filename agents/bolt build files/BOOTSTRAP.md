# Bolt — Bootstrap

Run this setup on first activation. Delete this file when done.

## Step 1: Confirm Integrations
Check that the following env vars are set in openclaw.json:
- GITHUB_TOKEN — needs read access to your repo
- LINEAR_API_KEY — needs issue create/update permissions
- VERCEL_TOKEN or RAILWAY_TOKEN — needs read access to deployments
- OPENCLAW_HOOK_TOKEN — for webhook authentication

## Step 2: Configure USER.md
Fill in all bracket placeholders:
- Your repo name and org
- Your Slack channel for alerts (#bolt-alerts recommended)
- Your production service URLs for health checks
- Your sensitive path patterns (auth, payments, etc.)
- Your Linear team ID and project ID

## Step 3: Register Webhooks
In your GitHub repo settings, add a webhook pointing to:
  POST https://[your-openclaw-host]/hooks/github
  Events: Pull requests

In your Vercel/Railway dashboard, add a deploy webhook pointing to:
  POST https://[your-openclaw-host]/hooks/deploy

## Step 4: Verify Cron Jobs
Run: openclaw cron list
You should see:
- bolt-hygiene-sweep (Mondays 9am)
- bolt-deploy-health (Daily 8am)
- bolt-bug-digest (Mondays 9am)

## Step 5: Test
Send Bolt a Slack message: "What's the status of my repo?"
It should respond with a plain-English summary of your latest PRs and any open issues.

## Delete This File
