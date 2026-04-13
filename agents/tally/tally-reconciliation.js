#!/usr/bin/env node
/**
 * tally-reconciliation.js
 * Requirements 19, 20: Bank reconciliation matching and duplicate detection.
 *
 * Deterministic matching. Zero LLM.
 */

const DATE_TOLERANCE_DAYS = 3;
const DUPLICATE_WINDOW_DAYS = 5;

function matchTransactions(ledgerEntries, bankEntries) {
  const confident = [];
  const probable = [];
  const unmatchedLedger = [...ledgerEntries];
  const unmatchedBank = [...bankEntries];

  // Pass 1: Exact matches (amount + date within tolerance + vendor)
  for (let i = unmatchedLedger.length - 1; i >= 0; i--) {
    const ledger = unmatchedLedger[i];
    const bankIdx = unmatchedBank.findIndex(bank =>
      Math.abs(bank.amount - ledger.amount) < 0.01 &&
      dateDiff(bank.date, ledger.date) <= DATE_TOLERANCE_DAYS &&
      vendorMatch(bank.description, ledger.vendor)
    );
    if (bankIdx !== -1) {
      confident.push({
        ledger_entry: ledger,
        bank_entry: unmatchedBank[bankIdx],
        match_type: 'exact',
        confidence: 'high'
      });
      unmatchedLedger.splice(i, 1);
      unmatchedBank.splice(bankIdx, 1);
    }
  }

  // Pass 2: Amount match only (no vendor match)
  for (let i = unmatchedLedger.length - 1; i >= 0; i--) {
    const ledger = unmatchedLedger[i];
    const bankIdx = unmatchedBank.findIndex(bank =>
      Math.abs(bank.amount - ledger.amount) < 0.01 &&
      dateDiff(bank.date, ledger.date) <= DATE_TOLERANCE_DAYS
    );
    if (bankIdx !== -1) {
      probable.push({
        ledger_entry: ledger,
        bank_entry: unmatchedBank[bankIdx],
        match_type: 'amount_only',
        confidence: 'medium',
        discrepancy: 'Vendor name does not match — verify this is the same transaction.'
      });
      unmatchedLedger.splice(i, 1);
      unmatchedBank.splice(bankIdx, 1);
    }
  }

  return { confident, probable, unmatched_ledger: unmatchedLedger, unmatched_bank: unmatchedBank };
}

function detectDuplicates(entries) {
  const duplicates = [];
  const checked = new Set();

  for (let i = 0; i < entries.length; i++) {
    if (checked.has(i)) continue;
    for (let j = i + 1; j < entries.length; j++) {
      if (checked.has(j)) continue;
      const a = entries[i];
      const b = entries[j];

      // Same amount + same vendor within window
      if (Math.abs(a.amount - b.amount) < 0.01 &&
          vendorMatch(a.vendor, b.vendor) &&
          dateDiff(a.date, b.date) <= DUPLICATE_WINDOW_DAYS) {
        duplicates.push({
          entry_a: a,
          entry_b: b,
          reason: a.invoice_number && b.invoice_number && a.invoice_number === b.invoice_number
            ? 'Same invoice number billed twice'
            : a.source !== b.source
              ? `Same charge from different sources (${a.source} and ${b.source})`
              : 'Same amount and vendor within 5-day window',
          recommendation: 'Review and remove one entry before approving.'
        });
        checked.add(j);
      }
    }
  }

  return duplicates;
}

function dateDiff(date1, date2) {
  return Math.abs(new Date(date1) - new Date(date2)) / (1000 * 60 * 60 * 24);
}

function vendorMatch(a, b) {
  if (!a || !b) return false;
  const normalize = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');
  return normalize(a).includes(normalize(b)) || normalize(b).includes(normalize(a));
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const ledger = input.ledger_entries || [];
  const bank = input.bank_entries || [];
  const allEntries = input.all_entries || [...ledger, ...bank];

  const reconciliation = matchTransactions(ledger, bank);
  const duplicates = detectDuplicates(allEntries);

  const result = {
    reconciliation,
    duplicates,
    summary: {
      total_ledger: ledger.length,
      total_bank: bank.length,
      confident_matches: reconciliation.confident.length,
      probable_matches: reconciliation.probable.length,
      unmatched_ledger: reconciliation.unmatched_ledger.length,
      unmatched_bank: reconciliation.unmatched_bank.length,
      duplicates_found: duplicates.length
    },
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

module.exports = { matchTransactions, detectDuplicates };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
