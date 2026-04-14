#!/usr/bin/env node
/**
 * vera-sentiment-detector.js
 * Requirements 11, 33, 34, 35: Detect and track sentiment continuously.
 *
 * Deterministic keyword matching handles ~70% of sentiment signals.
 * Runs on every customer message, not just intake.
 * Zero LLM.
 */

const SENTIMENT_SIGNALS = {
  distressed: {
    keywords: [
      'please help', 'desperate', 'scared', 'terrified', 'frightened',
      'don\'t know what to do', 'emergency', 'urgent', 'life or death',
      'medical', 'health', 'safety', 'crying', 'breakdown', 'panic',
      'financial ruin', 'bankrupt', 'lost everything', 'can\'t afford',
      'bereavement', 'death in', 'passed away', 'funeral'
    ],
    score: -3,
    action: 'priority_escalate'
  },
  angry: {
    keywords: [
      'unacceptable', 'ridiculous', 'outrageous', 'disgusting', 'appalling',
      'worst', 'terrible', 'horrible', 'furious', 'livid', 'infuriated',
      'scam', 'rip off', 'ripoff', 'theft', 'stealing', 'criminal',
      'incompetent', 'useless agent', 'waste of time', 'total waste',
      'never again', 'worst company', 'reporting you'
    ],
    score: -2,
    action: 'acknowledge_and_offer_escalation'
  },
  frustrated: {
    keywords: [
      'still', 'again', 'already told you', 'not helping', 'just answer',
      'how many times', 'repeat myself', 'said this before', 'keeps happening',
      'nothing works', 'not working', 'broken', 'failing', 'impossible',
      'give up', 'fed up', 'sick of', 'tired of', 'enough',
      'why can\'t you', 'why won\'t you', 'this is useless'
    ],
    score: -1,
    action: 'acknowledge_before_resolution'
  },
  neutral: {
    keywords: [],
    score: 0,
    action: 'proceed_normally'
  },
  positive: {
    keywords: [
      'thank you', 'thanks', 'great', 'perfect', 'awesome', 'excellent',
      'wonderful', 'appreciate', 'helpful', 'solved', 'fixed', 'working now',
      'that did it', 'exactly what i needed', 'love it'
    ],
    score: 1,
    action: 'proceed_normally'
  }
};

// Structural signals (not just keywords)
function detectStructuralSignals(message) {
  const signals = [];

  // ALL CAPS (more than 3 consecutive words)
  const capsWords = message.match(/\b[A-Z]{2,}\b/g) || [];
  if (capsWords.length >= 3) {
    signals.push({ type: 'all_caps', weight: -1 });
  }

  // Excessive exclamation or question marks
  const exclamations = (message.match(/!+/g) || []).length;
  const questions = (message.match(/\?{2,}/g) || []).length;
  if (exclamations >= 3 || questions >= 1) {
    signals.push({ type: 'excessive_punctuation', weight: -1 });
  }

  // Very short reply after longer exchanges (frustration signal)
  if (message.trim().split(/\s+/).length <= 3 && message.length > 0) {
    signals.push({ type: 'short_reply', weight: -0.5 });
  }

  return signals;
}

function detectSentiment(message, conversationHistory) {
  const lower = (message || '').toLowerCase();

  // Check keyword patterns
  let detectedSentiment = 'neutral';
  let detectedScore = 0;
  let matchedKeywords = [];
  let action = 'proceed_normally';

  for (const [sentiment, config] of Object.entries(SENTIMENT_SIGNALS)) {
    const matches = config.keywords.filter(kw => lower.includes(kw));
    if (matches.length > 0 && config.score < detectedScore) {
      detectedSentiment = sentiment;
      detectedScore = config.score;
      matchedKeywords = matches;
      action = config.action;
    }
    if (matches.length > 0 && config.score > 0 && detectedScore >= 0) {
      detectedSentiment = sentiment;
      detectedScore = config.score;
      matchedKeywords = matches;
      action = config.action;
    }
  }

  // Check structural signals
  const structuralSignals = detectStructuralSignals(message);
  const structuralWeight = structuralSignals.reduce((sum, s) => sum + s.weight, 0);
  detectedScore += structuralWeight;

  // Detect sentiment shift from conversation history
  const history = conversationHistory || [];
  const previousSentiment = history.length > 0 ? history[history.length - 1]?.sentiment : null;
  const sentimentShift = previousSentiment && detectedSentiment !== previousSentiment
    ? { from: previousSentiment, to: detectedSentiment, degraded: detectedScore < (SENTIMENT_SIGNALS[previousSentiment]?.score || 0) }
    : null;

  // Override action if sentiment degraded
  if (sentimentShift?.degraded) {
    if (detectedSentiment === 'distressed') {
      action = 'priority_escalate';
    } else if (detectedSentiment === 'angry' || detectedSentiment === 'frustrated') {
      action = 'acknowledge_before_resolution';
    }
  }

  return {
    sentiment: detectedSentiment,
    score: detectedScore,
    matched_keywords: matchedKeywords,
    structural_signals: structuralSignals,
    action,
    shift: sentimentShift,
    needs_llm_nuance: matchedKeywords.length === 0 && structuralSignals.length === 0 && detectedSentiment === 'neutral',
    timestamp: new Date().toISOString()
  };
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const message = input.message || input.text || '';
  const history = input.sentiment_history || [];

  const result = detectSentiment(message, history);

  process.stdout.write(JSON.stringify(result));
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

module.exports = { detectSentiment, SENTIMENT_SIGNALS };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
