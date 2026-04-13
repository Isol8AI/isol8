#!/usr/bin/env node
/**
 * lens-synthesis-formatter.js
 * Requirements 15, 23-27, 30: Format synthesis with inline tiers, vertical adaptation, appendix.
 *
 * Deterministic formatting. Narrative synthesis by llm-task in pipeline.
 */

const VERTICAL_FORMATS = {
  financial: {
    data_format: 'table',
    citation_style: 'filing_reference',
    number_presentation: 'traceable_to_filing'
  },
  technology: {
    data_format: 'separated_sections',
    citation_style: 'url_with_date',
    sections: ['verified_specs', 'community_experience']
  },
  academic: {
    data_format: 'structured_citations',
    citation_style: 'doi_with_citation_context',
    number_presentation: 'standard_academic'
  },
  legal: {
    data_format: 'structured_sections',
    citation_style: 'case_number_and_section',
    sections: ['primary_rulings', 'secondary_analysis']
  },
  competitive: {
    data_format: 'labeled_by_vertical',
    citation_style: 'mixed',
    sections: ['financial_filings', 'technical_activity', 'market_positioning', 'community_signal']
  }
};

function formatSynthesis(trackedClaims, vertical, userFormatPreference) {
  const format = userFormatPreference || VERTICAL_FORMATS[vertical] || VERTICAL_FORMATS.technology;

  // Confidence summary
  const tiers = { verified: 0, supported: 0, single_source: 0, contested: 0, gap: 0 };
  trackedClaims.forEach(c => tiers[c.confidence_tier]++);
  const total = trackedClaims.length;
  const verificationRate = total > 0 ? Math.round(((tiers.verified + tiers.supported) / total) * 100) : 0;

  const confidenceSummary = {
    text: `CONFIDENCE SUMMARY\nVerified: ${tiers.verified} | Supported: ${tiers.supported} | Single-source: ${tiers.single_source} | Contested: ${tiers.contested} | Gap: ${tiers.gap}\nOverall: ${total} findings, ${verificationRate}% at Verified or Supported confidence.`,
    tiers,
    total,
    verification_rate: verificationRate
  };

  // Format each claim with inline tier
  const formattedClaims = trackedClaims
    .filter(c => c.confidence_tier !== 'gap')
    .map(c => {
      const verticalLabel = c.vertical ? ` — ${c.vertical.charAt(0).toUpperCase() + c.vertical.slice(1)}` : '';
      const tierTag = `[${c.confidence_tier.toUpperCase()}${verticalLabel}]`;

      const primarySource = c.sources?.[0];
      const citation = primarySource
        ? formatCitation(primarySource, format.citation_style)
        : 'Source: [retrieval pending]';

      return {
        formatted: `${tierTag} ${c.claim_text}\n${citation}`,
        tier: c.confidence_tier,
        vertical: c.vertical,
        claim_id: c.claim_id,
        amplification_note: c.amplification_note || null,
        contradiction_detail: c.contradictions || null
      };
    });

  // Gap section — "What We Could Not Verify"
  const gaps = trackedClaims
    .filter(c => c.confidence_tier === 'gap')
    .map(c => ({
      question: c.claim_text,
      searched: c.sources_searched || [],
      tiers_consulted: c.tiers_consulted || [],
      reason: c.gap_reason || 'No sources found in the configured vertical hierarchy.'
    }));

  // Source appendix
  const allSources = [];
  const seen = new Set();
  for (const claim of trackedClaims) {
    for (const source of (claim.sources || [])) {
      if (seen.has(source.url)) continue;
      seen.add(source.url);
      allSources.push({
        url: source.url,
        title: source.title || null,
        author: source.author || null,
        publication: source.publication || null,
        date: source.date || null,
        doi: source.doi || null,
        tier: source.tier,
        role: source.role || 'corroboration',
        vertical: source.vertical || null
      });
    }
  }

  return {
    confidence_summary: confidenceSummary,
    formatted_claims: formattedClaims,
    gap_section: {
      title: 'WHAT WE COULD NOT VERIFY',
      gaps,
      count: gaps.length
    },
    source_appendix: {
      title: 'SOURCE APPENDIX',
      sources: allSources,
      total: allSources.length,
      by_tier: {
        primary: allSources.filter(s => s.tier === 'primary').length,
        secondary: allSources.filter(s => s.tier === 'secondary').length,
        community: allSources.filter(s => s.tier === 'community_signal').length
      }
    },
    format_applied: format,
    vertical,
    timestamp: new Date().toISOString()
  };
}

function formatCitation(source, style) {
  const parts = [];
  if (source.author) parts.push(source.author);
  if (source.title) parts.push(`"${source.title}"`);
  if (source.publication) parts.push(source.publication);
  if (source.date) parts.push(source.date);
  if (source.doi) parts.push(`DOI: ${source.doi}`);
  if (source.url) parts.push(source.url);

  return `Source: ${parts.join(', ')}`;
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const result = formatSynthesis(
    input.tracked_claims || [],
    input.vertical || 'technology',
    input.user_format_preference || null
  );

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

module.exports = { formatSynthesis };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
