#!/usr/bin/env node
/**
 * vera-intake-classifier.js
 * Requirements 9, 27, 50: Classify into four categories + detect human requests and compliance triggers.
 *
 * Deterministic keyword matching handles ~70% of classifications.
 * Ambiguous messages flagged for llm-task.
 * Zero LLM for classified messages.
 */

// --- Requirement 27: Non-negotiable human request patterns ---
const HUMAN_REQUEST_PATTERNS = [
  'talk to a person', 'speak to someone', 'speak to a person',
  'talk to a human', 'speak to a human', 'real person',
  'human agent', 'real agent', 'live agent', 'live person',
  'can i call', 'let me call', 'phone number',
  'stop sending automated', 'stop the bot', 'not a bot',
  'representative', 'supervisor', 'manager please',
  'i want a human', 'i need a human', 'get me a person',
  'transfer me', 'connect me to', 'put me through'
];

// --- Requirement 50: Legal/compliance triggers ---
const COMPLIANCE_TRIGGERS = [
  'lawyer', 'attorney', 'sue', 'lawsuit', 'legal action',
  'discrimination', 'harass', 'hipaa', 'gdpr', 'privacy violation',
  'regulatory', 'complaint to', 'report you', 'consumer protection',
  'class action', 'breach of contract', 'negligence', 'fraud',
  'ftc', 'bbb', 'better business bureau', 'attorney general',
  'data breach', 'identity theft', 'unauthorized charge'
];

// --- Distress signals (urgent escalation) ---
const DISTRESS_PATTERNS = [
  'please help me', 'desperate', 'scared', 'terrified',
  'don\'t know what to do', 'emergency', 'urgent',
  'life or death', 'medical', 'health issue', 'safety concern',
  'i\'m crying', 'breakdown', 'can\'t take this anymore',
  'financial ruin', 'going bankrupt', 'lost everything'
];

// --- Routine resolution patterns ---
const ROUTINE_PATTERNS = {
  order_status: ['where is my order', 'order status', 'track my order', 'tracking number',
                 'when will it arrive', 'shipping status', 'delivery date', 'has it shipped',
                 'order update', 'where\'s my package'],
  refund: ['refund', 'money back', 'get my money', 'charge back', 'want a refund',
           'return and refund', 'cancel and refund', 'overcharged'],
  returns: ['return', 'send it back', 'return label', 'return policy', 'exchange',
            'swap', 'wrong item', 'damaged item', 'defective'],
  password: ['password reset', 'forgot password', 'can\'t log in', 'locked out',
             'reset my password', 'login issue', 'access my account'],
  account: ['update my email', 'change my address', 'update account', 'change my name',
            'update payment', 'change subscription', 'cancel subscription',
            'upgrade', 'downgrade', 'billing'],
  faq: ['how do i', 'how does', 'what is your', 'do you have', 'can i',
        'is it possible', 'tell me about', 'information about', 'help with']
};

function classifyMessage(message) {
  const lower = (message || '').toLowerCase().trim();

  // Priority 1: Human request — non-negotiable, immediate
  for (const pattern of HUMAN_REQUEST_PATTERNS) {
    if (lower.includes(pattern)) {
      return {
        classified: true,
        needs_llm: false,
        category: 'needs_human',
        subcategory: 'explicit_request',
        matched: pattern,
        priority: 'immediate'
      };
    }
  }

  // Priority 2: Compliance/legal triggers — urgent escalation
  for (const trigger of COMPLIANCE_TRIGGERS) {
    if (lower.includes(trigger)) {
      return {
        classified: true,
        needs_llm: false,
        category: 'urgent_escalation',
        subcategory: 'compliance_legal',
        matched: trigger,
        priority: 'urgent',
        compliance_flag: true
      };
    }
  }

  // Priority 3: Distress signals — urgent escalation
  for (const pattern of DISTRESS_PATTERNS) {
    if (lower.includes(pattern)) {
      return {
        classified: true,
        needs_llm: false,
        category: 'urgent_escalation',
        subcategory: 'distress',
        matched: pattern,
        priority: 'urgent'
      };
    }
  }

  // Priority 4: Routine resolution patterns
  for (const [type, patterns] of Object.entries(ROUTINE_PATTERNS)) {
    for (const pattern of patterns) {
      if (lower.includes(pattern)) {
        return {
          classified: true,
          needs_llm: false,
          category: 'routine_resolution',
          subcategory: type,
          matched: pattern,
          priority: 'normal'
        };
      }
    }
  }

  // Not classified — needs LLM
  return {
    classified: false,
    needs_llm: true,
    message_preview: lower.substring(0, 200),
    priority: 'normal'
  };
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const message = input.message || input.text || input.body || '';
  const result = classifyMessage(message);
  result.timestamp = new Date().toISOString();

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

module.exports = { classifyMessage, HUMAN_REQUEST_PATTERNS, COMPLIANCE_TRIGGERS, DISTRESS_PATTERNS };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
