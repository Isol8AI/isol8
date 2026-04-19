#!/usr/bin/env node
/**
 * bolt-health-check.js
 * R8: Hit configured production service URLs, check response time and status.
 * Returns structured health report for Slack alert if anomaly detected.
 * Usage: node bolt-health-check.js '<services_json>'
 * services_json: [{ name, url, timeout_ms, expected_status }]
 */

const https = require("https");
const http = require("http");

const DEFAULT_TIMEOUT_MS = 3000;
const DEFAULT_EXPECTED_STATUS = 200;

function checkService(service) {
  return new Promise((resolve) => {
    const { name, url, timeout_ms = DEFAULT_TIMEOUT_MS, expected_status = DEFAULT_EXPECTED_STATUS } = service;
    const start = Date.now();
    const lib = url.startsWith("https") ? https : http;

    const req = lib.get(url, (res) => {
      const responseTime = Date.now() - start;
      const healthy = res.statusCode === expected_status;
      resolve({
        name,
        url,
        status: res.statusCode,
        response_time_ms: responseTime,
        healthy,
        issue: healthy
          ? null
          : `Responded with status ${res.statusCode} (expected ${expected_status})`,
      });
    });

    req.setTimeout(timeout_ms, () => {
      req.destroy();
      resolve({
        name,
        url,
        status: null,
        response_time_ms: timeout_ms,
        healthy: false,
        issue: `No response within ${timeout_ms}ms — service may be down or very slow`,
      });
    });

    req.on("error", (err) => {
      resolve({
        name,
        url,
        status: null,
        response_time_ms: Date.now() - start,
        healthy: false,
        issue: `Connection failed — ${err.message}`,
      });
    });
  });
}

function buildAlertMessage(results) {
  const unhealthy = results.filter((r) => !r.healthy);
  if (unhealthy.length === 0) return null;

  const lines = ["🚨 *Production Health Alert*\n"];
  for (const service of unhealthy) {
    lines.push(`*${service.name}* is having trouble:`);
    lines.push(`  ${service.issue}`);
    lines.push(`  URL: ${service.url}\n`);
  }
  lines.push("Bolt has logged this. If this persists, contact your developer.");
  return lines.join("\n");
}

async function run() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    console.error(JSON.stringify({ error: "No services config provided" }));
    process.exit(1);
  }

  let services;
  try {
    services = JSON.parse(args.join(" "));
    if (!Array.isArray(services)) services = [services];
  } catch {
    console.error(JSON.stringify({ error: "Invalid JSON for services config" }));
    process.exit(1);
  }

  const results = await Promise.all(services.map(checkService));
  const allHealthy = results.every((r) => r.healthy);
  const alertMessage = buildAlertMessage(results);

  const output = {
    checked_at: new Date().toISOString(),
    all_healthy: allHealthy,
    results,
    alert_message: alertMessage,
    summary: allHealthy
      ? `✅ All ${results.length} service(s) healthy`
      : `🚨 ${results.filter((r) => !r.healthy).length} of ${results.length} service(s) having issues`,
  };

  console.log(JSON.stringify(output, null, 2));
  process.exit(allHealthy ? 0 : 1);
}

run();
