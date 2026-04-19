#!/usr/bin/env node
/**
 * bolt-bug-classifier.js
 * R5: Classify bug severity deterministically before creating Linear issue.
 * Severity: P0 (production down), P1 (feature broken), P2 (cosmetic/minor)
 * Usage: node bolt-bug-classifier.js "<bug report text>"
 */

const P0_SIGNALS = [
  /production.*down/i,
  /site.*down/i,
  /app.*down/i,
  /nothing.*works/i,
  /completely broken/i,
  /can't.*log in/i,
  /cannot.*log in/i,
  /no one can/i,
  /payment.*fail/i,
  /charge.*fail/i,
  /data.*loss/i,
  /500.*error/i,
  /crash/i,
  /outage/i,
];

const P1_SIGNALS = [
  /feature.*broken/i,
  /doesn't work/i,
  /not working/i,
  /broken/i,
  /error.*when/i,
  /fails.*when/i,
  /can't.*\b(submit|save|load|access|use)\b/i,
  /button.*broken/i,
  /form.*broken/i,
  /page.*broken/i,
  /404/i,
  /403/i,
];

const P2_SIGNALS = [
  /cosmetic/i,
  /typo/i,
  /spelling/i,
  /alignment/i,
  /color/i,
  /font/i,
  /style/i,
  /slight/i,
  /minor/i,
  /small issue/i,
  /looks a bit/i,
];

function classify(text) {
  for (const pattern of P0_SIGNALS) {
    if (pattern.test(text)) {
      return {
        severity: "P0",
        label: "Critical — production impact",
        plain_label: "This is breaking the app for users right now",
        linear_priority: 1,
        auto_page: true,
      };
    }
  }

  for (const pattern of P1_SIGNALS) {
    if (pattern.test(text)) {
      return {
        severity: "P1",
        label: "High — feature broken",
        plain_label: "A feature isn't working but the rest of the app is fine",
        linear_priority: 2,
        auto_page: false,
      };
    }
  }

  for (const pattern of P2_SIGNALS) {
    if (pattern.test(text)) {
      return {
        severity: "P2",
        label: "Low — cosmetic or minor",
        plain_label: "Small visual or non-blocking issue",
        linear_priority: 3,
        auto_page: false,
      };
    }
  }

  // Default to P1 if unclear — better to overclassify than miss something real
  return {
    severity: "P1",
    label: "High — needs review",
    plain_label: "Couldn't automatically classify — treating as a broken feature until confirmed otherwise",
    linear_priority: 2,
    auto_page: false,
    defaulted: true,
  };
}

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error(JSON.stringify({ error: "No bug report text provided" }));
  process.exit(1);
}

const reportText = args.join(" ");
const result = classify(reportText);

console.log(
  JSON.stringify(
    {
      ...result,
      input_preview: reportText.substring(0, 120),
    },
    null,
    2
  )
);
process.exit(0);
