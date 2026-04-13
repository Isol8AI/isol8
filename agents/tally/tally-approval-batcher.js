#!/usr/bin/env node
/**
 * tally-approval-batcher.js
 * Requirement 14: Batch routine approvals, surface unusual individually.
 *
 * Deterministic sorting. Zero LLM.
 */

const MIN_CONFIRMATIONS_FOR_BATCH = 3;

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const pendingEntries = input.entries || [];
  const vendorMap = input.vendor_map || {};
  const approvalPrefs = input.approval_preferences || {};
  const autoConfirmVendors = (approvalPrefs.auto_confirm_vendors || []).map(v => v.toLowerCase());
  const reviewThreshold = approvalPrefs.review_threshold || 500;

  const batchable = [];
  const individual = [];

  for (const entry of pendingEntries) {
    const vendor = (entry.vendor || '').toLowerCase();
    const vendorHistory = vendorMap[vendor];
    const amount = entry.amount || 0;

    const isKnownVendor = vendorHistory && vendorHistory.confirmation_count >= MIN_CONFIRMATIONS_FOR_BATCH;
    const isAutoConfirm = autoConfirmVendors.includes(vendor);
    const isWithinAmountRange = vendorHistory
      ? amount >= vendorHistory.amount_min * 0.85 && amount <= vendorHistory.amount_max * 1.15
      : false;
    const isBelowThreshold = amount <= reviewThreshold;
    const hasNoFlags = !entry.anomaly_flags || entry.anomaly_flags.length === 0;

    if ((isKnownVendor || isAutoConfirm) && isWithinAmountRange && isBelowThreshold && hasNoFlags) {
      batchable.push({
        ...entry,
        batch_reason: isAutoConfirm ? 'auto_confirm_vendor' : 'recurring_known_vendor',
        confidence: 'high'
      });
    } else {
      const reasons = [];
      if (!isKnownVendor && !isAutoConfirm) reasons.push('new or infrequent vendor');
      if (!isWithinAmountRange) reasons.push(`amount $${amount} outside historical range`);
      if (!isBelowThreshold) reasons.push(`amount $${amount} exceeds review threshold $${reviewThreshold}`);
      if (!hasNoFlags) reasons.push(`anomaly flags: ${(entry.anomaly_flags || []).map(f => f.type).join(', ')}`);

      individual.push({
        ...entry,
        review_reasons: reasons,
        confidence: 'needs_review'
      });
    }
  }

  const result = {
    batch: {
      entries: batchable,
      count: batchable.length,
      total_amount: batchable.reduce((sum, e) => sum + (e.amount || 0), 0)
    },
    individual: {
      entries: individual,
      count: individual.length,
      total_amount: individual.reduce((sum, e) => sum + (e.amount || 0), 0)
    },
    total: pendingEntries.length,
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
}

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => {
      try { resolve(JSON.parse(data)); }
      catch { resolve(null); }
    });
    if (process.stdin.isTTY) resolve(null);
  });
}

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
