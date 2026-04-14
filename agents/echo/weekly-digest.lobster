name: weekly-digest
# Requirements 33, 34: Monday action item status digest with deadline alerts.
# Runs Monday 8 AM on cron.
# LLM calls: 1 (digest narrative — adaptive)

steps:
  # Step 1: Load all archived action items across every tracked meeting.
  - id: load-actions
    command: >
      openclaw.invoke --tool fast-io --action list --args-json '{
        "prefix": "echo-archive/",
        "fields": "action_items"
      }'

  # Step 2: Load the user's connected PM tool (click-to-connect, single-platform).
  # If nothing is connected, status checking no-ops and the digest runs off
  # meeting-date + deadline info alone.
  - id: load-connected-pm
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "echo-config/connected-pm-tool"}'

  # Step 3: Check PM tool for task completion status. Parallel conditional
  # branches — each a direct API call to the native PM tool.
  - id: check-pm-status-asana
    command: >
      exec --json --shell 'curl -s -H "Authorization: Bearer $ASANA_ACCESS_TOKEN" "https://app.asana.com/api/1.0/tasks?workspace=$load-connected-pm.json.workspace_id&completed_since=now-7d&opt_fields=gid,completed,completed_at,external"'
    condition: $load-connected-pm.json.platform == "asana"

  - id: check-pm-status-linear
    command: >
      exec --json --shell 'curl -s -X POST -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" -d @- "https://api.linear.app/graphql"'
    stdin: '{
      "query": "query($teamId: String!) { issues(filter: {team: {id: {eq: $teamId}}, updatedAt: {gte: \"-P7D\"}}) { nodes { id identifier completedAt state { name } } } }",
      "variables": {"teamId": "$load-connected-pm.json.team_id"}
    }'
    condition: $load-connected-pm.json.platform == "linear"

  - id: check-pm-status-jira
    command: >
      exec --json --shell 'curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" "$load-connected-pm.json.base_url/rest/api/3/search?jql=project=$load-connected-pm.json.project_key+AND+updated>-7d&fields=resolutiondate,status"'
    condition: $load-connected-pm.json.platform == "jira"

  # Step 4: Normalize whichever PM tool responded into a unified status map
  # keyed by the action item's external_id. Deterministic, zero-LLM.
  - id: normalize-pm-status
    command: >
      exec --json --shell 'node -e "
        const raw = JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\", \"utf8\"));
        const statusMap = {};
        const asanaTasks = (raw.asana && raw.asana.data) || [];
        for (const t of asanaTasks) {
          statusMap[t.gid] = { completed: !!t.completed, completed_date: t.completed_at || null };
        }
        const linearIssues = (raw.linear && raw.linear.data && raw.linear.data.issues && raw.linear.data.issues.nodes) || [];
        for (const i of linearIssues) {
          statusMap[i.id] = { completed: !!i.completedAt, completed_date: i.completedAt || null };
        }
        const jiraIssues = (raw.jira && raw.jira.issues) || [];
        for (const i of jiraIssues) {
          const done = i.fields && (i.fields.status && (i.fields.status.name === \"Done\" || i.fields.status.name === \"Closed\"));
          statusMap[i.id] = { completed: !!done, completed_date: (i.fields && i.fields.resolutiondate) || null };
        }
        process.stdout.write(JSON.stringify({ status_map: statusMap, source: Object.keys(raw).find(k => raw[k]) || null }));
      "'
    stdin: '{
      "asana": $check-pm-status-asana.json,
      "linear": $check-pm-status-linear.json,
      "jira": $check-pm-status-jira.json
    }'

  # Step 5: Run deadline tracker with action items + PM status map
  - id: track-deadlines
    command: >
      exec --json --shell 'node scripts/echo-deadline-tracker.js'
    stdin: '{
      "action_items": $load-actions.json.action_items,
      "pm_tool_status": $normalize-pm-status.json.status_map,
      "alert_days_before": 2
    }'

  # Step 6: Capability-evolver — weekly learning
  - id: learn
    command: >
      openclaw.invoke --tool capability-evolver --action analyze --args-json '{
        "data": {
          "reviewer_edits": "from fast-io echo-audit — what reviewers changed",
          "commitment_overrides": "from fast-io echo-state/commitment-overrides — tentative items promoted or definitive items removed",
          "template_edits": "from fast-io echo-state/template-edits"
        },
        "focus": "Which action item extractions do reviewers consistently remove (threshold too aggressive)? Which tentative items consistently become definitive (threshold too conservative for this team)? Which summary sections get heavily edited (template needs adjustment)?"
      }'

  # Step 7: Generate digest — ADAPTIVE LLM
  - id: generate-digest
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Generate a Monday action item digest. Lead with overdue items, then approaching deadlines, then items with no status update. Include: the task, who owns it, the deadline, and which meeting it came from. End with the follow-through rate. Keep it concise — this is an accountability check, not a report.",
        "thinking": "off",
        "input": {
          "tracked": $track-deadlines.json.digest_items,
          "overdue": $track-deadlines.json.overdue,
          "approaching": $track-deadlines.json.approaching,
          "follow_through_rate": $track-deadlines.json.follow_through_rate,
          "learning_notes": $learn.json
        }
      }'

  # Step 8: Deliver to Slack
  - id: deliver
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#echo-meetings",
        "text": "📊 MONDAY ACTION ITEM DIGEST\n\n$generate-digest.json.digest\n\nFollow-through rate: $track-deadlines.json.follow_through_rate%"
      }'

  # Step 9: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "echo-audit/{{date}}/weekly-digest",
        "data": {
          "action": "weekly_digest",
          "overdue": $track-deadlines.json.overdue,
          "approaching": $track-deadlines.json.approaching,
          "follow_through_rate": $track-deadlines.json.follow_through_rate,
          "pm_tool": "$load-connected-pm.json.platform",
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
