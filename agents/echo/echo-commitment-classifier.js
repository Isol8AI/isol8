#!/usr/bin/env node
/**
 * echo-commitment-classifier.js
 * Requirements 4, 18: Classify commitments vs tentative proposals. Adaptive thresholds.
 *
 * Deterministic keyword matching (~60%). LLM for ambiguous in pipeline (~40%).
 */

const DEFAULT_DEFINITIVE = [
  "i'll", "i will", "i'm going to", "we're going with", "we will",
  "i'll have this", "let me handle", "i'll take care of",
  "i'll set up", "i'll send", "i'll follow up", "i'll schedule",
  "let's do it", "we're doing", "decided to", "agreed to",
  "by friday", "by eow", "by end of week", "by end of day",
  "by monday", "by next week", "i'll get it done"
];

const DEFAULT_TENTATIVE = [
  "we should probably", "we should", "might be worth",
  "let's think about", "worth exploring", "could look into",
  "maybe we should", "let me think about", "i'll consider",
  "that's interesting", "worth considering", "food for thought",
  "not sure yet", "need to think", "we could potentially",
  "something to explore", "let's revisit", "tbd", "to be determined"
];

function classifyCommitment(text, speaker, customThresholds) {
  const lower = (text || '').toLowerCase();
  const definitivePatterns = [...DEFAULT_DEFINITIVE, ...(customThresholds?.definitive || [])];
  const tentativePatterns = [...DEFAULT_TENTATIVE, ...(customThresholds?.tentative || [])];

  // Check definitive first
  const definitiveMatch = definitivePatterns.find(p => lower.includes(p));
  if (definitiveMatch) {
    // Check for negation: "I won't", "I don't think I'll"
    const negations = ["won't", "don't think", "not going to", "can't", "unable to"];
    const isNegated = negations.some(n => lower.includes(n));

    if (isNegated) {
      return {
        classification: 'declined',
        confidence: 'high',
        matched: definitiveMatch,
        negated_by: negations.find(n => lower.includes(n)),
        needs_llm: false
      };
    }

    return {
      classification: 'definitive',
      confidence: 'high',
      matched: definitiveMatch,
      needs_llm: false
    };
  }

  // Check tentative
  const tentativeMatch = tentativePatterns.find(p => lower.includes(p));
  if (tentativeMatch) {
    return {
      classification: 'tentative',
      confidence: 'high',
      matched: tentativeMatch,
      display_as: 'FOR FOLLOW-UP / TO BE CONFIRMED',
      quote_hedged_language: true,
      needs_llm: false
    };
  }

  // Ambiguous — contains a task-like structure but no clear commitment language
  const hasTaskStructure = /\b(need to|have to|should|going to|plan to|want to)\b/i.test(text);
  if (hasTaskStructure) {
    return {
      classification: 'ambiguous',
      confidence: 'low',
      needs_llm: true,
      llm_context: `Classify this statement as definitive commitment, tentative proposal, or not an action item. The speaker is ${speaker}. Statement: "${text}". Consider: did the speaker personally commit to doing something specific with a timeline, or is this a general observation about what needs to happen?`
    };
  }

  return {
    classification: 'not_action_item',
    confidence: 'medium',
    needs_llm: false
  };
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const statements = input.statements || [];
  const customThresholds = input.custom_thresholds || {};

  const classified = statements.map(s => ({
    segment_id: s.id,
    speaker: s.speaker_name || s.speaker_label,
    text: s.text,
    timestamp: s.start_time,
    ...classifyCommitment(s.text, s.speaker_name || s.speaker_label, customThresholds)
  }));

  const result = {
    classified,
    definitive: classified.filter(c => c.classification === 'definitive').length,
    tentative: classified.filter(c => c.classification === 'tentative').length,
    ambiguous: classified.filter(c => c.classification === 'ambiguous').length,
    needs_llm_count: classified.filter(c => c.needs_llm).length,
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

module.exports = { classifyCommitment, DEFAULT_DEFINITIVE, DEFAULT_TENTATIVE };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
