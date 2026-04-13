#!/usr/bin/env node
/**
 * echo-synthesis-formatter.js
 * Requirements 10-15, 21: Format output per meeting type with flags for reviewer.
 *
 * Deterministic formatting. Summary narrative by llm-task in pipeline.
 */

const TEMPLATE_DEFAULTS = {
  board: {
    capture: ['decisions', 'rationale', 'decision_makers', 'relevant_context'],
    omit: ['objections_before_final', 'off_topic', 'half_formed_ideas', 'humor'],
    summary_mode: 'executive_summary',
    distribution: 'configured_recipients_only',
    requires_secretary: true
  },
  standup: {
    capture: ['blockers', 'decisions', 'tasks_advanced'],
    omit: ['everything_else'],
    summary_mode: 'bullet_points',
    max_per_participant: 'one_paragraph',
    distribution: 'all_attendees'
  },
  sales_call: {
    capture: ['client_needs', 'commitments_by_party', 'open_questions', 'next_steps_with_owners'],
    omit: ['internal_sidebar', 'pricing_deliberation'],
    summary_mode: 'detailed_breakdown',
    distribution: 'internal_team_only',
    crm_update: true
  },
  design_review: {
    capture: ['decisions', 'rationale', 'alternatives_considered', 'action_items'],
    omit: [],
    summary_mode: 'detailed_breakdown',
    distribution: 'all_attendees'
  },
  one_on_one: {
    capture: ['action_items', 'feedback_given', 'goals_discussed', 'blockers'],
    omit: ['personal_conversation'],
    summary_mode: 'bullet_points',
    distribution: 'participants_only',
    confidential: true
  }
};

function formatForReview(meetingType, actionItems, tentativeItems, flaggedSegments, meetingMeta, customTemplate) {
  const template = customTemplate || TEMPLATE_DEFAULTS[meetingType] || TEMPLATE_DEFAULTS.standup;

  // Build reviewer presentation with flags highlighted
  const flags = [];

  // Low-confidence segments
  for (const seg of (flaggedSegments || [])) {
    for (const flag of (seg.flags || [])) {
      flags.push({
        type: flag.type,
        detail: flag.detail,
        segment_text: seg.text?.substring(0, 100),
        timestamp: seg.start_time,
        severity: flag.severity
      });
    }
  }

  // Tentative items presented separately
  const tentativeFlags = (tentativeItems || []).map(t => ({
    type: 'tentative_action_item',
    detail: `"${t.hedged_language || t.task}" — flagged as tentative. Confirm or remove.`,
    owner: t.owner,
    timestamp: t.timestamp,
    severity: 'review'
  }));

  // Attribution uncertain
  const attributionFlags = (flaggedSegments || [])
    .filter(s => s.flags?.some(f => f.type === 'uncertain_attribution'))
    .map(s => ({
      type: 'uncertain_attribution',
      detail: s.speaker_name,
      segment_text: s.text?.substring(0, 100),
      timestamp: s.start_time,
      severity: 'review'
    }));

  return {
    meeting_type: meetingType,
    template_used: template,
    meeting_meta: {
      title: meetingMeta?.title,
      date: meetingMeta?.date,
      attendees: meetingMeta?.attendees,
      duration_minutes: meetingMeta?.duration_minutes
    },
    action_items: {
      definitive: actionItems || [],
      tentative: tentativeItems || [],
      total: (actionItems || []).length + (tentativeItems || []).length
    },
    flags: {
      all: [...flags, ...tentativeFlags, ...attributionFlags],
      count: flags.length + tentativeFlags.length + attributionFlags.length,
      low_confidence: flags.filter(f => f.type === 'low_confidence').length,
      tentative_items: tentativeFlags.length,
      uncertain_attribution: attributionFlags.length
    },
    reviewer: template.requires_secretary ? meetingMeta?.secretary : meetingMeta?.reviewer,
    requires_specific_reviewer: template.requires_secretary || false,
    distribution_rule: template.distribution,
    confidential: template.confidential || false,
    crm_update: template.crm_update || false,
    llm_instructions: {
      summary_mode: template.summary_mode,
      capture: template.capture,
      omit: template.omit,
      anti_seniority_bias: 'Attribute ideas to the person who originated them in the transcript, not to the highest-title person who agreed. If the analyst proposed it and the VP endorsed it, the analyst originated it.',
      max_per_participant: template.max_per_participant || null
    },
    timestamp: new Date().toISOString()
  };
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const result = formatForReview(
    input.meeting_type || 'standup',
    input.action_items || [],
    input.tentative_items || [],
    input.flagged_segments || [],
    input.meeting_meta || {},
    input.custom_template || null
  );

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

module.exports = { formatForReview, TEMPLATE_DEFAULTS };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
