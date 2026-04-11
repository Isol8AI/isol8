#!/usr/bin/env node
/**
 * pulse-sensitive-claim-detector.js
 * Requirement 35: Flag potentially unverified claims. Adaptive suppression for verified claims.
 *
 * Deterministic keyword/regex (~80%). Adaptability: previously approved claims reduce severity.
 */

const CLAIM_PATTERNS = {
  capability: {
    patterns: ['our platform', 'our product', 'we offer', 'we provide', 'we enable', 'we deliver',
               'our solution', 'our tool', 'you can use .* to', 'allows you to', 'enables you to'],
    severity: 'review',
    message: 'Product capability claim — verify this matches current product documentation.'
  },
  statistic: {
    patterns: ['\\d+%', '\\d+x', 'reduces .* by', 'increases .* by', 'improves .* by',
               'saves .* hours', 'drives .* more', '\\d+ times', 'up to \\d+'],
    severity: 'review',
    message: 'Statistical claim — verify source and accuracy before publishing.'
  },
  competitor: {
    patterns: ['unlike', 'compared to', 'better than', 'faster than', 'cheaper than',
               'more reliable than', 'alternative to', 'switch from', 'replace'],
    severity: 'review',
    message: 'Competitor comparison — verify claims are factual and fair.'
  },
  pricing: {
    patterns: ['\\$\\d', '€\\d', '£\\d', 'free', 'pricing', 'cost', 'starts at',
               'per month', 'per user', 'discount', 'trial'],
    severity: 'review',
    message: 'Pricing reference — verify this reflects current pricing.'
  },
  guarantee: {
    patterns: ['guarantee', 'promise', 'ensure', 'we will always', 'never fail',
               '100% uptime', 'zero downtime', 'risk-free', 'money back'],
    severity: 'high',
    message: 'Guarantee/commitment language — these create legal obligations. Verify with legal.'
  }
};

function detectClaims(text, approvedClaims) {
  const lower = text.toLowerCase();
  const flags = [];
  const approved = approvedClaims || {};

  for (const [type, config] of Object.entries(CLAIM_PATTERNS)) {
    for (const pattern of config.patterns) {
      const regex = new RegExp(pattern, 'gi');
      const matches = lower.match(regex);
      if (matches) {
        for (const match of [...new Set(matches)]) {
          // Check if this specific claim has been previously approved
          const claimKey = `${type}:${match.trim().substring(0, 50)}`;
          const priorApprovals = approved[claimKey] || 0;

          flags.push({
            type,
            match: match.trim(),
            severity: priorApprovals >= 2 ? 'previously_approved' : config.severity,
            message: priorApprovals >= 2
              ? `${config.message} (Previously approved ${priorApprovals} times — reduced severity.)`
              : config.message,
            prior_approvals: priorApprovals,
            needs_review: priorApprovals < 2
          });
        }
      }
    }
  }

  // Deduplicate by match
  const seen = new Set();
  const deduped = flags.filter(f => {
    const key = `${f.type}:${f.match}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return {
    flags: deduped,
    needs_review: deduped.filter(f => f.needs_review).length,
    previously_approved: deduped.filter(f => !f.needs_review).length,
    high_severity: deduped.filter(f => f.severity === 'high').length,
    timestamp: new Date().toISOString()
  };
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const text = input.text || input.draft?.body || '';
  const approvedClaims = input.approved_claims || {};
  const result = detectClaims(text, approvedClaims);

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

module.exports = { detectClaims };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
