#!/usr/bin/env node
/**
 * lens-pass-evaluator.js
 * Requirements 10, 11: Evaluate completeness after each search pass.
 *
 * Deterministic gap analysis. Zero LLM (query refinement happens in pipeline via llm-task).
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const subQuestions = input.sub_questions || [];
  const evidenceMap = input.evidence_map || {};
  const passNumber = input.pass_number || 1;
  const maxPasses = input.max_passes || 5;
  const researchStakes = input.stakes || 'standard'; // casual, standard, high_stakes
  const confidenceThresholds = input.confidence_thresholds || {};

  const minPassesByStakes = { casual: 2, standard: 3, high_stakes: 5 };
  const minPasses = minPassesByStakes[researchStakes] || 3;

  const evaluation = subQuestions.map(sq => {
    const evidence = evidenceMap[sq.id] || { sources: [], tier: 'gap' };
    const sourceCount = evidence.sources.length;
    const independentCount = evidence.sources.filter(s => s.independent).length;
    const primaryCount = evidence.sources.filter(s => s.tier === 'primary').length;

    // Determine current confidence tier
    const verifiedThreshold = confidenceThresholds.verified_min_independent_primaries || 3;
    let currentTier = 'gap';
    if (independentCount >= verifiedThreshold && primaryCount >= 1) currentTier = 'verified';
    else if (primaryCount >= 1 && independentCount >= 2) currentTier = 'supported';
    else if (sourceCount >= 1) currentTier = 'single_source';
    if (evidence.has_contradictions) currentTier = 'contested';

    const needsMorePasses = currentTier === 'gap' || currentTier === 'single_source' ||
                            (researchStakes === 'high_stakes' && currentTier !== 'verified');

    return {
      sub_question_id: sq.id,
      question: sq.question,
      current_tier: currentTier,
      source_count: sourceCount,
      independent_count: independentCount,
      primary_count: primaryCount,
      has_contradictions: evidence.has_contradictions || false,
      needs_more_passes: needsMorePasses,
      refinement_hint: needsMorePasses
        ? (sourceCount === 0 ? 'broaden_query' : sourceCount === 1 ? 'find_corroboration' : 'seek_primary')
        : null
    };
  });

  const allSatisfied = evaluation.every(e => !e.needs_more_passes);
  const shouldContinue = !allSatisfied && passNumber < maxPasses && passNumber < minPasses + 2;

  const result = {
    pass_number: passNumber,
    evaluation,
    all_satisfied: allSatisfied,
    should_continue: shouldContinue,
    action: allSatisfied ? 'proceed_to_synthesis' :
            passNumber >= maxPasses ? 'max_passes_reached_synthesize_with_gaps' :
            'run_next_pass',
    sub_questions_needing_passes: evaluation.filter(e => e.needs_more_passes).length,
    sub_questions_satisfied: evaluation.filter(e => !e.needs_more_passes).length,
    stakes: researchStakes,
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
