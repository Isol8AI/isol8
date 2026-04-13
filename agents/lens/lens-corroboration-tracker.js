#!/usr/bin/env node
/**
 * lens-corroboration-tracker.js
 * Requirements 12-16: Track sources per claim, detect citation amplification, assign tiers.
 *
 * Deterministic counting, chain tracing, tier assignment. Zero LLM.
 */

function trackCorroboration(claims, thresholds) {
  const verifiedMin = thresholds?.verified_min_independent_primaries || 3;
  const supportedMinPrimary = thresholds?.supported_min_primary || 1;
  const supportedMinSecondary = thresholds?.supported_min_secondary || 1;

  return claims.map(claim => {
    const sources = claim.sources || [];

    // Step 1: Trace citation chains — detect amplification
    const originMap = {};
    const independent = [];
    const amplified = [];

    for (const source of sources) {
      const originKey = findOrigin(source, sources);

      if (originKey && originKey !== source.url) {
        // This source references another tracked source — amplification
        if (!originMap[originKey]) originMap[originKey] = [];
        originMap[originKey].push(source);
        amplified.push({ source: source.url, traces_to: originKey });
      } else {
        // Independent source
        independent.push(source);
      }
    }

    const independentPrimaries = independent.filter(s => s.tier === 'primary').length;
    const independentSecondaries = independent.filter(s => s.tier === 'secondary').length;
    const independentTotal = independent.length;

    // Step 2: Detect contradictions
    const contradictions = detectContradictions(independent);

    // Step 3: Assign confidence tier
    let tier;
    if (contradictions.length > 0) {
      tier = 'contested';
    } else if (independentTotal === 0) {
      tier = 'gap';
    } else if (independentPrimaries >= verifiedMin) {
      tier = 'verified';
    } else if (independentPrimaries >= supportedMinPrimary && independentSecondaries >= supportedMinSecondary) {
      tier = 'supported';
    } else if (independentPrimaries >= 2 || independentSecondaries >= 2) {
      tier = 'supported';
    } else {
      tier = 'single_source';
    }

    return {
      claim_id: claim.id,
      claim_text: claim.text,
      vertical: claim.vertical,
      confidence_tier: tier,
      evidence: {
        total_sources: sources.length,
        independent_sources: independentTotal,
        independent_primaries: independentPrimaries,
        independent_secondaries: independentSecondaries,
        community_signal: independent.filter(s => s.tier === 'community_signal').length,
        amplified_sources: amplified.length,
        amplification_chains: Object.keys(originMap).length > 0 ? originMap : null
      },
      contradictions: contradictions.length > 0 ? contradictions : null,
      amplification_note: amplified.length > 0
        ? `${sources.length} sources cite this claim, but ${amplified.length} trace to the same origin(s). Confidence reflects ${independentTotal} independent source(s).`
        : null,
      sources: independent.map(s => ({
        url: s.url,
        title: s.title,
        author: s.author || null,
        publication: s.publication || null,
        date: s.date,
        tier: s.tier,
        doi: s.doi || null
      }))
    };
  });
}

function findOrigin(source, allSources) {
  // Check if this source explicitly cites another tracked source
  const refUrls = source.references || [];
  const refDois = source.cited_dois || [];

  for (const other of allSources) {
    if (other.url === source.url) continue;
    // URL match
    if (refUrls.some(ref => ref.includes(other.url) || other.url.includes(ref))) return other.url;
    // DOI match
    if (other.doi && refDois.includes(other.doi)) return other.url;
    // Author + title match (fuzzy)
    if (other.author && source.references_text) {
      const authorLast = other.author.split(' ').pop()?.toLowerCase();
      if (authorLast && source.references_text.toLowerCase().includes(authorLast)) {
        // Check title fragment too
        const titleFragment = (other.title || '').toLowerCase().split(' ').slice(0, 4).join(' ');
        if (titleFragment.length > 10 && source.references_text.toLowerCase().includes(titleFragment)) {
          return other.url;
        }
      }
    }
  }

  // Uncertain chain — might need agent loop
  if (source.possible_origin) return source.possible_origin;

  return null;
}

function detectContradictions(sources) {
  const contradictions = [];

  for (let i = 0; i < sources.length; i++) {
    for (let j = i + 1; j < sources.length; j++) {
      const a = sources[i];
      const b = sources[j];

      // Numerical contradiction
      if (a.extracted_value !== undefined && b.extracted_value !== undefined) {
        const deviation = Math.abs(a.extracted_value - b.extracted_value) / Math.max(Math.abs(a.extracted_value), 1);
        if (deviation > 0.15) {
          contradictions.push({
            type: 'numerical',
            source_a: { url: a.url, value: a.extracted_value },
            source_b: { url: b.url, value: b.extracted_value },
            deviation_pct: Math.round(deviation * 100),
            description: `Source A states ${a.extracted_value}, Source B states ${b.extracted_value} (${Math.round(deviation * 100)}% difference).`
          });
        }
      }

      // Semantic contradiction flagged by retrieval
      if (a.contradicts && a.contradicts.includes(b.url)) {
        contradictions.push({
          type: 'semantic',
          source_a: { url: a.url },
          source_b: { url: b.url },
          description: 'Sources make contradicting claims. Needs agent loop for semantic assessment.',
          needs_agent_loop: true
        });
      }
    }
  }

  return contradictions;
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const claims = input.claims || [];
  const thresholds = input.confidence_thresholds || {};
  const tracked = trackCorroboration(claims, thresholds);

  // Summary
  const tiers = { verified: 0, supported: 0, single_source: 0, contested: 0, gap: 0 };
  tracked.forEach(c => tiers[c.confidence_tier]++);

  const result = {
    claims: tracked,
    confidence_summary: tiers,
    total_claims: tracked.length,
    verification_rate: tracked.length > 0
      ? Math.round(((tiers.verified + tiers.supported) / tracked.length) * 100)
      : 0,
    has_gaps: tiers.gap > 0,
    has_contested: tiers.contested > 0,
    amplification_detected: tracked.some(c => c.amplification_note),
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

module.exports = { trackCorroboration, findOrigin, detectContradictions };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
