#!/usr/bin/env node
/**
 * lens-change-describer.js
 * Requirement 33: Describe source changes specifically, not vaguely.
 *
 * Deterministic diff for structured docs. llm-task in pipeline for unstructured.
 */

function describeStructuredChange(previous, current, sourceType) {
  const changes = [];

  if (sourceType === 'financial_filing') {
    // Compare key financial metrics
    const metrics = ['revenue', 'net_income', 'eps', 'guidance', 'debt', 'cash'];
    for (const metric of metrics) {
      if (previous[metric] !== undefined && current[metric] !== undefined && previous[metric] !== current[metric]) {
        const direction = current[metric] > previous[metric] ? 'increased' : 'decreased';
        const pctChange = previous[metric] !== 0
          ? Math.round(((current[metric] - previous[metric]) / Math.abs(previous[metric])) * 100)
          : null;
        changes.push({
          field: metric,
          previous: previous[metric],
          current: current[metric],
          direction,
          pct_change: pctChange,
          description: `${metric} ${direction} from ${previous[metric]} to ${current[metric]}${pctChange ? ` (${pctChange > 0 ? '+' : ''}${pctChange}%)` : ''}.`
        });
      }
    }
  }

  if (sourceType === 'regulation' || sourceType === 'legal') {
    // Section-level diff
    const prevSections = previous.sections || {};
    const currSections = current.sections || {};
    const allSections = new Set([...Object.keys(prevSections), ...Object.keys(currSections)]);

    for (const section of allSections) {
      if (!prevSections[section] && currSections[section]) {
        changes.push({
          field: section,
          type: 'added',
          description: `New section added: ${section}.`
        });
      } else if (prevSections[section] && !currSections[section]) {
        changes.push({
          field: section,
          type: 'removed',
          description: `Section removed: ${section}.`
        });
      } else if (prevSections[section] !== currSections[section]) {
        changes.push({
          field: section,
          type: 'modified',
          previous_excerpt: (prevSections[section] || '').substring(0, 200),
          current_excerpt: (currSections[section] || '').substring(0, 200),
          description: `Section ${section} was modified.`
        });
      }
    }
  }

  if (sourceType === 'documentation' || sourceType === 'changelog') {
    // Version comparison
    if (previous.version && current.version && previous.version !== current.version) {
      changes.push({
        field: 'version',
        previous: previous.version,
        current: current.version,
        description: `Version updated from ${previous.version} to ${current.version}.`
      });
    }
    // New entries
    const prevEntries = new Set((previous.entries || []).map(e => e.id || e.title));
    const newEntries = (current.entries || []).filter(e => !prevEntries.has(e.id || e.title));
    if (newEntries.length > 0) {
      changes.push({
        field: 'new_entries',
        count: newEntries.length,
        entries: newEntries.map(e => e.title || e.summary).slice(0, 5),
        description: `${newEntries.length} new entries added.`
      });
    }
  }

  return changes;
}

function describeTextDiff(previousText, currentText) {
  // Simple word-level diff statistics
  const prevWords = (previousText || '').split(/\s+/);
  const currWords = (currentText || '').split(/\s+/);
  const prevSet = new Set(prevWords);
  const currSet = new Set(currWords);

  const added = [...currSet].filter(w => !prevSet.has(w)).length;
  const removed = [...prevSet].filter(w => !currSet.has(w)).length;
  const lengthChange = currWords.length - prevWords.length;

  return {
    previous_word_count: prevWords.length,
    current_word_count: currWords.length,
    words_added: added,
    words_removed: removed,
    length_change: lengthChange,
    is_substantial: (added + removed) > Math.min(prevWords.length, currWords.length) * 0.1,
    needs_llm_summary: true // Pipeline uses llm-task for semantic summary of unstructured changes
  };
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const sourceType = input.source_type || 'unstructured';
  let result;

  if (['financial_filing', 'regulation', 'legal', 'documentation', 'changelog'].includes(sourceType)) {
    const changes = describeStructuredChange(
      input.previous || {},
      input.current || {},
      sourceType
    );
    result = {
      source: input.source_url,
      source_type: sourceType,
      changes,
      change_count: changes.length,
      has_changes: changes.length > 0,
      needs_llm_summary: false,
      timestamp: new Date().toISOString()
    };
  } else {
    const diff = describeTextDiff(input.previous_text || '', input.current_text || '');
    result = {
      source: input.source_url,
      source_type: sourceType,
      diff_stats: diff,
      has_changes: diff.is_substantial,
      needs_llm_summary: diff.is_substantial,
      llm_context: diff.is_substantial
        ? 'Summarize what changed between the previous and current version. Be specific about what was added, removed, or modified. Focus on changes that affect the accuracy of findings built on this source.'
        : null,
      timestamp: new Date().toISOString()
    };
  }

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

module.exports = { describeStructuredChange, describeTextDiff };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
