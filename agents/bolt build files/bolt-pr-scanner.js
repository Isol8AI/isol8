#!/usr/bin/env node
/**
 * bolt-pr-scanner.js
 * R6: Scan PR changed files for sensitive paths, classify PR type,
 * prepare structured output for LLM plain-English summary.
 * Usage: node bolt-pr-scanner.js '<github_pr_json>'
 */

const SENSITIVE_PATH_PATTERNS = [
  { pattern: /src\/auth\//i, label: "authentication logic" },
  { pattern: /src\/payments?\//i, label: "payment processing" },
  { pattern: /src\/billing\//i, label: "billing logic" },
  { pattern: /\.env/i, label: "environment variables" },
  { pattern: /migrations?\//i, label: "database migrations" },
  { pattern: /prisma\//i, label: "database schema" },
  { pattern: /middleware/i, label: "request middleware" },
  { pattern: /secrets?\//i, label: "secrets store" },
];

const PR_TYPE_PATTERNS = [
  { pattern: /^feat|^feature/i, type: "new feature", plain: "adds new functionality" },
  { pattern: /^fix|^bug/i, type: "bug fix", plain: "fixes a bug" },
  { pattern: /^refactor/i, type: "refactor", plain: "reorganizes existing code without changing behavior" },
  { pattern: /^chore|^deps|^dependency/i, type: "maintenance", plain: "updates dependencies or tooling" },
  { pattern: /^docs/i, type: "docs", plain: "updates documentation only" },
  { pattern: /^test/i, type: "tests", plain: "adds or updates tests" },
  { pattern: /^style|^ui/i, type: "UI change", plain: "changes the visual appearance" },
];

function detectPRType(title) {
  for (const { pattern, type, plain } of PR_TYPE_PATTERNS) {
    if (pattern.test(title)) return { type, plain };
  }
  return { type: "general change", plain: "makes changes to the codebase" };
}

function scanFiles(files) {
  const sensitive = [];
  for (const file of files) {
    for (const { pattern, label } of SENSITIVE_PATH_PATTERNS) {
      if (pattern.test(file)) {
        sensitive.push({ file, label });
        break;
      }
    }
  }
  return sensitive;
}

function parsePR(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error(JSON.stringify({ error: "No PR payload provided" }));
  process.exit(1);
}

const pr = parsePR(args.join(" "));
const files = pr.changed_files || pr.files || [];
const title = pr.title || "";
const prType = detectPRType(title);
const sensitiveFiles = scanFiles(files);

const output = {
  pr_number: pr.number || pr.pr_number || null,
  title,
  pr_type: prType,
  changed_file_count: files.length,
  sensitive_files: sensitiveFiles,
  requires_founder_attention: sensitiveFiles.length > 0,
  flag_message:
    sensitiveFiles.length > 0
      ? `🚩 This update touches ${sensitiveFiles.map((f) => f.label).join(" and ")}. You may want to review it before it merges.`
      : null,
  llm_context: {
    title,
    pr_type_plain: prType.plain,
    file_count: files.length,
    files_sample: files.slice(0, 5),
    sensitive_files: sensitiveFiles,
    author: pr.user?.login || pr.author || "unknown",
  },
};

console.log(JSON.stringify(output, null, 2));
process.exit(0);
