#!/usr/bin/env node
/**
 * lens-confidence-degrader.js
 * Requirement 34: Downgrade confidence when underlying sources change.
 *
 * Deterministic source check. Dismissal suppression for repeated alerts.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const verifiedFindings = input.verified_findings || [];
  const sourceStatusUpdates = input.source_status_updates || {};
  const dismissalHistory = input.dismissal_history || {};

  const downgrades = [];
  const unchanged = [];

  for (const finding of verifiedFindings) {
    const findingId = finding.id || finding.claim_id;
    const sources = finding.sources || [];
    let shouldDowngrade = false;
    let newTier = finding.confidence_tier;
    let reason = null;

    for (const source of sources) {
      const status = sourceStatusUpdates[source.url];
      if (!status) continue;

      if (status.retracted) {
        shouldDowngrade = true;
        newTier = 'gap';
        reason = `Source retracted: ${source.url}. Finding no longer supported.`;
      } else if (status.superseded) {
        shouldDowngrade = true;
        newTier = finding.confidence_tier === 'verified' ? 'single_source' : 'gap';
        reason = `Source superseded by: ${status.superseded_by}. Original finding may no longer be accurate.`;
      } else if (status.content_changed) {
        shouldDowngrade = true;
        newTier = 'single_source';
        reason = `Source content changed since verification. Claim may no longer match current source.`;
      } else if (status.inaccessible) {
        shouldDowngrade = true;
        newTier = 'single_source';
        reason = `Source no longer accessible: ${source.url}. Cannot re-verify.`;
      }
    }

    if (shouldDowngrade) {
      // Check dismissal history — suppress if user has dismissed this type 3+ times
      const dismissKey = `${findingId}:${reason?.split(':')[0] || 'change'}`;
      const priorDismissals = dismissalHistory[dismissKey] || 0;

      downgrades.push({
        finding_id: findingId,
        claim: finding.claim_text,
        previous_tier: finding.confidence_tier,
        new_tier: newTier,
        reason,
        suppressed: priorDismissals >= 3,
        prior_dismissals: priorDismissals,
        alert_severity: priorDismissals >= 3 ? 'informational' : 'action_required'
      });
    } else {
      unchanged.push({ finding_id: findingId, tier: finding.confidence_tier });
    }
  }

  const activeDowgrades = downgrades.filter(d => !d.suppressed);

  const result = {
    downgrades,
    active_downgrades: activeDowgrades.length,
    suppressed_downgrades: downgrades.length - activeDowgrades.length,
    unchanged: unchanged.length,
    total_checked: verifiedFindings.length,
    has_downgrades: activeDowgrades.length > 0,
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
