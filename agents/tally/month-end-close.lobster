name: month-end-close
# Requirements 40-44: Month-end close as review-and-confirm workflow.
# Triggered last business day of month or manually by finance person.
# LLM calls: 0 (fully deterministic — all math and assembly)

args:
  period_end:
    required: true
  period_start:
    required: true

steps:
  # Step 0: Load connected accounting platform config
  - id: load-accounting
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "tally-config/connected-accounting"}'

  # Step 1: Final reconciliation across all accounts (Req 19)
  - id: final-recon-xero
    command: >
      openclaw.invoke --tool xero --action get-bank-statements --args-json '{
        "from": "{{period_start}}",
        "to": "{{period_end}}"
      }'
      | exec --json --shell 'node scripts/tally-reconciliation.js'
    condition: $load-accounting.json.platform == "xero"

  - id: final-recon-qbo
    command: >
      exec --shell 'curl -sS "https://quickbooks.api.intuit.com/v3/company/$QBO_REALM_ID/query?query=SELECT%20*%20FROM%20Account%20WHERE%20AccountType%20%3D%20%27Bank%27&minorversion=65" \
        -H "Authorization: Bearer $QBO_ACCESS_TOKEN" \
        -H "Accept: application/json" \
        | node -e "
          let d=\"\";process.stdin.on(\"data\",c=>d+=c);process.stdin.on(\"end\",()=>{
            const r=JSON.parse(d);
            const accounts=(r.QueryResponse?.Account||[]).map(a=>({id:a.Id,name:a.Name,balance:a.CurrentBalance,type:a.AccountType}));
            process.stdout.write(JSON.stringify({accounts,period_start:\"{{period_start}}\",period_end:\"{{period_end}}\"}));
          });"' \
        | exec --json --shell 'node scripts/tally-reconciliation.js'
    condition: $load-accounting.json.platform == "quickbooks"

  # Step 2: Final duplicate check (Req 20)
  - id: final-duplicates-xero
    command: >
      openclaw.invoke --tool xero --action list-transactions --args-json '{
        "from": "{{period_start}}",
        "to": "{{period_end}}"
      }'
      | exec --json --shell 'node scripts/tally-reconciliation.js'
    condition: $load-accounting.json.platform == "xero"

  - id: final-duplicates-qbo
    command: >
      exec --shell 'curl -sS "https://quickbooks.api.intuit.com/v3/company/$QBO_REALM_ID/query?query=SELECT%20*%20FROM%20Purchase%20WHERE%20TxnDate%20%3E%3D%20%27{{period_start}}%27%20AND%20TxnDate%20%3C%3D%20%27{{period_end}}%27&minorversion=65" \
        -H "Authorization: Bearer $QBO_ACCESS_TOKEN" \
        -H "Accept: application/json" \
        | node -e "
          let d=\"\";process.stdin.on(\"data\",c=>d+=c);process.stdin.on(\"end\",()=>{
            const r=JSON.parse(d);
            const txns=(r.QueryResponse?.Purchase||[]).map(t=>({id:t.Id,date:t.TxnDate,amount:t.TotalAmt,vendor:t.EntityRef?.name}));
            process.stdout.write(JSON.stringify({transactions:txns}));
          });"' \
        | exec --json --shell 'node scripts/tally-reconciliation.js'
    condition: $load-accounting.json.platform == "quickbooks"

  # Merge reconciliation results (only one branch runs per platform)
  - id: final-recon
    command: >
      exec --json --shell 'node -e "
        const x=process.env.XERO||\"\",q=process.env.QBO||\"\";
        process.stdout.write(x||q||\"{}\");
      "'
    env:
      XERO: $final-recon-xero.stdout
      QBO: $final-recon-qbo.stdout

  - id: final-duplicates
    command: >
      exec --json --shell 'node -e "
        const x=process.env.XERO||\"\",q=process.env.QBO||\"\";
        process.stdout.write(x||q||\"{}\");
      "'
    env:
      XERO: $final-duplicates-xero.stdout
      QBO: $final-duplicates-qbo.stdout

  # Step 3: Load accounting policies for journal entries
  - id: load-policies
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "tally-config/accounting-policies"}'

  # Step 4: Generate close checklist (Req 41)
  - id: checklist
    command: >
      exec --json --shell 'node scripts/tally-close-engine.js'
    stdin: '{"mode": "checklist"}'

  # Step 5: Draft journal entries — accruals, prepaids, depreciation (Req 42)
  - id: journal-entries
    command: >
      exec --json --shell 'node scripts/tally-close-engine.js'
    stdin: '{"mode": "journal_entries", "policies": $load-policies.json, "period": {"end_date": "{{period_end}}"}}'

  # Step 6: Generate draft financial statements (Req 43)
  - id: draft-statements-xero
    command: >
      openclaw.invoke --tool xero --action get-reports --args-json '{
        "reports": ["profit_and_loss", "balance_sheet", "cash_flow"],
        "from": "{{period_start}}",
        "to": "{{period_end}}"
      }'
    condition: $load-accounting.json.platform == "xero"

  - id: draft-statements-qbo
    command: >
      exec --shell 'node -e "
        const https=require(\"https\");
        const reports=[\"ProfitAndLoss\",\"BalanceSheet\",\"CashFlow\"];
        const realm=process.env.QBO_REALM_ID;
        const token=process.env.QBO_ACCESS_TOKEN;
        const results={};
        let done=0;
        reports.forEach(r=>{
          const url=\"https://quickbooks.api.intuit.com/v3/company/\"+realm+\"/reports/\"+r+\"?start_date={{period_start}}&end_date={{period_end}}&minorversion=65\";
          https.get(url,{headers:{\"Authorization\":\"Bearer \"+token,\"Accept\":\"application/json\"}},res=>{
            let d=\"\";res.on(\"data\",c=>d+=c);res.on(\"end\",()=>{
              results[r]=JSON.parse(d);
              if(++done===reports.length)process.stdout.write(JSON.stringify(results));
            });
          });
        });"'
    condition: $load-accounting.json.platform == "quickbooks"

  # Merge financial statements (only one branch runs per platform)
  - id: draft-statements
    command: >
      exec --json --shell 'node -e "
        const x=process.env.XERO||\"\",q=process.env.QBO||\"\";
        process.stdout.write(x||q||\"{}\");
      "'
    env:
      XERO: $draft-statements-xero.stdout
      QBO: $draft-statements-qbo.stdout

  # Step 7: Load prior period for comparison
  - id: load-prior
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "tally-state/prior-period-statements"}'

  # Step 8: Validate statements — flag inconsistencies (Req 44)
  - id: validate-statements
    command: >
      exec --json --shell 'node scripts/tally-close-engine.js'
    stdin: '{"mode": "validate"}'

  # Step 9: Full close package assembly
  - id: assemble-package
    command: >
      exec --json --shell 'node scripts/tally-close-engine.js'

  # Step 10: Write close package to Google Sheet
  - id: write-close-sheet
    command: >
      openclaw.invoke --tool gog --action sheets-write --args-json '{
        "spreadsheet": "Tally Monthly Close",
        "sheet": "{{period_end}}",
        "data": {
          "checklist": $checklist.json,
          "journal_entries": $journal-entries.json,
          "validation_flags": $validate-statements.json
        }
      }'

  # Step 11: Post close package to Slack for finance person review
  - id: notify-close
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#tally-approvals",
        "text": "📋 MONTH-END CLOSE — {{period_end}}\n\n**Checklist:**\n$checklist.json\n\n**Journal entries drafted:** $journal-entries.json.length entries pending your approval\n\n**Validation flags:** $validate-statements.json.length items to review\n\n**Ready to close:** $assemble-package.json.ready_to_close\n\nReview the close package in the spreadsheet: $write-close-sheet.json.url\n\nApprove journal entries and confirm to finalize."
      }'

  # Step 12: Post journal entries for individual approval (Tier 2 gate)
  - id: approval-journal
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "#tally-approvals",
        "text": "📝 JOURNAL ENTRIES — Approval Required\n\n$journal-entries.json\n\n[Approve All] [Review Individual]"
      }'

  # Step 13: Save current period as prior for next month
  - id: save-prior
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "tally-state/prior-period-statements",
        "data": $draft-statements.json
      }'

  # Step 14: Monthly Drive backup (Req 50 — 7-year retention)
  - id: drive-backup
    command: >
      openclaw.invoke --tool gog --action drive-write --args-json '{
        "file": "Tally Audit Backup — {{period_end}}",
        "content": $assemble-package.json,
        "folder": "Tally Audit Archive"
      }'

  # Step 15: Audit log
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "audit/{{timestamp}}/month-end-close",
        "data": {
          "action": "month_end_close",
          "period": "{{period_start}} to {{period_end}}",
          "checklist_items": $checklist.json.length,
          "journal_entries_drafted": $journal-entries.json.length,
          "validation_flags": $validate-statements.json.length,
          "reconciliation": $final-recon.json.summary,
          "duplicates_found": $final-duplicates.json.duplicates_found,
          "ready_to_close": $assemble-package.json.ready_to_close,
          "authorized_by": "autonomous",
          "timestamp": "{{timestamp}}"
        }
      }'
