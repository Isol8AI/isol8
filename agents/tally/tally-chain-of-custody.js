#!/usr/bin/env node
/**
 * tally-chain-of-custody.js
 * Requirement 51: Complete chain of custody for any transaction.
 *
 * Deterministic assembly from audit log. Zero LLM.
 */

function buildChain(auditEntries, transactionId) {
  const relevant = auditEntries
    .filter(e => e.transaction_id === transactionId || e.entry_id === transactionId)
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

  if (relevant.length === 0) {
    return { found: false, transaction_id: transactionId, message: 'No audit entries found for this transaction.' };
  }

  const chain = relevant.map((entry, idx) => ({
    step: idx + 1,
    action: entry.action,
    timestamp: entry.timestamp,
    source: entry.source || null,
    detail: entry.detail || null,
    approved_by: entry.approved_by || null,
    confidence: entry.confidence || null,
    flags: entry.flags || []
  }));

  return {
    found: true,
    transaction_id: transactionId,
    chain,
    total_steps: chain.length,
    first_seen: chain[0].timestamp,
    last_action: chain[chain.length - 1].timestamp,
    posted: chain.some(s => s.action === 'posted_to_ledger'),
    approved_by: chain.find(s => s.approved_by)?.approved_by || 'pending'
  };
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const auditEntries = input.audit_entries || [];
  const transactionId = input.transaction_id;

  if (!transactionId) {
    process.stderr.write('transaction_id is required');
    process.exit(1);
  }

  const result = buildChain(auditEntries, transactionId);
  result.timestamp = new Date().toISOString();

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

module.exports = { buildChain };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
