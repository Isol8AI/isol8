#!/usr/bin/env node
/**
 * vera-activation-check.js
 * Requirements 1, 2, 6: Validate escalation path, business hours, authorized actions.
 * Blocks activation if human lifeline is missing.
 *
 * Deterministic. Zero LLM.
 */

async function main() {
  const input = await readStdin();
  const checks = [];

  // --- Requirement 1/2: Escalation path exists ---
  const escalationPath = input?.escalation_path || null;
  if (!escalationPath) {
    checks.push({
      check: 'escalation_path',
      pass: false,
      severity: 'blocker',
      reason: 'No human escalation path configured. Vera cannot go live without a verified human backup.',
      remediation: 'Configure at least one: a named agent, team inbox, Slack channel, or phone number as the escalation destination.'
    });
  } else {
    const hasDestination = escalationPath.slack_channel || escalationPath.email_inbox ||
                           escalationPath.phone_number || escalationPath.agent_name;
    if (!hasDestination) {
      checks.push({
        check: 'escalation_path',
        pass: false,
        severity: 'blocker',
        reason: 'Escalation path is configured but has no valid destination.',
        remediation: 'Add at least one destination: slack_channel, email_inbox, phone_number, or agent_name.'
      });
    } else {
      checks.push({
        check: 'escalation_path',
        pass: true,
        destinations: {
          slack: escalationPath.slack_channel || null,
          email: escalationPath.email_inbox || null,
          phone: escalationPath.phone_number || null,
          agent: escalationPath.agent_name || null
        }
      });
    }
  }

  // --- Requirement 6: Business hours configured ---
  const businessHours = input?.business_hours || null;
  if (!businessHours) {
    checks.push({
      check: 'business_hours',
      pass: false,
      severity: 'blocker',
      reason: 'Business hours not configured. Vera needs to know when humans are available vs when to use out-of-hours handling.',
      remediation: 'Configure staffed hours, timezone, and out-of-hours behavior (queue_with_callback, email_response, or voicemail).'
    });
  } else {
    const hasRequired = businessHours.timezone && businessHours.staffed_hours?.start &&
                        businessHours.staffed_hours?.end && businessHours.out_of_hours_behavior;
    if (!hasRequired) {
      const missing = [];
      if (!businessHours.timezone) missing.push('timezone');
      if (!businessHours.staffed_hours?.start) missing.push('staffed_hours.start');
      if (!businessHours.staffed_hours?.end) missing.push('staffed_hours.end');
      if (!businessHours.out_of_hours_behavior) missing.push('out_of_hours_behavior');
      checks.push({
        check: 'business_hours',
        pass: false,
        severity: 'blocker',
        reason: `Business hours incomplete. Missing: ${missing.join(', ')}`,
        remediation: 'Complete business hours configuration with all required fields.'
      });
    } else {
      checks.push({ check: 'business_hours', pass: true });
    }
  }

  // --- Authorized actions scope ---
  const authorizedActions = input?.authorized_actions || null;
  if (!authorizedActions) {
    checks.push({
      check: 'authorized_actions',
      pass: false,
      severity: 'warning',
      reason: 'No authorized action scope configured. Vera will escalate all refunds, returns, and account changes to humans.',
      remediation: 'Configure max_refund_amount, allowed_return_types, and autonomous_actions in vera-config/authorized-actions.'
    });
  } else {
    checks.push({ check: 'authorized_actions', pass: true, scope: authorizedActions });
  }

  // --- Knowledge base exists ---
  const kbStatus = input?.kb_status || null;
  if (!kbStatus || !kbStatus.document_count || kbStatus.document_count === 0) {
    checks.push({
      check: 'knowledge_base',
      pass: false,
      severity: 'blocker',
      reason: 'Knowledge base is empty. Vera cannot answer any business-specific questions without KB content.',
      remediation: 'Ingest policy documents, FAQs, product documentation, and SOPs into local-rag-qdrant before activation.'
    });
  } else {
    checks.push({
      check: 'knowledge_base',
      pass: true,
      document_count: kbStatus.document_count,
      last_updated: kbStatus.last_updated
    });
  }

  // --- Confidence threshold ---
  const confidenceThreshold = input?.confidence_threshold;
  if (confidenceThreshold === undefined || confidenceThreshold === null) {
    checks.push({
      check: 'confidence_threshold',
      pass: true,
      note: 'Using default confidence threshold of 0.85'
    });
  } else {
    checks.push({ check: 'confidence_threshold', pass: true, threshold: confidenceThreshold });
  }

  const blockers = checks.filter(c => !c.pass && c.severity === 'blocker');
  const warnings = checks.filter(c => !c.pass && c.severity === 'warning');
  const allPassed = blockers.length === 0;

  const result = {
    pass: allPassed,
    blockers,
    warnings,
    checks,
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
  process.exit(allPassed ? 0 : 1);
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

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
