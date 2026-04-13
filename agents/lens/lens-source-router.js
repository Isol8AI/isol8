#!/usr/bin/env node
/**
 * lens-source-router.js
 * Requirements 2, 4, 8, 19: Route sub-questions to source tiers per vertical hierarchy.
 *
 * Deterministic lookup. Agent loop escape for ambiguous routing and user reclassifications.
 */

// Default tool mapping for source types
const SOURCE_TOOLS = {
  sec_edgar: { tool: 'agent-browser', endpoint: 'https://efts.sec.gov/LATEST/search-index', type: 'direct_api' },
  bloomberg: { tool: 'agent-browser', type: 'scrape' },
  reuters: { tool: 'perplexity', type: 'search' },
  company_ir_pages: { tool: 'agent-browser', type: 'scrape' },
  fed_publications: { tool: 'agent-browser', type: 'scrape' },
  marketwatch: { tool: 'perplexity', type: 'search' },
  yahoo_finance: { tool: 'perplexity', type: 'search' },
  arxiv: { tool: 'arxiv-search-collector', type: 'skill' },
  pubmed: { tool: 'pubmed-edirect', type: 'skill' },
  semantic_scholar: { tool: 'semantic-scholar-api', endpoint: 'https://api.semanticscholar.org/graph/v1', type: 'direct_api' },
  github: { tool: 'agent-browser', type: 'scrape' },
  official_docs: { tool: 'agent-browser', type: 'scrape' },
  hackernews: { tool: 'perplexity', type: 'search', domain_filter: 'news.ycombinator.com' },
  stackoverflow: { tool: 'stackunderflow', type: 'skill' },
  reddit: { tool: 'social-intelligence', type: 'skill' },
  court_documents: { tool: 'depo-bot', type: 'skill' },
  statutory_databases: { tool: 'agent-browser', type: 'scrape' },
  federal_register: { tool: 'agent-browser', endpoint: 'https://www.federalregister.gov/api/v1', type: 'direct_api' },
  semantic_scholar_citations: { tool: 'semantic-scholar-api', endpoint: 'https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations', type: 'direct_api' }
};

function routeSubQuestion(subQuestion, verticalConfig, userOverrides) {
  const vertical = subQuestion.vertical;
  const hierarchy = verticalConfig[vertical];

  if (!hierarchy) {
    return {
      routed: false,
      needs_agent_loop: true,
      reason: `No hierarchy configured for vertical "${vertical}". The agent loop should either construct a custom hierarchy or ask the user to define one.`,
      sub_question: subQuestion.question
    };
  }

  // Apply user overrides — sources the user has reclassified
  const overrides = userOverrides || {};
  const effectiveHierarchy = {
    primary: [...hierarchy.primary],
    secondary: [...hierarchy.secondary],
    community_signal: [...(hierarchy.community_signal || [])]
  };

  for (const [source, newTier] of Object.entries(overrides)) {
    // Remove from current tier
    effectiveHierarchy.primary = effectiveHierarchy.primary.filter(s => s !== source);
    effectiveHierarchy.secondary = effectiveHierarchy.secondary.filter(s => s !== source);
    effectiveHierarchy.community_signal = effectiveHierarchy.community_signal.filter(s => s !== source);
    // Add to new tier
    if (effectiveHierarchy[newTier]) effectiveHierarchy[newTier].push(source);
  }

  // Determine target tier based on sub-question type
  const targetTier = subQuestion.target_tier || 'primary';
  const sources = effectiveHierarchy[targetTier] || effectiveHierarchy.primary;

  // Map sources to retrieval tools
  const retrievalPlan = sources.map(source => {
    const toolMapping = SOURCE_TOOLS[source.toLowerCase().replace(/[\s\/]+/g, '_')];
    return {
      source,
      tier: targetTier,
      tool: toolMapping?.tool || 'perplexity',
      type: toolMapping?.type || 'search',
      endpoint: toolMapping?.endpoint || null,
      domain_filter: toolMapping?.domain_filter || null
    };
  });

  // Check for ambiguous routing — sub-question spans multiple tiers
  const spansMultipleTiers = subQuestion.spans_tiers && subQuestion.spans_tiers.length > 1;

  return {
    routed: true,
    sub_question: subQuestion.question,
    vertical,
    target_tier: targetTier,
    retrieval_plan: retrievalPlan,
    needs_agent_loop: spansMultipleTiers,
    agent_loop_reason: spansMultipleTiers
      ? `Sub-question spans ${subQuestion.spans_tiers.join(' and ')} tiers. Agent loop should determine primary routing and whether both tiers need querying.`
      : null,
    overrides_applied: Object.keys(overrides).length > 0
  };
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const subQuestions = input.sub_questions || [];
  const verticalConfig = input.vertical_config || {};
  const userOverrides = input.user_overrides || {};

  const routed = subQuestions.map(sq => routeSubQuestion(sq, verticalConfig, userOverrides));

  const result = {
    routed: routed.filter(r => r.routed && !r.needs_agent_loop),
    needs_agent_loop: routed.filter(r => r.needs_agent_loop),
    unroutable: routed.filter(r => !r.routed),
    total: subQuestions.length,
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

module.exports = { routeSubQuestion, SOURCE_TOOLS };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
