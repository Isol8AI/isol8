#!/usr/bin/env node
/**
 * tally-tax-tracker.js
 * Requirements 45, 46, 47: Continuous tax prep, quarterly deadlines, CPA flags.
 *
 * Deterministic tagging and threshold checks. Zero LLM.
 */

const DEDUCTION_MAP = {
  'software & tools': { deduction: 'business_expense', rate: 1.0 },
  'software': { deduction: 'business_expense', rate: 1.0 },
  'office supplies': { deduction: 'business_expense', rate: 1.0 },
  'professional services': { deduction: 'business_expense', rate: 1.0 },
  'legal': { deduction: 'business_expense', rate: 1.0 },
  'accounting': { deduction: 'business_expense', rate: 1.0 },
  'consulting': { deduction: 'business_expense', rate: 1.0 },
  'advertising': { deduction: 'business_expense', rate: 1.0 },
  'marketing': { deduction: 'business_expense', rate: 1.0 },
  'travel': { deduction: 'business_expense', rate: 1.0 },
  'meals & entertainment': { deduction: 'meals', rate: 0.5 },
  'meals': { deduction: 'meals', rate: 0.5 },
  'client entertainment': { deduction: 'meals', rate: 0.5 },
  'insurance': { deduction: 'business_expense', rate: 1.0 },
  'rent': { deduction: 'business_expense', rate: 1.0 },
  'utilities': { deduction: 'business_expense', rate: 1.0 },
  'equipment': { deduction: 'equipment', rate: 1.0 },
  'home office': { deduction: 'home_office', rate: null },
  'vehicle': { deduction: 'vehicle', rate: null },
  'education & training': { deduction: 'business_expense', rate: 1.0 },
  'subscriptions': { deduction: 'business_expense', rate: 1.0 }
};

const QUARTERLY_DEADLINES = [
  { quarter: 'Q1', due: '04-15', period: 'January 1 - March 31' },
  { quarter: 'Q2', due: '06-15', period: 'April 1 - May 31' },
  { quarter: 'Q3', due: '09-15', period: 'June 1 - August 31' },
  { quarter: 'Q4', due: '01-15', period: 'September 1 - December 31' }
];

function tagTransaction(transaction) {
  const category = (transaction.category || '').toLowerCase();
  const amount = transaction.amount || 0;
  const vendor = transaction.vendor || '';

  const mapping = Object.entries(DEDUCTION_MAP).find(([key]) =>
    category.includes(key) || key.includes(category)
  );

  const tag = {
    deduction_type: mapping ? mapping[1].deduction : 'uncategorized',
    deduction_rate: mapping ? mapping[1].rate : null,
    deductible_amount: mapping && mapping[1].rate ? Math.round(amount * mapping[1].rate * 100) / 100 : null
  };

  return tag;
}

function flagForCpa(transaction, ytdByVendor) {
  const flags = [];
  const amount = transaction.amount || 0;
  const category = (transaction.category || '').toLowerCase();
  const vendor = (transaction.vendor || '').toLowerCase();

  // Meals over $75
  if ((category.includes('meal') || category.includes('entertainment')) && amount > 75) {
    flags.push({
      type: 'meal_documentation',
      message: 'Meal/entertainment over $75 — verify business purpose documentation for deductibility.',
      rule: 'IRS requires documentation of business purpose, attendees, and business relationship for meals over $75.'
    });
  }

  // Mixed use indicator
  if (category.includes('home office') || category.includes('vehicle')) {
    flags.push({
      type: 'mixed_use',
      message: `${category} expense — confirm allocation split (business vs personal) with CPA.`,
      rule: 'Mixed-use expenses require documented business use percentage.'
    });
  }

  // Equipment over $2,500 (Section 179 threshold)
  if (category.includes('equipment') && amount > 2500) {
    flags.push({
      type: 'section_179',
      message: `Equipment purchase $${amount} may qualify for Section 179 immediate expensing — CPA should advise on depreciation vs deduction.`,
      rule: 'Equipment over $2,500 should be evaluated for Section 179 expensing or depreciation schedule.'
    });
  }

  // Contractor payments — 1099 threshold
  if (ytdByVendor && ytdByVendor[vendor] && ytdByVendor[vendor] > 600) {
    const isContractor = category.includes('contractor') || category.includes('freelance') ||
                         category.includes('consulting') || category.includes('professional services');
    if (isContractor) {
      flags.push({
        type: '1099_filing',
        message: `YTD payments to "${transaction.vendor}" total $${ytdByVendor[vendor].toLocaleString()}. 1099-NEC filing may be required (threshold: $600).`,
        rule: 'IRS requires 1099-NEC for non-employee compensation exceeding $600/year.'
      });
    }
  }

  // Vehicle expenses
  if (category.includes('vehicle') || category.includes('gas') || category.includes('fuel') ||
      category.includes('parking') || category.includes('tolls')) {
    flags.push({
      type: 'vehicle_allocation',
      message: 'Vehicle-related expense — confirm business vs personal mileage split with CPA.',
      rule: 'Vehicle deductions require either actual expense method or standard mileage rate, with documented business use percentage.'
    });
  }

  return flags;
}

function checkQuarterlyDeadline(currentDate, taxRate, ytdIncome, ytdDeductions) {
  const now = new Date(currentDate);
  const year = now.getFullYear();
  const alerts = [];

  for (const deadline of QUARTERLY_DEADLINES) {
    const dueYear = deadline.quarter === 'Q4' ? year + 1 : year;
    const dueDate = new Date(`${dueYear}-${deadline.due}`);
    const daysUntil = Math.floor((dueDate - now) / (1000 * 60 * 60 * 24));

    if (daysUntil > 0 && daysUntil <= 30) {
      const estimatedLiability = Math.round((ytdIncome - ytdDeductions) * (taxRate || 0.25) / 4);
      alerts.push({
        quarter: deadline.quarter,
        due_date: `${dueYear}-${deadline.due}`,
        days_until: daysUntil,
        period: deadline.period,
        estimated_liability: estimatedLiability,
        ytd_income: ytdIncome,
        ytd_deductions: ytdDeductions,
        effective_rate: taxRate || 0.25,
        message: `${deadline.quarter} estimated tax payment due ${dueYear}-${deadline.due} (${daysUntil} days). Estimated liability: $${estimatedLiability.toLocaleString()} based on YTD income $${ytdIncome.toLocaleString()} less deductions $${ytdDeductions.toLocaleString()}.`
      });
    }
  }

  return alerts;
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const mode = input.mode || 'tag';

  if (mode === 'tag') {
    const transaction = input.transaction || input;
    const tag = tagTransaction(transaction);
    const cpaFlags = flagForCpa(transaction, input.ytd_by_vendor || {});
    process.stdout.write(JSON.stringify({ ...transaction, tax_tag: tag, cpa_flags: cpaFlags }));
  } else if (mode === 'deadline') {
    const alerts = checkQuarterlyDeadline(
      input.current_date || new Date().toISOString(),
      input.tax_rate,
      input.ytd_income || 0,
      input.ytd_deductions || 0
    );
    process.stdout.write(JSON.stringify({ alerts, has_upcoming: alerts.length > 0 }));
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

module.exports = { tagTransaction, flagForCpa, checkQuarterlyDeadline };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
