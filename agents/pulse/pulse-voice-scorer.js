#!/usr/bin/env node
/**
 * pulse-voice-scorer.js
 * Requirements 5, 6: Score content against brand voice. Hybrid: ~60% deterministic, ~40% llm-task.
 *
 * Deterministic: banned phrases, anti-patterns, terminology violations.
 * LLM (in pipeline): tone scale alignment and overall coherence.
 */

function scoreVoiceDeterministic(text, voiceDoc) {
  const lower = text.toLowerCase();
  const flags = [];
  let deductions = 0;

  // Check 1: Banned phrases
  const bannedPhrases = voiceDoc.banned_phrases || [];
  for (const phrase of bannedPhrases) {
    if (lower.includes(phrase.toLowerCase())) {
      flags.push({
        type: 'banned_phrase',
        phrase,
        severity: 'high',
        detail: `Contains banned phrase: "${phrase}". Remove or rephrase.`
      });
      deductions += 10;
    }
  }

  // Check 2: Anti-patterns
  const antiPatterns = voiceDoc.anti_patterns || [];
  for (const pattern of antiPatterns) {
    if (lower.includes(pattern.toLowerCase())) {
      flags.push({
        type: 'anti_pattern',
        pattern,
        severity: 'medium',
        detail: `Contains anti-pattern: "${pattern}". This is explicitly off-brand.`
      });
      deductions += 7;
    }
  }

  // Check 3: Terminology — using avoided terms instead of preferred
  const terminology = voiceDoc.terminology || {};
  const avoidTerms = terminology.avoid || {};
  for (const [avoid, preferred] of Object.entries(avoidTerms)) {
    if (lower.includes(avoid.toLowerCase())) {
      flags.push({
        type: 'terminology_violation',
        found: avoid,
        preferred,
        severity: 'medium',
        detail: `Uses "${avoid}" — brand prefers "${preferred}".`
      });
      deductions += 5;
    }
  }

  // Check 4: Generic corporate language detector
  const corporateBeige = [
    'leverage', 'synergy', 'utilize', 'best-in-class', 'world-class',
    'cutting-edge', 'game-changing', 'revolutionary', 'disruptive',
    'paradigm shift', 'holistic approach', 'at the end of the day',
    'move the needle', 'low-hanging fruit', 'circle back', 'deep dive',
    'thought leader', 'value proposition', 'core competency', 'stakeholder alignment'
  ];
  const corpMatches = corporateBeige.filter(phrase => lower.includes(phrase));
  if (corpMatches.length > 0) {
    flags.push({
      type: 'corporate_beige',
      matches: corpMatches,
      severity: 'low',
      detail: `Contains generic corporate language: ${corpMatches.join(', ')}. These make any brand sound like every brand.`
    });
    deductions += corpMatches.length * 3;
  }

  // Check 5: On-brand/off-brand pair violations
  const pairs = voiceDoc.on_off_brand_pairs || [];
  for (const pair of pairs) {
    if (pair.off_brand && lower.includes(pair.off_brand.toLowerCase())) {
      flags.push({
        type: 'off_brand_pair',
        off_brand: pair.off_brand,
        on_brand: pair.on_brand,
        severity: 'medium',
        detail: `Uses off-brand phrasing "${pair.off_brand}" — on-brand alternative: "${pair.on_brand}".`
      });
      deductions += 7;
    }
  }

  const deterministicScore = Math.max(0, 100 - deductions);

  return {
    deterministic_score: deterministicScore,
    flags,
    deductions,
    needs_llm_tone_check: true, // always send to LLM for tone alignment
    flagged_phrase_count: flags.length
  };
}

function checkFreshness(text) {
  // Check for stale year references
  const currentYear = new Date().getFullYear();
  const yearPattern = /\b(20\d{2})\b/g;
  const years = [];
  let match;
  while ((match = yearPattern.exec(text)) !== null) {
    years.push(parseInt(match[1]));
  }

  const staleYears = years.filter(y => y < currentYear - 1);

  return {
    has_stale_references: staleYears.length > 0,
    stale_years: staleYears,
    all_years_referenced: [...new Set(years)].sort()
  };
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const mode = input.mode || 'score';

  if (mode === 'score') {
    const text = input.text || input.draft?.body || '';
    const voiceDoc = input.voice_doc || {};
    const result = scoreVoiceDeterministic(text, voiceDoc);
    result.freshness = checkFreshness(text);
    result.word_count = text.split(/\s+/).length;
    result.timestamp = new Date().toISOString();
    process.stdout.write(JSON.stringify(result));
  } else if (mode === 'batch_drift') {
    // Score multiple published pieces for weekly drift analysis
    const pieces = input.pieces || [];
    const voiceDoc = input.voice_doc || {};
    const scores = pieces.map(p => ({
      id: p.id,
      title: p.title,
      published_date: p.published_date,
      ...scoreVoiceDeterministic(p.text || p.body || '', voiceDoc),
      freshness: checkFreshness(p.text || p.body || '')
    }));

    const avgScore = scores.length > 0
      ? Math.round(scores.reduce((s, p) => s + p.deterministic_score, 0) / scores.length)
      : null;

    process.stdout.write(JSON.stringify({
      scores,
      average_deterministic_score: avgScore,
      total_pieces: scores.length,
      flagged_pieces: scores.filter(s => s.flags.length > 0).length,
      stale_pieces: scores.filter(s => s.freshness.has_stale_references).length,
      timestamp: new Date().toISOString()
    }));
  }
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

module.exports = { scoreVoiceDeterministic, checkFreshness };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
