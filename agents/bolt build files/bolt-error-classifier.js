#!/usr/bin/env node
/**
 * bolt-error-classifier.js
 * R3: Classify error type, file, and line deterministically before LLM plain-English explanation.
 * Usage: node bolt-error-classifier.js "<error text>"
 * Output: JSON with type, file, line, severity, plain_label
 */

const ERROR_PATTERNS = [
  {
    type: "null_pointer",
    plain_label: "Something in the code tried to use a value that doesn't exist yet",
    severity: "high",
    patterns: [
      /cannot read propert(?:y|ies) of (null|undefined)/i,
      /null pointer/i,
      /typeerror.*undefined/i,
      /is not a function/i,
    ],
  },
  {
    type: "http_502",
    plain_label: "Your server crashed or couldn't be reached — users may be seeing errors",
    severity: "critical",
    patterns: [/502 bad gateway/i, /upstream connect error/i, /no healthy upstream/i],
  },
  {
    type: "http_503",
    plain_label: "Your service is temporarily unavailable — likely overloaded or restarting",
    severity: "critical",
    patterns: [/503 service unavailable/i, /service unavailable/i],
  },
  {
    type: "build_failure",
    plain_label: "Your latest code update failed to build — nothing changed in production",
    severity: "high",
    patterns: [/build failed/i, /compilation error/i, /failed to compile/i, /exit code 1/i],
  },
  {
    type: "dependency_conflict",
    plain_label: "Two packages you're using disagree on a shared dependency version",
    severity: "medium",
    patterns: [/peer dep/i, /conflicting peer/i, /version conflict/i, /incompatible/i],
  },
  {
    type: "env_missing",
    plain_label: "A required configuration value (like an API key) isn't set",
    severity: "high",
    patterns: [/env.*not set/i, /missing.*env/i, /undefined.*process\.env/i, /environment variable/i],
  },
  {
    type: "auth_error",
    plain_label: "Authentication failed — a token or credential may be expired or missing",
    severity: "high",
    patterns: [/401 unauthorized/i, /403 forbidden/i, /invalid token/i, /authentication failed/i],
  },
  {
    type: "db_connection",
    plain_label: "The app can't connect to the database",
    severity: "critical",
    patterns: [/connection refused/i, /econnrefused/i, /database.*connect/i, /pg.*error/i],
  },
  {
    type: "timeout",
    plain_label: "Something took too long and gave up — could be a slow API or database query",
    severity: "medium",
    patterns: [/timeout/i, /timed out/i, /etimedout/i, /deadline exceeded/i],
  },
  {
    type: "memory",
    plain_label: "Your app ran out of memory",
    severity: "critical",
    patterns: [/out of memory/i, /heap.*limit/i, /javascript heap/i, /oom/i],
  },
];

function extractFileAndLine(text) {
  const fileLineMatch = text.match(/at .+\((.+):(\d+):(\d+)\)/);
  if (fileLineMatch) {
    return { file: fileLineMatch[1], line: parseInt(fileLineMatch[2]) };
  }
  const simpleMatch = text.match(/([^\s]+\.[jt]sx?):(\d+)/);
  if (simpleMatch) {
    return { file: simpleMatch[1], line: parseInt(simpleMatch[2]) };
  }
  return { file: null, line: null };
}

function classify(errorText) {
  const { file, line } = extractFileAndLine(errorText);

  for (const error of ERROR_PATTERNS) {
    for (const pattern of error.patterns) {
      if (pattern.test(errorText)) {
        return {
          type: error.type,
          plain_label: error.plain_label,
          severity: error.severity,
          file,
          line,
          matched: true,
        };
      }
    }
  }

  return {
    type: "unknown",
    plain_label: "An unexpected error occurred — details need developer review",
    severity: "medium",
    file,
    line,
    matched: false,
  };
}

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error(JSON.stringify({ error: "No error text provided" }));
  process.exit(1);
}

const errorText = args.join(" ");
const result = classify(errorText);

console.log(JSON.stringify(result, null, 2));
process.exit(0);
