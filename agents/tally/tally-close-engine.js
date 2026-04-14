#!/usr/bin/env node
/**
 * tally-close-engine.js
 * Requirements 40, 41, 42, 43, 44: Month-end close support.
 *
 * Deterministic calculations and assembly. Zero LLM.
 */

function generateChecklist(data) {
  const items = [];

  // Accounts needing reconciliation
  const unreconciledAccounts = data.accounts?.filter(a => !a.reconciled) || [];
  items.push({
    category: 'Reconciliation',
    item: `${unreconciledAccounts.length} account(s) pending reconciliation`,
    status: unreconciledAccounts.length === 0 ? 'ready' : 'needs_attention',
    details: unreconciledAccounts.map(a => a.name),
    total_discrepancy: unreconciledAccounts.reduce((sum, a) => sum + Math.abs(a.discrepancy || 0), 0)
  });

  // Pending categorizations
  const pendingCat = data.pending_categorizations || 0;
  items.push({
    category: 'Categorization',
    item: `${pendingCat} transaction(s) pending categorization`,
    status: pendingCat === 0 ? 'ready' : 'needs_attention'
  });

  // Overdue receivables
  const overdueAR = data.receivables?.filter(r => r.days_overdue > 0) || [];
  items.push({
    category: 'Accounts Receivable',
    item: `${overdueAR.length} receivable(s) past due`,
    status: overdueAR.length === 0 ? 'ready' : 'needs_attention',
    details: overdueAR.map(r => ({ client: r.client, amount: r.amount, days_overdue: r.days_overdue })),
    total_overdue: overdueAR.reduce((sum, r) => sum + r.amount, 0)
  });

  // Accruals
  const accruals = data.accounting_policies?.accruals || [];
  items.push({
    category: 'Accruals',
    item: `${accruals.length} recurring accrual(s) to post`,
    status: 'ready',
    details: accruals.map(a => ({ description: a.description, amount: a.amount }))
  });

  // Prepaids
  const prepaids = data.accounting_policies?.prepaids || [];
  items.push({
    category: 'Prepaid Amortization',
    item: `${prepaids.length} prepaid(s) to amortize`,
    status: 'ready',
    details: prepaids.map(p => ({ description: p.description, monthly_amount: p.total / p.months }))
  });

  // Depreciation
  const depreciation = data.accounting_policies?.depreciation || [];
  items.push({
    category: 'Depreciation',
    item: `${depreciation.length} asset(s) to depreciate`,
    status: 'ready',
    details: depreciation.map(d => ({ asset: d.asset, monthly_amount: Math.round(d.original_cost / d.useful_life_months * 100) / 100 }))
  });

  // Unresolved anomaly flags
  const unresolvedFlags = data.unresolved_anomalies || 0;
  items.push({
    category: 'Anomaly Flags',
    item: `${unresolvedFlags} unresolved anomaly flag(s)`,
    status: unresolvedFlags === 0 ? 'ready' : 'needs_attention'
  });

  return items;
}

function draftJournalEntries(policies, period) {
  const entries = [];

  // Accruals
  for (const accrual of (policies.accruals || [])) {
    entries.push({
      type: 'accrual',
      description: accrual.description,
      date: period.end_date,
      debit: { account: accrual.account, amount: accrual.amount },
      credit: { account: `Accrued ${accrual.account}`, amount: accrual.amount },
      source: 'tally-config/accounting-policies',
      status: 'draft_pending_approval'
    });
  }

  // Prepaid amortization
  for (const prepaid of (policies.prepaids || [])) {
    const monthlyAmount = Math.round((prepaid.total / prepaid.months) * 100) / 100;
    entries.push({
      type: 'prepaid_amortization',
      description: `Amortize ${prepaid.description}`,
      date: period.end_date,
      debit: { account: prepaid.expense_account || prepaid.description, amount: monthlyAmount },
      credit: { account: 'Prepaid Expenses', amount: monthlyAmount },
      source: 'tally-config/accounting-policies',
      status: 'draft_pending_approval'
    });
  }

  // Depreciation
  for (const asset of (policies.depreciation || [])) {
    let monthlyAmount;
    if (asset.method === 'straight_line') {
      monthlyAmount = Math.round((asset.original_cost / asset.useful_life_months) * 100) / 100;
    } else {
      monthlyAmount = Math.round((asset.original_cost / asset.useful_life_months) * 100) / 100;
    }
    entries.push({
      type: 'depreciation',
      description: `Depreciate ${asset.asset}`,
      date: period.end_date,
      debit: { account: 'Depreciation Expense', amount: monthlyAmount },
      credit: { account: `Accumulated Depreciation - ${asset.asset}`, amount: monthlyAmount },
      calculation: `$${asset.original_cost} / ${asset.useful_life_months} months = $${monthlyAmount}/month (${asset.method || 'straight_line'})`,
      source: 'tally-config/accounting-policies',
      status: 'draft_pending_approval'
    });
  }

  return entries;
}

