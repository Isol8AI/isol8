#!/usr/bin/env node
/**
 * pulse-performance-connector.js
 * Requirement 42: Connect content to business outcomes. Deterministic join.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const contentPieces = input.content || [];
  const trafficData = input.traffic_data || []; // from biz-reporter/GA4
  const conversionData = input.conversion_data || []; // from posthog
  const revenueData = input.revenue_data || []; // from Stripe via biz-reporter

  const connected = contentPieces.map(piece => {
    const url = piece.url || '';
    const utmSource = piece.utm_source || '';

    // Match traffic by URL or UTM
    const traffic = trafficData.filter(t =>
      t.landing_page === url || t.utm_source === utmSource || t.referrer?.includes(url)
    );
    const totalVisits = traffic.reduce((sum, t) => sum + (t.sessions || t.visits || 0), 0);
    const totalUsers = traffic.reduce((sum, t) => sum + (t.users || 0), 0);

    // Match conversions
    const conversions = conversionData.filter(c =>
      c.first_touch_url === url || c.attribution_source === utmSource
    );
    const signups = conversions.filter(c => c.event === 'signup' || c.event === 'trial_start').length;
    const paidConversions = conversions.filter(c => c.event === 'purchase' || c.event === 'subscription_start').length;

    // Match revenue
    const attributedRevenue = revenueData
      .filter(r => r.attribution_source === utmSource || r.first_touch_content === piece.id)
      .reduce((sum, r) => sum + (r.amount || 0), 0);

    return {
      content_id: piece.id,
      title: piece.title,
      url,
      published_date: piece.published_date,
      content_type: piece.type,
      engagement: { visits: totalVisits, users: totalUsers },
      conversions: { signups, paid: paidConversions },
      revenue: attributedRevenue,
      roi_signal: totalVisits > 0
        ? (paidConversions > 0 ? 'revenue_driving' : signups > 0 ? 'lead_generating' : 'traffic_only')
        : 'no_traffic'
    };
  });

  // Sort by business impact
  const ranked = connected.sort((a, b) => {
    if (b.revenue !== a.revenue) return b.revenue - a.revenue;
    if (b.conversions.paid !== a.conversions.paid) return b.conversions.paid - a.conversions.paid;
    if (b.conversions.signups !== a.conversions.signups) return b.conversions.signups - a.conversions.signups;
    return b.engagement.visits - a.engagement.visits;
  });

  const result = {
    content_performance: ranked,
    top_3_by_outcome: ranked.slice(0, 3),
    revenue_driving: ranked.filter(c => c.roi_signal === 'revenue_driving').length,
    lead_generating: ranked.filter(c => c.roi_signal === 'lead_generating').length,
    traffic_only: ranked.filter(c => c.roi_signal === 'traffic_only').length,
    no_traffic: ranked.filter(c => c.roi_signal === 'no_traffic').length,
    total_attributed_revenue: ranked.reduce((sum, c) => sum + c.revenue, 0),
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
}

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => { try { resolve(JSON.parse(data)); } catch { resolve(null); } });
    if (process.stdin.isTTY) resolve(null);
  });
}

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
