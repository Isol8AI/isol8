#!/usr/bin/env node
/**
 * lens-confidence-estimator.js
 * Requirement 9: Estimate expected confidence per sub-question before searching.
 *
 * Deterministic estimation from source availability metadata + historical data.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const subQuestions = input.sub_questions || [];
  const verticalConfig = input.vertical_config || {};
  const historicalData = input.historical_research || {};

  const estimates = subQuestions.map(sq => {
    const vertical = sq.vertical;
    const hierarchy = verticalConfig[vertical] || {};
    const primaryCount = (hierarchy.primary || []).length;
    const historicalHits = historicalData[sq.domain || vertical] || {};

    // Estimate based on source availability
    let expectedConfidence = 'supported';
    let flag = null;

    if (primaryCount >= 3) {
      expectedConfidence = 'verified';
    } else if (primaryCount >= 1) {
      expectedConfidence = 'supported';
    } else {
      expectedConfidence = 'single_source';
      flag = `Primary sources likely thin for this sub-question in the ${vertical} vertical. Consider adjusting scope or accepting lower confidence.`;
    }

    // Adjust based on historical data
    if (historicalHits.avg_sources_found !== undefined) {
      if (historicalHits.avg_sources_found >= 3) expectedConfidence = 'verified';
      else if (historicalHits.avg_sources_found >= 1.5) expectedConfidence = 'supported';
      else if (historicalHits.avg_sources_found < 1) {
        expectedConfidence = 'gap_likely';
        flag = `Previous research in this area found fewer than 1 source on average. Data void is likely.`;
      }
    }

    // Check if this is a niche domain
    const isNiche = hierarchy.niche_mode || primaryCount <= 2;
    if (isNiche && !flag) {
      flag = `Niche domain — only ${primaryCount} primary sources configured. Verification thresholds adjusted.`;
    }

    return {
      sub_question: sq.question,
      vertical,
      expected_confidence: expectedConfidence,
      primary_sources_available: primaryCount,
      historical_avg_sources: historicalHits.avg_sources_found || null,
      is_niche: isNiche,
      flag
    };
  });

  const thinAreas = estimates.filter(e => e.flag);

  const result = {
    estimates,
    thin_areas: thinAreas,
    has_thin_areas: thinAreas.length > 0,
    summary: `${estimates.length} sub-questions. ${estimates.filter(e => e.expected_confidence === 'verified').length} expected Verified, ${thinAreas.length} flagged as potentially thin.`,
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
