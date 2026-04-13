#!/usr/bin/env node
/**
 * tally-metrics-calculator.js
 * Requirements 26, 27, 28, 31, 35, 36: Financial metrics with traces and alerts.
 *
 * Deterministic math. Zero LLM.
 */

function calculateMetrics(data) {
  const { revenue, cogs, expenses, cash, stripe, headcount, config } = data;
  const thresholds = config?.metric_thresholds || {};
  const benchmarks = config?.benchmarks || {};
  const metrics = {};
  const traces = {};
  const alerts = [];

  // Gross Margin
  const totalRevenue = revenue?.current_month || 0;
  const totalCogs = cogs?.current_month || 0;
  const grossProfit = totalRevenue - totalCogs;
  const grossMargin = totalRevenue > 0 ? Math.round((grossProfit / totalRevenue) * 1000) / 10 : 0;
  metrics.gross_margin = grossMargin;
  traces.gross_margin = {
    revenue: totalRevenue, cogs: totalCogs, gross_profit: grossProfit,
    formula: `(${totalRevenue} - ${totalCogs}) / ${totalRevenue} = ${grossMargin}%`,
    source: 'xero/revenue + xero/cogs accounts'
  };
  const priorGrossMargin = revenue?.prior_month > 0
    ? Math.round(((revenue.prior_month - (cogs?.prior_month || 0)) / revenue.prior_month) * 1000) / 10 : null;
  if (priorGrossMargin !== null && Math.abs(grossMargin - priorGrossMargin) > (thresholds.gross_margin_compression_points || 3)) {
    alerts.push({ metric: 'gross_margin', current: grossMargin, prior: priorGrossMargin, change: grossMargin - priorGrossMargin, threshold: thresholds.gross_margin_compression_points || 3, message: `Gross margin moved ${Math.abs(grossMargin - priorGrossMargin).toFixed(1)} points (${priorGrossMargin}% → ${grossMargin}%).` });
  }

  // MRR / ARR (from Stripe)
  const mrr = stripe?.mrr || 0;
  const arr = mrr * 12;
  const priorMrr = stripe?.prior_mrr || 0;
  const mrrGrowth = priorMrr > 0 ? Math.round(((mrr - priorMrr) / priorMrr) * 1000) / 10 : 0;
  metrics.mrr = mrr;
  metrics.arr = arr;
  metrics.mrr_growth = mrrGrowth;
  traces.mrr = { mrr, arr, prior_mrr: priorMrr, growth: `${mrrGrowth}%`, source: 'stripe/subscriptions' };

  // Burn Rate (trailing 3-month average operating expenses)
  const opex3m = expenses?.trailing_3m || [];
  const burnRate = opex3m.length > 0 ? Math.round(opex3m.reduce((a, b) => a + b, 0) / opex3m.length) : 0;
  metrics.burn_rate = burnRate;
  traces.burn_rate = { trailing_months: opex3m, average: burnRate, source: 'xero/expense accounts' };
  const priorBurn = expenses?.prior_burn_rate || 0;
  if (priorBurn > 0) {
    const burnIncrease = Math.round(((burnRate - priorBurn) / priorBurn) * 1000) / 10;
    if (burnIncrease > (thresholds.burn_rate_increase_pct || 15)) {
      alerts.push({ metric: 'burn_rate', current: burnRate, prior: priorBurn, change_pct: burnIncrease, threshold: thresholds.burn_rate_increase_pct || 15, message: `Burn rate increased ${burnIncrease}% ($${priorBurn.toLocaleString()} → $${burnRate.toLocaleString()}).` });
    }
  }

  // Burn Multiple
  const netNewArr = (mrr - priorMrr) * 12;
  const netBurn = burnRate - totalRevenue;
  const burnMultiple = netNewArr > 0 ? Math.round((Math.abs(netBurn) / netNewArr) * 10) / 10 : null;
  metrics.burn_multiple = burnMultiple;
  traces.burn_multiple = { net_burn: netBurn, net_new_arr: netNewArr, formula: burnMultiple ? `|${netBurn}| / ${netNewArr} = ${burnMultiple}x` : 'Cannot calculate — no net new ARR', source: 'derived from burn_rate and stripe/mrr', benchmark: benchmarks.burn_multiple || null };

  // Runway
  const currentCash = cash?.current_balance || 0;
  const runway = burnRate > totalRevenue ? Math.round(currentCash / (burnRate - totalRevenue)) : null;
  metrics.runway_months = runway;
  traces.runway = { current_cash: currentCash, monthly_net_burn: burnRate - totalRevenue, formula: runway ? `${currentCash} / ${burnRate - totalRevenue} = ${runway} months` : 'Revenue exceeds burn — infinite runway', source: 'plaid/balances + xero/expenses' };
  if (runway !== null && runway < (thresholds.runway_months_min || 6)) {
    alerts.push({ metric: 'runway', months: runway, threshold: thresholds.runway_months_min || 6, message: `Runway is ${runway} months at current burn. Below ${thresholds.runway_months_min || 6}-month threshold.` });
  }

  // Revenue per Employee
  const revPerEmployee = headcount > 0 ? Math.round(totalRevenue / headcount) : null;
  metrics.revenue_per_employee = revPerEmployee;
  traces.revenue_per_employee = { revenue: totalRevenue, headcount, formula: revPerEmployee ? `${totalRevenue} / ${headcount} = $${revPerEmployee.toLocaleString()}` : 'Headcount not configured', source: 'xero/revenue + config/headcount' };

  // OpEx % by Category
  const opexByCategory = expenses?.by_category || {};
  const opexPct = {};
  for (const [cat, amount] of Object.entries(opexByCategory)) {
    opexPct[cat] = totalRevenue > 0 ? Math.round((amount / totalRevenue) * 1000) / 10 : 0;
  }
  metrics.opex_pct_by_category = opexPct;
  traces.opex_pct_by_category = { categories: opexByCategory, total_revenue: totalRevenue, source: 'xero/expense accounts' };

  // LTV:CAC
  const ltv = stripe?.ltv || null;
  const cac = expenses?.cac || null;
  const ltvCac = (ltv && cac && cac > 0) ? Math.round((ltv / cac) * 10) / 10 : null;
  metrics.ltv_cac = ltvCac;
  traces.ltv_cac = { ltv, cac, formula: ltvCac ? `${ltv} / ${cac} = ${ltvCac}` : 'LTV or CAC data not available', source: 'stripe/subscriptions + xero/sales-marketing', benchmark: benchmarks.ltv_cac || null };

  // Cash projections (30/60/90 days)
  const monthlyNetBurn = burnRate - totalRevenue;
  metrics.cash_projections = {
    current: currentCash,
    day_30: Math.round(currentCash - monthlyNetBurn),
    day_60: Math.round(currentCash - monthlyNetBurn * 2),
    day_90: Math.round(currentCash - monthlyNetBurn * 3)
  };

  return { metrics, traces, alerts };
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const result = calculateMetrics(input);
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

module.exports = { calculateMetrics };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
