#!/usr/bin/env node
/**
 * echo-deadline-tracker.js
 * Requirements 33, 34: Track action item status, flag approaching deadlines.
 *
 * Deterministic date comparison. Zero LLM.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const actionItems = input.action_items || [];
  const pmToolStatus = input.pm_tool_status || {};
  const now = Date.now();
  const alertDaysBeforeDeadline = input.alert_days_before || 2;

  const tracked = actionItems.map(item => {
    // Check PM tool for completion status
    const pmStatus = pmToolStatus[item.id] || {};
    const completed = pmStatus.completed || item.completed || false;
    const completedDate = pmStatus.completed_date || null;

    // Parse deadline
    let deadlineDate = null;
    let daysUntilDeadline = null;
    let isOverdue = false;
    let isApproaching = false;

    if (item.deadline) {
      deadlineDate = parseDeadline(item.deadline, item.meeting_date);
      if (deadlineDate) {
        daysUntilDeadline = Math.floor((deadlineDate.getTime() - now) / (1000 * 60 * 60 * 24));
        isOverdue = !completed && daysUntilDeadline < 0;
        isApproaching = !completed && daysUntilDeadline >= 0 && daysUntilDeadline <= alertDaysBeforeDeadline;
      }
    }

    const daysSinceAssigned = Math.floor((now - new Date(item.meeting_date || item.timestamp).getTime()) / (1000 * 60 * 60 * 24));

    return {
      id: item.id,
      owner: item.owner,
      task: item.task,
      deadline: item.deadline,
      deadline_date: deadlineDate?.toISOString() || null,
      meeting_title: item.meeting_title,
      meeting_date: item.meeting_date,
      timestamp_link: item.timestamp_link,
      completed,
      completed_date: completedDate,
      days_until_deadline: daysUntilDeadline,
      days_since_assigned: daysSinceAssigned,
      status: completed ? 'completed' :
              isOverdue ? 'overdue' :
              isApproaching ? 'approaching_deadline' :
              'in_progress',
      alert: (isOverdue || isApproaching) ? {
        type: isOverdue ? 'overdue' : 'approaching',
        message: isOverdue
          ? `OVERDUE: "${item.task}" assigned to ${item.owner} was due ${Math.abs(daysUntilDeadline)} days ago (from ${item.meeting_title}).`
          : `APPROACHING: "${item.task}" assigned to ${item.owner} is due in ${daysUntilDeadline} day(s) (from ${item.meeting_title}).`,
        notify: [item.owner, item.meeting_organizer].filter(Boolean)
      } : null
    };
  });

  const overdue = tracked.filter(t => t.status === 'overdue');
  const approaching = tracked.filter(t => t.status === 'approaching_deadline');
  const completed = tracked.filter(t => t.status === 'completed');
  const inProgress = tracked.filter(t => t.status === 'in_progress');

  // No-deadline items older than 7 days without status
  const stale = tracked.filter(t =>
    !t.completed && !t.deadline && t.days_since_assigned > 7
  );

  const result = {
    tracked,
    overdue: overdue.length,
    approaching: approaching.length,
    completed: completed.length,
    in_progress: inProgress.length,
    stale_no_deadline: stale.length,
    alerts: [...overdue, ...approaching].map(t => t.alert).filter(Boolean),
    digest_items: tracked.filter(t => !t.completed),
    follow_through_rate: tracked.length > 0
      ? Math.round((completed.length / tracked.length) * 100)
      : null,
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
}

function parseDeadline(deadlineText, meetingDate) {
  if (!deadlineText) return null;
  const lower = deadlineText.toLowerCase();
  const meetDate = new Date(meetingDate || Date.now());

  const dayMap = { sunday: 0, monday: 1, tuesday: 2, wednesday: 3, thursday: 4, friday: 5, saturday: 6 };

  // "by Friday" — next occurrence of that day
  for (const [day, num] of Object.entries(dayMap)) {
    if (lower.includes(day)) {
      const target = new Date(meetDate);
      const daysUntil = (num - meetDate.getDay() + 7) % 7 || 7;
      target.setDate(target.getDate() + daysUntil);
      return target;
    }
  }

  // "by end of week" / "by eow"
  if (lower.includes('end of week') || lower.includes('eow')) {
    const target = new Date(meetDate);
    const daysUntilFri = (5 - meetDate.getDay() + 7) % 7 || 7;
    target.setDate(target.getDate() + daysUntilFri);
    return target;
  }

  // "by end of day" / "by eod" / "by cob"
  if (lower.includes('end of day') || lower.includes('eod') || lower.includes('cob')) {
    return meetDate; // Same day
  }

  // "by tomorrow"
  if (lower.includes('tomorrow')) {
    const target = new Date(meetDate);
    target.setDate(target.getDate() + 1);
    return target;
  }

  // "by next week"
  if (lower.includes('next week')) {
    const target = new Date(meetDate);
    target.setDate(target.getDate() + 7);
    return target;
  }

  // "within X days/weeks"
  const durationMatch = lower.match(/within (\d+)\s+(days?|weeks?)/);
  if (durationMatch) {
    const target = new Date(meetDate);
    const amount = parseInt(durationMatch[1]);
    const unit = durationMatch[2].startsWith('week') ? 7 : 1;
    target.setDate(target.getDate() + amount * unit);
    return target;
  }

  return null;
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

module.exports = { parseDeadline };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
