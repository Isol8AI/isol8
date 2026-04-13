#!/usr/bin/env node
/**
 * pulse-queue-limiter.js
 * Requirement 48: Prevent queue from growing too large for genuine review.
 *
 * Deterministic counter. Adaptability: adjusts based on marketer's actual throughput.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const queueSize = input.current_queue_size || 0;
  const maxQueue = input.max_queue_size || 10;
  const weeklyReviewHistory = input.review_history || [];

  // Track actual review throughput
  const thisWeekReviewed = weeklyReviewHistory.filter(r => {
    const reviewDate = new Date(r.reviewed_at);
    const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
    return reviewDate.getTime() > weekAgo;
  }).length;

  // Detect rubber-stamping: if marketer approves >80% without edits, flag concern
  const approvedWithoutEdits = weeklyReviewHistory.filter(r =>
    r.action === 'approved' && !r.had_edits
  ).length;
  const rubberStampRate = weeklyReviewHistory.length > 0
    ? approvedWithoutEdits / weeklyReviewHistory.length
    : 0;

  const atLimit = queueSize >= maxQueue;
  const rubberStamping = rubberStampRate > 0.8 && weeklyReviewHistory.length >= 5;

  // Adaptive limit suggestion
  let adaptiveSuggestion = null;
  if (thisWeekReviewed > maxQueue * 1.5 && !rubberStamping) {
    adaptiveSuggestion = {
      action: 'increase_limit',
      suggested: Math.min(25, Math.round(thisWeekReviewed * 0.8)),
      reason: `You reviewed ${thisWeekReviewed} pieces this week with genuine edits. Your limit of ${maxQueue} may be too conservative.`
    };
  } else if (rubberStamping) {
    adaptiveSuggestion = {
      action: 'decrease_limit',
      suggested: Math.max(5, Math.round(maxQueue * 0.7)),
      reason: `${Math.round(rubberStampRate * 100)}% of recent reviews were approved without edits. This suggests the queue may be too large for genuine review. Consider reducing to ${Math.max(5, Math.round(maxQueue * 0.7))} to maintain editorial quality.`
    };
  }

  const result = {
    queue_size: queueSize,
    max_queue: maxQueue,
    at_limit: atLimit,
    action: atLimit ? 'pause_generation' : 'continue',
    this_week_reviewed: thisWeekReviewed,
    rubber_stamp_rate: Math.round(rubberStampRate * 100),
    rubber_stamping_detected: rubberStamping,
    adaptive_suggestion: adaptiveSuggestion,
    message: atLimit
      ? `Review queue has ${queueSize} pieces pending (limit: ${maxQueue}). Content generation paused so your review stays genuine. Approve or clear some before I continue.`
      : rubberStamping
        ? `${Math.round(rubberStampRate * 100)}% of recent reviews were approved without edits. A queue that gets bulk-approved is operationally equivalent to no approval gate. Consider reviewing more carefully or reducing your queue limit.`
        : null,
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
