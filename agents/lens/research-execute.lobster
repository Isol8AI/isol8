name: research-execute
# Requirements 6-30: Full research execution from request to deliverable.
# Triggered per research request.
# LLM calls: 3-8 (decomposition, query refinements, semantic cross-checks, synthesis narrative)

args:
  research_question:
    required: true
  vertical:
    default: ""
  stakes:
    default: "standard"  # casual, standard, high_stakes

steps:
  # Step 1: Load vertical configuration
  - id: load-verticals
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "lens-config/verticals"}'

  # Step 2: Load confidence and freshness thresholds
  - id: load-thresholds
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "lens-config/confidence-thresholds"}'

  - id: load-freshness
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "lens-config/freshness-thresholds"}'

  # Step 3: Load user overrides (source reclassifications)
  - id: load-overrides
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "lens-state/source-overrides"}'

  # Step 4: Query decomposition — LLM CALL (Req 6)
  - id: decompose
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Decompose this research question into sub-questions. For each, identify: the specific question, which vertical it belongs to, which source tier to target first (primary/secondary/community), and whether it spans multiple tiers. Be thorough but not redundant — every sub-question should be independently answerable.",
        "thinking": "low",
        "input": {
          "question": "{{research_question}}",
          "vertical": "{{vertical}}",
          "available_verticals": $load-verticals.json
        },
        "schema": {
          "type": "object",
          "properties": {
            "sub_questions": {"type": "array", "items": {
              "type": "object",
              "properties": {
                "id": {"type": "string"},
                "question": {"type": "string"},
                "vertical": {"type": "string"},
                "target_tier": {"type": "string"},
                "spans_tiers": {"type": "array", "items": {"type": "string"}}
              }
            }},
            "research_scope": {"type": "string"}
          },
          "required": ["sub_questions"]
        }
      }'

  # Step 5: Route sub-questions to sources (Req 8)
  - id: route
    command: >
      exec --json --shell 'node scripts/lens-source-router.js'
    stdin: '{"sub_questions": $decompose.json.sub_questions, "vertical_config": $load-verticals.json, "user_overrides": $load-overrides.json}'

  # Step 6: Estimate confidence per sub-question (Req 9)
  - id: estimate
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "lens-state/historical-research"}'
      | exec --json --shell 'node scripts/lens-confidence-estimator.js'

  # Step 7: Present plan to user — TIER 2 GATE (Req 7)
  - id: present-plan
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#lens-research",
        "text": "🔍 RESEARCH PLAN — {{research_question}}\n\nSub-questions:\n$decompose.json.sub_questions\n\n⚠️ Thin areas: $estimate.json.thin_areas\n\nStakes: {{stakes}} (${stakes == \"casual\" ? \"2 passes\" : stakes == \"high_stakes\" ? \"5 passes\" : \"3 passes\"})\n\n[Approve Plan] [Modify] [Cancel]"
      }'

  - id: await-plan-approval
    command: >
      openclaw.invoke --tool lobster --action await-approval --args-json '{
        "prompt": "Waiting for user to approve research plan",
        "timeout_hours": 24
      }'

  # Step 8: Multi-pass research loop (Req 10-11)
  # Pass 1 — Primary discovery via Perplexity + Semantic Scholar
  - id: pass-1-search
    command: >
      exec --json --shell 'node -e "const https=require(\"https\");const input=JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\",\"utf8\"));const queries=input.queries||[];const results=[];let done=0;if(!queries.length){process.stdout.write(JSON.stringify({results:[],high_value_urls:[],total:0}));return;}queries.forEach((q,i)=>{const body=JSON.stringify({model:\"sonar\",messages:[{role:\"user\",content:typeof q===\"string\"?q:q.query||q.question||JSON.stringify(q)}]});const opts={hostname:\"api.perplexity.ai\",path:\"/chat/completions\",method:\"POST\",headers:{Authorization:\"Bearer \"+process.env.PERPLEXITY_API_KEY,\"Content-Type\":\"application/json\",\"Content-Length\":Buffer.byteLength(body)}};const req=https.request(opts,res=>{let d=\"\";res.on(\"data\",c=>d+=c);res.on(\"end\",()=>{try{const r=JSON.parse(d);results[i]={content:r.choices[0].message.content,citations:r.citations||[]};}catch(e){results[i]={content:\"\",citations:[]};}done++;if(done===queries.length){const urls=[...new Set(results.flatMap(r=>r.citations))];process.stdout.write(JSON.stringify({results,high_value_urls:urls.slice(0,20),total:urls.length}));}});});req.on(\"error\",()=>{results[i]={content:\"\",citations:[]};done++;if(done===queries.length){const urls=[...new Set(results.flatMap(r=>r.citations))];process.stdout.write(JSON.stringify({results,high_value_urls:urls.slice(0,20),total:urls.length}));}});req.write(body);req.end();});"'
    stdin: '{"queries": $route.json.routed}'
    condition: $await-plan-approval.json.approved

  - id: pass-1-academic
    command: >
      exec --json --shell 'node -e "const https=require(\"https\");const input=JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\",\"utf8\"));const queries=input.queries||[];const results=[];let done=0;if(!queries.length){process.stdout.write(JSON.stringify({results:[],papers:[]}));return;}queries.forEach((q,i)=>{const query=encodeURIComponent(typeof q===\"string\"?q:q.query||q.question||\"\");const opts={hostname:\"api.semanticscholar.org\",path:\"/graph/v1/paper/search?query=\"+query+\"&limit=10&fields=title,abstract,year,citationCount,authors,url,externalIds\",method:\"GET\"};const req=https.request(opts,res=>{let d=\"\";res.on(\"data\",c=>d+=c);res.on(\"end\",()=>{try{results[i]=JSON.parse(d);}catch{results[i]={data:[]};}done++;if(done===queries.length)process.stdout.write(JSON.stringify({results,papers:results.flatMap(r=>(r.data||[]))}));});});req.on(\"error\",()=>{results[i]={data:[]};done++;if(done===queries.length)process.stdout.write(JSON.stringify({results,papers:results.flatMap(r=>(r.data||[]))}));});req.end();});"'
    stdin: '{"queries": $route.json.routed}'

  # Retrieve full content from high-value pages
  - id: pass-1-retrieve
    command: >
      openclaw.invoke --tool agent-browser --action browse --args-json '{
        "urls": $pass-1-search.json.high_value_urls,
        "extract": "markdown"
      }'

  # Evaluate pass 1
  - id: pass-1-eval
    command: >
      exec --json --shell 'node scripts/lens-pass-evaluator.js'
    stdin: '{"sub_questions": $decompose.json.sub_questions, "evidence_map": $pass-1-retrieve.json, "academic_results": $pass-1-academic.json, "pass_number": 1, "stakes": "{{stakes}}", "confidence_thresholds": $load-thresholds.json}'

  # Pass 2 — Refine and fill gaps
  - id: pass-2-refine
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "These sub-questions still need better sources. Refine the search queries based on what was found in pass 1. For sub-questions with zero results, broaden the query. For single-source results, find corroborating sources.",
        "thinking": "off",
        "input": {
          "gaps": $pass-1-eval.json.evaluation,
          "pass_1_results": $pass-1-search.json
        },
        "schema": {
          "type": "object",
          "properties": {
            "refined_queries": {"type": "array", "items": {"type": "object", "properties": {"sub_question_id": {"type": "string"}, "query": {"type": "string"}, "target_sources": {"type": "array"}}}}
          }
        }
      }'
    condition: $pass-1-eval.json.should_continue

  - id: pass-2-search
    command: >
      exec --json --shell 'node -e "const https=require(\"https\");const input=JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\",\"utf8\"));const queries=input.queries||[];const results=[];let done=0;if(!queries.length){process.stdout.write(JSON.stringify({results:[],high_value_urls:[],total:0}));return;}queries.forEach((q,i)=>{const body=JSON.stringify({model:\"sonar\",messages:[{role:\"user\",content:typeof q===\"string\"?q:q.query||q.question||JSON.stringify(q)}]});const opts={hostname:\"api.perplexity.ai\",path:\"/chat/completions\",method:\"POST\",headers:{Authorization:\"Bearer \"+process.env.PERPLEXITY_API_KEY,\"Content-Type\":\"application/json\",\"Content-Length\":Buffer.byteLength(body)}};const req=https.request(opts,res=>{let d=\"\";res.on(\"data\",c=>d+=c);res.on(\"end\",()=>{try{const r=JSON.parse(d);results[i]={content:r.choices[0].message.content,citations:r.citations||[]};}catch(e){results[i]={content:\"\",citations:[]};}done++;if(done===queries.length){const urls=[...new Set(results.flatMap(r=>r.citations))];process.stdout.write(JSON.stringify({results,high_value_urls:urls.slice(0,20),total:urls.length}));}});});req.on(\"error\",()=>{results[i]={content:\"\",citations:[]};done++;if(done===queries.length){const urls=[...new Set(results.flatMap(r=>r.citations))];process.stdout.write(JSON.stringify({results,high_value_urls:urls.slice(0,20),total:urls.length}));}});req.write(body);req.end();});"'
    stdin: '{"queries": $pass-2-refine.json.refined_queries}'
    condition: $pass-1-eval.json.should_continue

  - id: pass-2-retrieve
    command: >
      openclaw.invoke --tool agent-browser --action browse --args-json '{
        "urls": $pass-2-search.json.high_value_urls,
        "extract": "markdown"
      }'
    condition: $pass-1-eval.json.should_continue

  - id: pass-2-eval
    command: >
      exec --json --shell 'node scripts/lens-pass-evaluator.js'
    stdin: '{"sub_questions": $decompose.json.sub_questions, "evidence_map": {"pass_1": $pass-1-retrieve.json, "pass_2": $pass-2-retrieve.json}, "pass_number": 2, "stakes": "{{stakes}}", "confidence_thresholds": $load-thresholds.json}'
    condition: $pass-1-eval.json.should_continue

  # Pass 3 — Deep retrieval for remaining gaps (high-stakes only continues to 4-5)
  - id: pass-3-refine
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Final pass refinement. For remaining gaps, try: alternative databases, different search terms, primary source direct retrieval via agent-browser. For single-source claims, try domain-specific databases.",
        "thinking": "off",
        "input": {"gaps": $pass-2-eval.json.evaluation}
      }'
    condition: $pass-2-eval.json.should_continue

  - id: pass-3-search
    command: >
      exec --json --shell 'node -e "const https=require(\"https\");const input=JSON.parse(require(\"fs\").readFileSync(\"/dev/stdin\",\"utf8\"));const queries=input.queries||[];const results=[];let done=0;if(!queries.length){process.stdout.write(JSON.stringify({results:[],high_value_urls:[],total:0}));return;}queries.forEach((q,i)=>{const body=JSON.stringify({model:\"sonar\",messages:[{role:\"user\",content:typeof q===\"string\"?q:q.query||q.question||JSON.stringify(q)}]});const opts={hostname:\"api.perplexity.ai\",path:\"/chat/completions\",method:\"POST\",headers:{Authorization:\"Bearer \"+process.env.PERPLEXITY_API_KEY,\"Content-Type\":\"application/json\",\"Content-Length\":Buffer.byteLength(body)}};const req=https.request(opts,res=>{let d=\"\";res.on(\"data\",c=>d+=c);res.on(\"end\",()=>{try{const r=JSON.parse(d);results[i]={content:r.choices[0].message.content,citations:r.citations||[]};}catch(e){results[i]={content:\"\",citations:[]};}done++;if(done===queries.length){const urls=[...new Set(results.flatMap(r=>r.citations))];process.stdout.write(JSON.stringify({results,high_value_urls:urls.slice(0,20),total:urls.length}));}});});req.on(\"error\",()=>{results[i]={content:\"\",citations:[]};done++;if(done===queries.length){const urls=[...new Set(results.flatMap(r=>r.citations))];process.stdout.write(JSON.stringify({results,high_value_urls:urls.slice(0,20),total:urls.length}));}});req.write(body);req.end();});"'
    stdin: '{"queries": $pass-3-refine.json.refined_queries}'
    condition: $pass-2-eval.json.should_continue

  - id: pass-3-retrieve
    command: >
      openclaw.invoke --tool agent-browser --action browse --args-json '{
        "urls": $pass-3-search.json.high_value_urls,
        "extract": "markdown"
      }'
    condition: $pass-2-eval.json.should_continue

  - id: pass-3-eval
    command: >
      exec --json --shell 'node scripts/lens-pass-evaluator.js'
    stdin: '{"sub_questions": $decompose.json.sub_questions, "evidence_map": {"pass_1": $pass-1-retrieve.json, "pass_2": $pass-2-retrieve.json, "pass_3": $pass-3-retrieve.json}, "pass_number": 3, "stakes": "{{stakes}}", "confidence_thresholds": $load-thresholds.json}'
    condition: $pass-2-eval.json.should_continue

  # Step 9: Track corroboration and assign confidence tiers (Req 12-16)
  - id: track-corroboration
    command: >
      exec --json --shell 'node scripts/lens-corroboration-tracker.js'

  # Step 10: Freshness check on all sources (Req 31)
  - id: freshness-check
    command: >
      exec --json --shell 'node scripts/lens-freshness-checker.js'

  # Step 11: Cross-check secondary against primary (Req 21, high-stakes)
  - id: cross-check
    command: >
      exec --json --shell 'node scripts/lens-cross-checker.js'
    condition: $stakes == "high_stakes"

  # Step 12: Semantic cross-check for flagged items — LLM
  - id: semantic-cross-check
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Compare these secondary source claims against their primary sources. For each pair, determine: does the secondary accurately represent the primary, or does it introduce distortion? Be specific about any discrepancies.",
        "thinking": "off",
        "input": $cross-check.json.secondary_primary
      }'
    condition: $cross-check.json.needs_agent_loop

  # Step 13: Cross-vertical contradiction check (Req 29)
  - id: cross-vertical
    command: >
      exec --json --shell 'node scripts/lens-cross-checker.js'
    stdin: '{"mode": "cross_vertical", "findings": $track-corroboration.json.claims}'

  # Step 14: Format synthesis (Req 23-27)
  - id: format-synthesis
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "lens-state/user-format-preference"}'
      | exec --json --shell 'node scripts/lens-synthesis-formatter.js'

  # Step 15: Generate narrative synthesis — ADAPTIVE LLM (Req 23)
  - id: generate-narrative
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Write the research synthesis narrative connecting these confidence-rated findings. Preserve every inline tier tag and source citation exactly as formatted. Adapt your writing style to the users preference. Structure per the vertical format. Do NOT fill any gaps with generated content — gaps are listed in the What We Could Not Verify section. Do NOT present uncertain findings with confident language.",
        "thinking": "low",
        "input": {
          "formatted_claims": $format-synthesis.json.formatted_claims,
          "confidence_summary": $format-synthesis.json.confidence_summary,
          "gap_section": $format-synthesis.json.gap_section,
          "source_appendix": $format-synthesis.json.source_appendix,
          "vertical": "{{vertical}}",
          "cross_vertical_issues": $cross-vertical.json,
          "freshness_flags": $freshness-check.json
        }
      }'

  # Step 16: Deliver to Slack
  - id: deliver
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#lens-research",
        "text": "📋 RESEARCH COMPLETE — {{research_question}}\n\n$format-synthesis.json.confidence_summary.text\n\n$generate-narrative.json.synthesis\n\n$format-synthesis.json.gap_section\n\n$format-synthesis.json.source_appendix"
      }'

  # Step 17: Store in fast-io + Google Drive for audit
  - id: store-research
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "lens-research/{{timestamp}}/{{research_question}}",
        "data": {
          "question": "{{research_question}}",
          "vertical": "{{vertical}}",
          "stakes": "{{stakes}}",
          "claims": $track-corroboration.json.claims,
          "confidence_summary": $format-synthesis.json.confidence_summary,
          "source_appendix": $format-synthesis.json.source_appendix,
          "gaps": $format-synthesis.json.gap_section,
          "passes_completed": $pass-3-eval.json.pass_number,
          "timestamp": "{{timestamp}}"
        }
      }'

  - id: store-drive
    command: >
      openclaw.invoke --tool gog --action drive-write --args-json '{
        "path": "Lens Research Archive/{{date}}-{{research_question}}",
        "content": $generate-narrative.json.synthesis
      }'

  # Step 18: Update historical research data for future confidence estimates
  - id: update-history
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "lens-state/historical-research/{{vertical}}",
        "data": {
          "avg_sources_found": $track-corroboration.json.claims,
          "last_research": "{{timestamp}}"
        }
      }'

  # Step 19: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/research",
        "data": {
          "action": "research_completed",
          "question": "{{research_question}}",
          "vertical": "{{vertical}}",
          "stakes": "{{stakes}}",
          "sub_questions": $decompose.json.sub_questions.length,
          "passes": $pass-3-eval.json.pass_number,
          "confidence_summary": $format-synthesis.json.confidence_summary.tiers,
          "verification_rate": $format-synthesis.json.confidence_summary.verification_rate,
          "authorized_by": "user_approved_plan",
          "timestamp": "{{timestamp}}"
        }
      }'
