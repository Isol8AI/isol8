#!/usr/bin/env node
/**
 * lens-cross-checker.js
 * Requirements 21, 29: Cross-check secondary against primary + cross-vertical contradictions.
 *
 * Deterministic for numerical. Agent loop escape for semantic contradictions.
 */

function crossCheckSecondaryPrimary(findings) {
  const discrepancies = [];

  for (const finding of findings) {
    if (!finding.secondary_source || !finding.primary_source) continue;

    const secondary = finding.secondary_source;
    const primary = finding.primary_source;

    // Numerical comparison
    if (secondary.value !== undefined && primary.value !== undefined) {
      const deviation = Math.abs(secondary.value - primary.value) / Math.max(Math.abs(primary.value), 1);
      if (deviation > 0.01) {
        discrepancies.push({
          type: 'numerical_discrepancy',
          claim: finding.claim,
          secondary: { source: secondary.url, value: secondary.value },
          primary: { source: primary.url, value: primary.value },
          deviation_pct: Math.round(deviation * 100),
          recommendation: `Secondary states ${secondary.value}. Primary shows ${primary.value}. Use primary figure.`,
          needs_agent_loop: false
        });
      }
    }

    // Date/fact discrepancy
    if (secondary.date_claim && primary.date_claim && secondary.date_claim !== primary.date_claim) {
      discrepancies.push({
        type: 'date_discrepancy',
        claim: finding.claim,
        secondary: { source: secondary.url, date: secondary.date_claim },
        primary: { source: primary.url, date: primary.date_claim },
        recommendation: `Secondary reports ${secondary.date_claim}. Primary shows ${primary.date_claim}. Use primary.`,
        needs_agent_loop: false
      });
    }

    // Semantic discrepancy — needs agent loop
    if (secondary.text_claim && primary.text_claim) {
      discrepancies.push({
        type: 'semantic_check_needed',
        claim: finding.claim,
        secondary: { source: secondary.url, text: secondary.text_claim.substring(0, 200) },
        primary: { source: primary.url, text: primary.text_claim.substring(0, 200) },
        needs_agent_loop: true,
        agent_loop_context: 'Compare secondary interpretation against primary text. Determine if the secondary accurately represents the primary or introduces distortion.'
      });
    }
  }

  return discrepancies;
}

function crossCheckVerticals(findings) {
  const contradictions = [];

  // Group findings by entity (company, topic, etc.)
  const byEntity = {};
  for (const f of findings) {
    const entity = f.entity || f.company || f.topic;
    if (!entity) continue;
    if (!byEntity[entity]) byEntity[entity] = [];
    byEntity[entity].push(f);
  }

  for (const [entity, entityFindings] of Object.entries(byEntity)) {
    // Compare findings from different verticals about the same entity
    for (let i = 0; i < entityFindings.length; i++) {
      for (let j = i + 1; j < entityFindings.length; j++) {
        const a = entityFindings[i];
        const b = entityFindings[j];
        if (a.vertical === b.vertical) continue;

        // Numerical contradiction across verticals
        if (a.extracted_value !== undefined && b.extracted_value !== undefined &&
            a.claim_type === b.claim_type) {
          const deviation = Math.abs(a.extracted_value - b.extracted_value) / Math.max(Math.abs(a.extracted_value), 1);
          if (deviation > 0.10) {
            contradictions.push({
              type: 'cross_vertical_numerical',
              entity,
              vertical_a: a.vertical,
              vertical_b: b.vertical,
              source_a: { url: a.source_url, value: a.extracted_value },
              source_b: { url: b.source_url, value: b.extracted_value },
              description: `${a.vertical} source states ${a.extracted_value}, ${b.vertical} source states ${b.extracted_value}.`,
              needs_agent_loop: false
            });
          }
        }

        // Semantic contradiction across verticals — always needs agent loop
        if (a.claim_text && b.claim_text && a.claim_type === b.claim_type) {
          contradictions.push({
            type: 'cross_vertical_semantic',
            entity,
            vertical_a: a.vertical,
            vertical_b: b.vertical,
            claim_a: a.claim_text.substring(0, 200),
            claim_b: b.claim_text.substring(0, 200),
            needs_agent_loop: true,
            agent_loop_context: `${a.vertical} source says one thing, ${b.vertical} source says another about ${entity}. Determine if this is a genuine contradiction or a difference in framing.`
          });
        }
      }
    }
  }

  return contradictions;
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const mode = input.mode || 'both';
  const result = { timestamp: new Date().toISOString() };

  if (mode === 'secondary_primary' || mode === 'both') {
    result.secondary_primary = crossCheckSecondaryPrimary(input.findings || []);
  }
  if (mode === 'cross_vertical' || mode === 'both') {
    result.cross_vertical = crossCheckVerticals(input.findings || []);
  }

  result.total_discrepancies = (result.secondary_primary || []).length + (result.cross_vertical || []).length;
  result.needs_agent_loop = [...(result.secondary_primary || []), ...(result.cross_vertical || [])].some(d => d.needs_agent_loop);

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

module.exports = { crossCheckSecondaryPrimary, crossCheckVerticals };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
