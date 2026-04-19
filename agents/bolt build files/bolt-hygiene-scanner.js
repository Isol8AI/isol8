#!/usr/bin/env node
/**
 * bolt-hygiene-scanner.js
 * R7: Analyze GitHub repo data for stale branches, idle PRs, and old issues.
 * Returns structured hygiene report for Slack digest.
 * Usage: node bolt-hygiene-scanner.js '<repo_data_json>'
 * repo_data_json: { branches: [...], pull_requests: [...], issues: [...] }
 */

const STALE_BRANCH_DAYS = parseInt(process.env.STALE_BRANCH_DAYS || "14");
const IDLE_PR_DAYS = parseInt(process.env.IDLE_PR_DAYS || "7");
const OLD_ISSUE_DAYS = parseInt(process.env.OLD_ISSUE_DAYS || "30");

function daysSince(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  return Math.floor((now - date) / (1000 * 60 * 60 * 24));
}

function scanBranches(branches) {
  const stale = [];
  for (const branch of branches) {
    if (branch.name === "main" || branch.name === "master" || branch.name === "develop") continue;
    const days = daysSince(branch.last_commit_date || branch.updated_at);
    if (days >= STALE_BRANCH_DAYS) {
      stale.push({ name: branch.name, days_inactive: days });
    }
  }
  return stale.sort((a, b) => b.days_inactive - a.days_inactive);
}

function scanPRs(prs) {
  const idle = [];
  for (const pr of prs) {
    if (pr.state !== "open") continue;
    const days = daysSince(pr.updated_at);
    if (days >= IDLE_PR_DAYS) {
      idle.push({
        number: pr.number,
        title: pr.title,
        author: pr.user?.login || pr.author || "unknown",
        days_idle: days,
        url: pr.html_url || pr.url,
      });
    }
  }
  return idle.sort((a, b) => b.days_idle - a.days_idle);
}

function scanIssues(issues) {
  const old = [];
  for (const issue of issues) {
    if (issue.state !== "open") continue;
    if (issue.pull_request) continue; // skip PR-linked issues
    const days = daysSince(issue.created_at);
    if (days >= OLD_ISSUE_DAYS) {
      old.push({
        number: issue.number,
        title: issue.title,
        days_open: days,
        url: issue.html_url || issue.url,
      });
    }
  }
  return old.sort((a, b) => b.days_open - a.days_open);
}

function buildDigestMessage(staleBranches, idlePRs, oldIssues, repo) {
  const lines = [`📋 *Weekly Repo Checkup — ${repo}*\n`];

  if (staleBranches.length === 0 && idlePRs.length === 0 && oldIssues.length === 0) {
    lines.push("Everything looks clean. No action needed.");
    return lines.join("\n");
  }

  if (staleBranches.length > 0) {
    lines.push(`*Branches with no activity in ${STALE_BRANCH_DAYS}+ days (${staleBranches.length}):*`);
    staleBranches.slice(0, 5).forEach((b) => {
      lines.push(`  • \`${b.name}\` — ${b.days_inactive} days quiet`);
    });
    if (staleBranches.length > 5) lines.push(`  …and ${staleBranches.length - 5} more`);
    lines.push("");
  }

  if (idlePRs.length > 0) {
    lines.push(`*Open updates waiting on review (${idlePRs.length}):*`);
    idlePRs.slice(0, 5).forEach((p) => {
      lines.push(`  • #${p.number} "${p.title}" — ${p.days_idle} days with no activity`);
    });
    if (idlePRs.length > 5) lines.push(`  …and ${idlePRs.length - 5} more`);
    lines.push("");
  }

  if (oldIssues.length > 0) {
    lines.push(`*Open issues older than ${OLD_ISSUE_DAYS} days (${oldIssues.length}):*`);
    oldIssues.slice(0, 5).forEach((i) => {
      lines.push(`  • #${i.number} "${i.title}" — open for ${i.days_open} days`);
    });
    if (oldIssues.length > 5) lines.push(`  …and ${oldIssues.length - 5} more`);
  }

  return lines.join("\n");
}

function parseData(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return { branches: [], pull_requests: [], issues: [] };
  }
}

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error(JSON.stringify({ error: "No repo data provided" }));
  process.exit(1);
}

const data = parseData(args.join(" "));
const repo = data.repo || "your repo";
const staleBranches = scanBranches(data.branches || []);
const idlePRs = scanPRs(data.pull_requests || []);
const oldIssues = scanIssues(data.issues || []);

const output = {
  repo,
  scanned_at: new Date().toISOString(),
  stale_branches: staleBranches,
  idle_prs: idlePRs,
  old_issues: oldIssues,
  total_flags: staleBranches.length + idlePRs.length + oldIssues.length,
  digest_message: buildDigestMessage(staleBranches, idlePRs, oldIssues, repo),
};

console.log(JSON.stringify(output, null, 2));
process.exit(0);
