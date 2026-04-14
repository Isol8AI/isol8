# Lens — Tool Usage Guide

## Core Retrieval Stack

### Perplexity API (Structured Web Search)

Lens's primary structured-web-search engine. Runs in every research pass for discovery, through the daily monitoring sweep (academic, legal, competitive, financial news), and for any web search query across verticals.

**Not a ClawHub skill.** Called via direct `curl` from lobster `exec --shell` steps. The Perplexity `sonar` model is designed for structured web search with citations: every response has a `choices[0].message.content` plus a `citations[]` array of source URLs. This is a deterministic API — same query → same structured response shape — so every call is a deterministic step, NOT an llm-task call. The deterministic / LLM split is preserved exactly.

Canonical call shape:
```
curl -sS https://api.perplexity.ai/chat/completions \
  -H "Authorization: Bearer $PERPLEXITY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"sonar","messages":[{"role":"user","content":"<query>"}]}'
```

In lobster pipelines, curl is piped into an inline `node -e` normalizer that extracts `content`, `citations`, `high_value_urls`, and `total`. For multi-query research passes, iteration happens inside an inline `node -e` fetch loop (curl can't loop) — same Perplexity API, same deterministic character. Auth credential `PERPLEXITY_API_KEY` is set at the process environment level (not in `openclaw.json`) and is the only required env var beyond `OPENCLAW_HOOK_TOKEN`.

### agent-browser (Full-Page Retrieval + Interactive Navigation)

Full-page content retrieval and browser automation. Handles JavaScript-heavy pages, bot protection, interactive navigation — SEC EDGAR multi-step search, court document databases requiring login, GitHub advanced search, academic publisher pages. 11K+ downloads. Cleanest high-download skill per ClawHavoc analysis. The architectural fix for data voids: when a source is difficult to retrieve, agent-browser gets the actual page instead of Lens filling the gap with generated content. Used in every research pass for deep reading of high-value URLs from Perplexity citations, in monitoring sweep for tech changelog tracking, and in weekly maintenance for source accessibility checks.

### Semantic Scholar API (Academic Search + Citation Network)

200M+ academic papers. Structured metadata, abstracts, citation counts, full-text links, citation intents (supporting/contradicting/mentioning). Covers breadth beyond arXiv (CS focus) and PubMed (biomedical focus). Free API tier, no key required.

**Not a ClawHub skill.** Called via direct `curl` from lobster `exec --shell` steps — same deterministic pattern as Perplexity.

Paper search:
```
curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query=...&limit=10&fields=title,abstract,year,citationCount,authors,url,externalIds"
```

Citation network (citation intent classification):
```
curl -s "https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations?fields=title,contexts,intents,isInfluential"
```

The `intents` field covers supporting/contradicting/mentioning classification. Not as granular as dedicated citation analysis, but free and deterministic.

### deeps
Deep research orchestration for complex multi-step tasks requiring planning, decomposition, and iterative refinement. Used for research questions exceeding 5 sub-questions or 3 sequential passes.

## Vertical-Specific Skills (install per vertical)

### arxiv-search-collector (academic, tech)
Systematic literature retrieval — builds structured paper sets against research questions. Not a one-shot search but a workflow for multi-pass cross-verification across academic literature.

### agentic-paper-digest (academic, tech)
Ongoing monitoring — surfaces new arXiv and Hugging Face papers in configured areas. Feeds freshness monitoring.

### arxiv-watcher (academic, tech)
Topic-specific and author-specific arXiv monitoring. For continuous tracking over months.

### pubmed-edirect (academic, healthcare)
PubMed peer-reviewed literature. Essential for healthcare/life sciences where arXiv preprints are insufficient — PubMed papers have completed peer review, have DOIs, are the citable primary sources.

### stackunderflow (tech)
Verified community knowledge from Stack Overflow. Community signal tier only — never cited as primary source.

### depo-bot (legal)
Structured reports from deposition transcripts and primary legal documents. Extracts specific claims, rulings, precedents.

### social-intelligence (competitive, market)
Social media research across Twitter, Instagram, Reddit. 1.5B+ posts indexed. Community signal tier — intelligence about perception and experience, never elevated to primary citation status.

## Direct API Integrations

### SEC EDGAR (efts.sec.gov)
Primary source for all financial research. Public API, no key required. Query by form type, date range, company. Always route financial queries here first. agent-browser for interactive EDGAR interface.

## Storage and Delivery

### fast-io
Key structure:
- `lens-config/verticals` — source hierarchies per vertical
- `lens-config/confidence-thresholds` — configurable Verified/Supported thresholds
- `lens-config/freshness-thresholds/{{vertical}}` — staleness thresholds per vertical
- `lens-config/monitoring` — topics to watch per vertical
- `lens-state/source-overrides` — user reclassifications
- `lens-state/historical-research` — past research for confidence estimation
- `lens-state/degradation-dismissals` — suppressed alert types
- `lens-state/user-format-preference` — output style preference
- `lens-research/{{timestamp}}/{{question}}` — complete research deliverables with audit trail
- `lens-monitoring/previous-state` — baseline for change detection
- `audit/{{timestamp}}/{{action}}` — 12-month audit trail

### gog (Google Workspace)
Drive: research archive — every deliverable, source appendix, and version persists as human-accessible audit trail. Sheets: confidence scoring tracker — Verified/Supported/Single-source/Contested/Gap per active research project. Gmail: research request intake and deliverable sharing.

### slack
Channel: `#lens-research` — research plan approval, findings delivery, monitoring alerts, confidence degradation notices, gap alerts.

## Click-to-Connect Integrations

Lens's core retrieval stack (Perplexity API, Semantic Scholar API, agent-browser) requires no user-side service connections — Perplexity needs only a `PERPLEXITY_API_KEY` env var, Semantic Scholar is free with no key, and agent-browser is a built-in skill.

Vertical-specific skills are click-to-connect toggles in the Isol8 settings UI. Lens only mentions them when the user asks for something that benefits from them:

### Academic vertical — click-to-connect (enable per need)
arxiv-search-collector, agentic-paper-digest, arxiv-watcher, pubmed-edirect. When the user configures academic research and wants systematic literature retrieval or ongoing paper monitoring, Lens says: "To enable systematic arXiv/PubMed monitoring, connect the relevant academic skills in settings. Supported: arxiv-search-collector, agentic-paper-digest, arxiv-watcher, pubmed-edirect."

### Tech vertical — click-to-connect (optional)
stackunderflow. When the user wants community signal from Stack Overflow, Lens says: "To include Stack Overflow community signal, connect stackunderflow in settings."

### Legal vertical — click-to-connect (optional)
depo-bot. When the user needs structured deposition/legal document analysis, Lens says: "To analyze deposition transcripts and legal documents, connect depo-bot in settings."

### Competitive/Market vertical — click-to-connect (optional)
social-intelligence. When the user wants social media perception data, Lens says: "To include social media intelligence, connect social-intelligence in settings."

## Handling Missing Integrations

If a user asks Lens to perform an action that requires a tool or service they haven't connected yet, tell them exactly which service they need to connect, list the supported options, and tell them to connect it in their settings. Do not attempt the action without the connection. Do not ask them to connect during onboarding — only when they need it.

Examples:
- No academic skills connected, user asks for systematic literature review → "To run systematic literature retrieval, connect arxiv-search-collector in settings."
- No social-intelligence connected, user asks for Reddit sentiment → "To include social media intelligence, connect social-intelligence in settings."
- No vertical-specific skills needed → Lens operates fully on Perplexity + Semantic Scholar + agent-browser with no additional connections.

## API Error Handling

Every pipeline step that calls an external API checks the response and branches on error conditions:

- **429 rate limit** → retry up to 3x with exponential backoff (60s / 120s / 300s, per cron config), then surface to the user: "Research API is rate-limiting — retrying automatically. If this keeps happening, check your Perplexity plan usage."
- **401 / 403 auth expired** → surface immediately: "Your Perplexity API key is invalid or expired. Update `PERPLEXITY_API_KEY` in your environment to restore research and monitoring."
- **5xx server errors** → retry per cron retry config, then surface with the underlying error.

## Security

- `skill-vetter` — run before production, especially on any search/scraping skill handling retrieved content
- `sona-security-audit` — runtime monitoring; research data (competitive intelligence, financial filings, proprietary analysis) is sensitive professional information
- Do NOT install: `private-web-search-searchxng` (active VirusTotal flag), any financial data skill without verifiable primary source connection, any skill under 30 days old without VirusTotal clearance

## Denied Tools (defense-in-depth)

The following tools are blocked in `openclaw.json` tools.deny and will not install even if referenced:
- `foxreach-io`
- `campaign-orchestrator`
- `phone-caller`
- `linkedin-automation`
- `private-web-search-searchxng` — active VirusTotal flag
