#!/usr/bin/env node
/**
 * tally-categorization-engine.js
 * Requirements 9, 10, 17: Confidence validation, vendor learning, accuracy tracking.
 *
 * Deterministic field validation and vendor mapping. Zero LLM.
 */

const REQUIRED_FIELDS = ['amount', 'vendor', 'category'];

function checkConfidence(extraction) {
  const missing = REQUIRED_FIELDS.filter(f => !extraction[f] && extraction[f] !== 0);
  const uncertain = [];

  if (extraction.confidence_score !== undefined && extraction.confidence_score < 0.7) {
    uncertain.push({ field: 'category', reason: `Low confidence: ${extraction.confidence_score}` });
  }
  if (extraction.vendor === 'unknown' || extraction.vendor === '') {
    uncertain.push({ field: 'vendor', reason: 'Vendor could not be identified' });
  }
  if (extraction.category_alternatives && extraction.category_alternatives.length > 1) {
    uncertain.push({ field: 'category', reason: `Multiple possible categories: ${extraction.category_alternatives.join(', ')}` });
  }

  return {
    pass: missing.length === 0 && uncertain.length === 0,
    missing,
    uncertain,
    route: missing.length > 0 ? 'ambiguity_flow' :
           uncertain.length > 0 ? 'individual_review' :
           'standard_approval'
  };
}

function applyVendorMapping(extraction, vendorMap) {
  const vendor = (extraction.vendor || '').toLowerCase().trim();
  const mapping = vendorMap[vendor];

  if (mapping) {
    return {
      ...extraction,
      category: mapping.category,
      subcategory: mapping.subcategory || null,
      mapping_source: 'vendor_history',
      mapping_confidence: mapping.confirmation_count >= 3 ? 'high' : 'medium',
      confirmation_count: mapping.confirmation_count
    };
  }

  return {
    ...extraction,
    mapping_source: 'llm_extraction',
    mapping_confidence: 'needs_review'
  };
}

function trackAccuracy(corrections, periodDays) {
  if (!corrections || corrections.length === 0) {
    return { accuracy: null, sample_size: 0, period_days: periodDays };
  }

  const cutoff = Date.now() - (periodDays * 24 * 60 * 60 * 1000);
  const recent = corrections.filter(c => new Date(c.timestamp).getTime() > cutoff);

  const byVendor = {};
  for (const c of recent) {
    const vendor = (c.vendor || 'unknown').toLowerCase();
    if (!byVendor[vendor]) byVendor[vendor] = { correct: 0, corrected: 0 };
    if (c.was_correct) {
      byVendor[vendor].correct++;
    } else {
      byVendor[vendor].corrected++;
    }
  }

  // Only measure recurring vendors (3+ transactions)
  const recurringVendors = Object.entries(byVendor).filter(([_, v]) => (v.correct + v.corrected) >= 3);
  if (recurringVendors.length === 0) {
    return { accuracy: null, sample_size: recent.length, period_days: periodDays, note: 'Insufficient recurring vendor data' };
  }

  const totalRecurring = recurringVendors.reduce((sum, [_, v]) => sum + v.correct + v.corrected, 0);
  const correctRecurring = recurringVendors.reduce((sum, [_, v]) => sum + v.correct, 0);
  const accuracy = Math.round((correctRecurring / totalRecurring) * 1000) / 10;

  const worstVendors = recurringVendors
    .map(([vendor, v]) => ({
      vendor,
      accuracy: Math.round((v.correct / (v.correct + v.corrected)) * 100),
      total: v.correct + v.corrected,
      corrected: v.corrected
    }))
    .filter(v => v.accuracy < 90)
    .sort((a, b) => a.accuracy - b.accuracy)
    .slice(0, 5);

  return {
    accuracy,
    target: 90,
    meets_target: accuracy >= 90,
    sample_size: totalRecurring,
    recurring_vendors: recurringVendors.length,
    period_days: periodDays,
    worst_vendors: worstVendors,
    alert: accuracy < 90 && periodDays >= 60
      ? `Categorization accuracy ${accuracy}% is below 90% target after ${periodDays} days. Review worst-performing vendors.`
      : null
  };
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const mode = input.mode || 'check';

  if (mode === 'check') {
    const extraction = input.extraction || {};
    const vendorMap = input.vendor_map || {};
    const mapped = applyVendorMapping(extraction, vendorMap);
    const confidence = checkConfidence(mapped);
    process.stdout.write(JSON.stringify({ ...mapped, confidence_check: confidence }));
  } else if (mode === 'accuracy') {
    const corrections = input.corrections || [];
    const periodDays = input.period_days || 60;
    const result = trackAccuracy(corrections, periodDays);
    process.stdout.write(JSON.stringify(result));
  }
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

module.exports = { checkConfidence, applyVendorMapping, trackAccuracy };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
