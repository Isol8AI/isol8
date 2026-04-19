#!/usr/bin/env node
/**
 * bolt-sensitive-gate.js
 * R9: Hard deny on any action touching auth, payments, env vars, migrations.
 * Run before every file write or system state change.
 * Usage: node bolt-sensitive-gate.js <filepath>
 */

const path = require("path");

const SENSITIVE_PATTERNS = [
  /src\/auth\//i,
  /src\/payments\//i,
  /src\/billing\//i,
  /\.env/i,
  /migrations\//i,
  /prisma\/migrations\//i,
  /secrets\//i,
  /\.pem$/i,
  /\.key$/i,
  /credentials/i,
];

const SENSITIVE_LABELS = {
  "/src/auth/": "authentication logic",
  "/src/payments/": "payment processing",
  "/src/billing/": "billing logic",
  ".env": "environment variables / secrets",
  "migrations/": "database migrations",
  "prisma/migrations/": "database migrations",
  "secrets/": "secrets store",
  ".pem": "private key file",
  ".key": "private key file",
  "credentials": "credentials file",
};

function getSensitiveLabel(filepath) {
  for (const [pattern, label] of Object.entries(SENSITIVE_LABELS)) {
    if (filepath.toLowerCase().includes(pattern.toLowerCase())) {
      return label;
    }
  }
  return "sensitive system file";
}

function checkPath(filepath) {
  const normalized = filepath.replace(/\\/g, "/");
  for (const pattern of SENSITIVE_PATTERNS) {
    if (pattern.test(normalized)) {
      return {
        blocked: true,
        filepath: normalized,
        reason: getSensitiveLabel(normalized),
      };
    }
  }
  return { blocked: false, filepath: normalized };
}

const args = process.argv.slice(2);

if (args.length === 0) {
  console.error(JSON.stringify({ error: "No filepath provided. Usage: node bolt-sensitive-gate.js <filepath>" }));
  process.exit(1);
}

const results = args.map(checkPath);
const anyBlocked = results.some((r) => r.blocked);

const output = {
  blocked: anyBlocked,
  results,
  message: anyBlocked
    ? `🚫 Bolt cannot touch this — it involves ${results.find((r) => r.blocked).reason}. This requires a developer.`
    : "✅ Path cleared. Safe to proceed.",
};

console.log(JSON.stringify(output, null, 2));
process.exit(anyBlocked ? 1 : 0);