function validateStatements(current, prior, projections) {
  const flags = [];

  // Revenue deviation
  if (prior.revenue && current.revenue) {
    const revDeviation = Math.abs(current.revenue - prior.revenue) / prior.revenue;
    if (revDeviation > 0.20) {
      flags.push({
        type: 'revenue_deviation',
        current: current.revenue,
        prior_avg: prior.revenue,
        deviation_pct: Math.round(revDeviation * 100),
        message: `Revenue $${current.revenue.toLocaleString()} is ${Math.round(revDeviation * 100)}% ${current.revenue > prior.revenue ? 'above' : 'below'} the trailing 3-month average of $${prior.revenue.toLocaleString()}.`
      });
    }
  }

  // Expense category spikes
  if (current.expenses_by_category && prior.expenses_by_category) {
    for (const [cat, amount] of Object.entries(current.expenses_by_category)) {
      const priorAmount = prior.expenses_by_category[cat] || 0;
      if (priorAmount > 0) {
        const deviation = (amount - priorAmount) / priorAmount;
        if (deviation > 0.25) {
          flags.push({
            type: 'expense_spike',
            category: cat,
            current: amount,
            prior_avg: priorAmount,
            deviation_pct: Math.round(deviation * 100),
            message: `${cat} expenses $${amount.toLocaleString()} spiked ${Math.round(deviation * 100)}% vs average $${priorAmount.toLocaleString()}.`
          });
        }
      }
    }
  }

  // Cash position vs projection
  if (projections?.projected_cash && current.cash) {
    const cashVariance = Math.abs(current.cash - projections.projected_cash) / projections.projected_cash;
    if (cashVariance > 0.10) {
      flags.push({
        type: 'cash_variance',
        actual: current.cash,
        projected: projections.projected_cash,
        variance_pct: Math.round(cashVariance * 100),
        message: `Cash position $${current.cash.toLocaleString()} is ${Math.round(cashVariance * 100)}% ${current.cash > projections.projected_cash ? 'above' : 'below'} the projected $${projections.projected_cash.toLocaleString()}.`
      });
    }
  }

  // Balance sheet balance check
  if (current.total_assets !== undefined && current.total_liabilities !== undefined && current.total_equity !== undefined) {
    const imbalance = Math.abs(current.total_assets - (current.total_liabilities + current.total_equity));
    if (imbalance > 0.01) {
      flags.push({
        type: 'balance_sheet_imbalance',
        assets: current.total_assets,
        liabilities_plus_equity: current.total_liabilities + current.total_equity,
        imbalance,
        message: `Balance sheet does not balance. Assets: $${current.total_assets.toLocaleString()}, L+E: $${(current.total_liabilities + current.total_equity).toLocaleString()}. Difference: $${imbalance.toFixed(2)}.`
      });
    }
  }

  return flags;
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const mode = input.mode || 'full';

  if (mode === 'checklist') {
    process.stdout.write(JSON.stringify(generateChecklist(input)));
  } else if (mode === 'journal_entries') {
    process.stdout.write(JSON.stringify(draftJournalEntries(input.policies || {}, input.period || {})));
  } else if (mode === 'validate') {
    process.stdout.write(JSON.stringify(validateStatements(input.current || {}, input.prior || {}, input.projections || {})));
  } else {
    // Full close package
    const checklist = generateChecklist(input);
    const journalEntries = draftJournalEntries(input.accounting_policies || {}, input.period || {});
    const validationFlags = validateStatements(input.current_statements || {}, input.prior_statements || {}, input.projections || {});

    process.stdout.write(JSON.stringify({
      checklist,
      journal_entries: journalEntries,
      validation_flags: validationFlags,
      ready_to_close: checklist.every(i => i.status === 'ready') && validationFlags.length === 0,
      timestamp: new Date().toISOString()
    }));
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

module.exports = { generateChecklist, draftJournalEntries, validateStatements };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
