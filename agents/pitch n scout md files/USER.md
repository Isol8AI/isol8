# User Profile

<!-- Replace all brackets before going live -->

name: [Rep Name]
role: [Sales Rep / SDR / AE / Sales Lead / Founder]
company: [Company Name]
timezone: America/New_York
preferred_name: [How they want to be addressed]

---

## Pitch — Communication Preferences

approval_channel: "#pitch-approvals"
signal_alerts: "#pitch-signals"
pipeline_health: "#pitch-pipeline"
quarantine_alerts: "#pitch-quarantine"
preferred_response_window: [e.g., "within 2 hours during business hours"]

## Pitch — Sales Context

product: [What you sell — one sentence]
avg_deal_size: [e.g., "$12,000 ARR"]
sales_cycle_length: [e.g., "30-60 days"]
primary_persona: [e.g., "VP of Operations at 50-200 person SaaS companies"]
top_competitors: [e.g., "Acme, Rival Co"] <!-- also populate competitor-list in fast-io -->

## Pitch — Voice Calibration

<!-- How should outreach sound? Pitch adapts to the rep's voice. -->
<!-- e.g., "Conversational, never corporate. Short sentences. No buzzwords." -->
<!-- e.g., "Formal but warm. Always references a specific signal." -->
<!-- e.g., "Direct and brief — 3 sentences max for first touch." -->
tone_notes: [Your voice preferences]

## Pitch — Notes

<!-- Any rep-specific context Pitch should know -->
<!-- e.g., "I only work EMEA accounts — always check timezone before sequencing" -->
<!-- e.g., "I prefer to review all C-suite touches personally before they queue" -->
<!-- e.g., "We're in a launch phase — prioritize funded startups under 2 years old" -->

---

## Scout — ICP Baseline

<!-- Scout infers ICP from conversation, but a baseline here speeds up first brief. -->
<!-- Leave blank and tell Scout your ICP verbally if you prefer. -->

target_verticals: [e.g., "SaaS, fintech"] <!-- Scout will map to database stacks -->
target_company_size: [e.g., "50-500 employees"]
target_roles: [e.g., "VP Operations, Head of Revenue, COO"]
target_geographies: [e.g., "US, Canada, UK"]
icp_must_haves: [e.g., "B2B, recurring revenue model, has a sales team"]
icp_disqualifiers: [e.g., "agencies, e-commerce, solo founders"]

## Scout — Signal Preferences

<!-- Which signals matter most for your business? Scout weights accordingly. -->
<!-- Leave blank and Scout will calibrate after the first week of conversion data. -->

high_priority_signals: [e.g., "Series A/B funding, new VP Sales hire, competitor switch"]
low_priority_signals: [e.g., "job postings for junior roles, minor product updates"]
daily_lead_limit: 50 <!-- Scout will never exceed this — raise or lower as needed -->

## Scout — Communication Preferences

lead_alerts: "#scout-alerts"
digest_channel: "#scout-digest"
leads_channel: "#scout-leads"
alert_on_score_above: 90 <!-- immediate Slack ping for urgent leads -->
digest_style: [numbers_first / narrative / bullet_points]

## Scout — Notes

<!-- Any sourcing context Scout should know -->
<!-- e.g., "We just entered the healthcare vertical — prioritize Definitive Healthcare leads" -->
<!-- e.g., "Exclude any company already in our CRM regardless of score" -->
<!-- e.g., "We're a PLG company — website visitors are our highest-value signal" -->
