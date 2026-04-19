#!/usr/bin/env node
/**
 * bolt-deploy-monitor.js
 * R4: Parse incoming deploy webhook payload, classify failure type,
 * determine if production-impacting, return structured output for Slack alert + Linear issue.
 * Usage: node bolt-deploy-monitor.js '<webhook_json>'
 */

const FAILURE_TYPES = {
  build: {
    patterns: [/build/i, /compile/i, /webpack/i, /esbuild/i, /tsc/i],
    plain_label: "Build failed — your code changes couldn't be packaged for deployment",
    production_impact: false,
    linear_priority: "P1",
  },
  config: {
    patterns: [/config/i, /env/i, /environment/i, /variable/i, /missing/i],
    plain_label: "Configuration error — a required setting is missing or wrong",
    production_impact: false,
    linear_priority: "P1",
  },
  infra: {
    patterns: [/timeout/i, /network/i, /connection/i, /gateway/i, /502/i, /503/i, /crashed/i],
    plain_label: "Infrastructure issue — your server had trouble responding",
    production_impact: true,
    linear_priority: "P0",
  },
  oom: {
    patterns: [/memory/i, /oom/i, /heap/i],
    plain_label: "Out of memory — your app ran out of resources",
    production_impact: true,
    linear_priority: "P0",
  },
  unknown: {
    patterns: [],
    plain_label: "Deployment failed for an unknown reason — logs attached",
    production_impact: false,
    linear_priority: "P1",
  },
};

function classifyFailure(payload) {
  const text = JSON.stringify(payload).toLowerCase();

  for (const [type, config] of Object.entries(FAILURE_TYPES)) {
    if (type === "unknown") continue;
    for (const pattern of config.patterns) {
      if (pattern.test(text)) {
        return { failure_type: type, ...config };
      }
    }
  }

  return { failure_type: "unknown", ...FAILURE_TYPES.unknown };
}

function parsePayload(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return { raw_text: raw };
  }
}

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error(JSON.stringify({ error: "No webhook payload provided" }));
  process.exit(1);
}

const payload = parsePayload(args.join(" "));
const classification = classifyFailure(payload);

const output = {
  ...classification,
  service: payload.project || payload.app || payload.service || "unknown service",
  environment: payload.env || payload.environment || "production",
  timestamp: new Date().toISOString(),
  raw_payload: payload,
  alert_message: classification.production_impact
    ? `🚨 Production issue detected on ${payload.project || "your app"}. ${classification.plain_label}. Investigating now.`
    : `⚠️ Deploy failed on ${payload.project || "your app"}. ${classification.plain_label}. Production is unaffected.`,
};

console.log(JSON.stringify(output, null, 2));
process.exit(0);
