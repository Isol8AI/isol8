"use client";

import { useState, type ReactNode } from "react";

type Agent = {
  id: string;
  name: string;
  role: string;
  lede: ReactNode;
  failures: ReactNode[];
  build: ReactNode[];
};

const AGENTS: Agent[] = [
  {
    id: "echo",
    name: "Echo",
    role: "Meeting Recap",
    lede: (
      <>
        Turns every meeting into an accurate, reviewable record — and makes sure
        what was decided actually gets done. Drafts the recap, extracts action
        items, tracks them to completion.{" "}
        <strong>A human approves before anything is distributed.</strong>
      </>
    ),
    failures: [
      <>
        <strong>Whisper hallucinates in 1.4% of transcriptions</strong> —
        fabricates sentences that were never spoken. Echo applies the Cornell
        silence-trim fix and flags low-confidence segments.
      </>,
      <>
        <strong>Meetings cost U.S. businesses $399B/yr.</strong> 54% of attendees
        leave without knowing what to do next.
      </>,
      <>
        <strong>Seniority bias in AI summarizers</strong> — summaries attribute
        ideas to the highest-title person who agreed, not the originator.
      </>,
      <>
        <strong>Commitment flattening</strong> — &ldquo;we should probably look
        at this&rdquo; gets summarized as a firm action item.
      </>,
    ],
    build: [
      <>
        Seven deterministic JS modules: <code>action-extractor</code>,{" "}
        <code>commitment-classifier</code>, <code>transcript-normalizer</code>,{" "}
        <code>deadline-tracker</code>, <code>synthesis-formatter</code>,{" "}
        <code>audio-preprocessor</code>, <code>activation-check</code>.
      </>,
      <>
        Two Lobster pipelines: <code>meeting-process</code>,{" "}
        <code>weekly-digest</code>.
      </>,
      <>
        LLM reserved for the narrative summary alone — every classification and
        extraction is deterministic.
      </>,
      <>Explicit anti-seniority-bias instruction in every summary prompt.</>,
      <>Nothing distributes until the configured reviewer approves.</>,
    ],
  },
  {
    id: "ember",
    name: "Ember",
    role: "HR Operations",
    lede: (
      <>
        Automates the 14 hours per week of administrative work that consumes HR
        professionals without producing value — onboarding orchestration, policy
        queries, compliance documentation, people analytics, review prep.{" "}
        <strong>
          Ember never automates the decisions that determine someone&apos;s
          livelihood.
        </strong>
      </>
    ),
    failures: [
      <>
        <strong>Amazon&apos;s recruiting AI</strong> taught itself that maleness
        predicted hiring success.
      </>,
      <>
        <strong>Workday&apos;s screening tool</strong> rejected a man at 12:55
        AM before any human saw his application — a federal judge ruled it
        participated in the hiring decision.
      </>,
      <>
        <strong>iTutorGroup</strong> explicitly programmed age discrimination at
        scale.
      </>,
      <>
        <strong>CVS</strong> scored candidates on facial expressions.
      </>,
      <>
        <strong>HireVue</strong> told a deaf applicant to work on &ldquo;active
        listening.&rdquo;
      </>,
    ],
    build: [
      <>
        A strict operational/decision split — Ember handles the operational
        layer and refuses anything that touches employment, compensation, or
        career trajectory.
      </>,
      <>
        Never: hiring, firing, promoting, demoting, evaluating, disciplining, or
        accommodating a specific person.
      </>,
      <>
        Prepares humans to make those calls faster and better-informed; never
        substitutes for them.
      </>,
      <>All HR data handled per the policy library configured by the customer.</>,
    ],
  },
  {
    id: "lens",
    name: "Lens",
    role: "Research Intelligence",
    lede: (
      <>
        Focuses research on any vertical — market, tech, academic, legal,
        competitive — and delivers findings the user can actually{" "}
        <strong>verify, not just trust.</strong> Every claim carries a source
        tier and a confidence rating derived from cross-verification.
      </>
    ),
    failures: [
      <>
        <strong>AI is 34% more likely to use confident language</strong> when
        generating incorrect information.
      </>,
      <>
        <strong>The Chicago Sun-Times</strong> published a summer reading list
        with 10 phantom books that don&apos;t exist.
      </>,
      <>
        <strong>Deloitte</strong> submitted $2M in government reports with
        fabricated citations.
      </>,
      <>
        A mathematical proof confirmed hallucinations cannot be fully eliminated
        under current LLM architectures — so Lens surfaces them instead of
        hiding them.
      </>,
    ],
    build: [
      <>
        Nine JS modules: <code>source-router</code>,{" "}
        <code>corroboration-tracker</code>, <code>confidence-estimator</code>,{" "}
        <code>confidence-degrader</code>, <code>cross-checker</code>,{" "}
        <code>freshness-checker</code>, <code>pass-evaluator</code>,{" "}
        <code>change-describer</code>, <code>synthesis-formatter</code>.
      </>,
      <>
        Five vertical source hierarchies (Financial, Technology, Academic,
        Legal, Competitive) — configurable, not hardcoded.
      </>,
      <>
        Multi-pass search: 2 passes for casual, 3 for standard, 5 for
        high-stakes. Each pass refines the next.
      </>,
      <>
        Five confidence tiers: Verified (3+ independent primaries), Supported,
        Single-source, Contested, Gap.
      </>,
      <>
        Citation amplification detection — three articles citing the same origin
        count as one source.
      </>,
    ],
  },
  {
    id: "ora",
    name: "Ora",
    role: "Scheduling",
    lede: (
      <>
        Protects the user&apos;s time, coordinates meetings with others, and
        surfaces intelligence about how their calendar is actually working.{" "}
        <strong>
          Ora never takes a scheduling action that affects another person
          without the user seeing it first.
        </strong>
      </>
    ),
    failures: [
      <>
        <strong>GPT-4o fails at basic scheduling 91.4% of the time.</strong> Ora
        does zero scheduling math in the LLM.
      </>,
      <>
        <strong>Motion stresses out 68% of its users.</strong> Ora doesn&apos;t
        rearrange your life — it suggests and enforces the rules you set.
      </>,
      <>
        <strong>The Berlin DST disaster</strong> destroyed weeks of coordination
        from a six-line logic error. Ora&apos;s datetime engine is a real
        module, audited, not an LLM afterthought.
      </>,
    ],
    build: [
      <>
        Three-tier architecture — <strong>Suggest</strong> (read + analyze,
        fully autonomous), <strong>Protect</strong> (enforce rules the user
        set), <strong>Coordinate</strong> (requires user confirmation).
      </>,
      <>
        14 JS modules — <code>datetime-engine</code>, <code>slot-ranker</code>,{" "}
        <code>conflict-detector</code>, <code>buffer-checker</code>,{" "}
        <code>rule-enforcer</code>, <code>booking-engine</code>, and more.
      </>,
      <>
        Four Lobster pipelines: <code>morning-briefing</code>,{" "}
        <code>reschedule-cancel</code>, <code>scheduling-request</code>,{" "}
        <code>weekly-digest</code>.
      </>,
      <>
        Every outbound booking that affects another person routes through user
        confirmation.
      </>,
    ],
  },
  {
    id: "pitch",
    name: "Pitch",
    role: "Sales",
    lede: (
      <>
        Finds buying signals, researches prospects, generates outreach drafts,
        runs multi-touch sequences, and tracks deal progress through MEDDIC —
        while{" "}
        <strong>
          keeping a human rep in the loop at every moment that carries
          relationship risk.
        </strong>
      </>
    ),
    failures: [
      <>
        <strong>Autonomous cold outreach at scale = reputation damage.</strong>{" "}
        Pitch treats every first touch as relationship-forming and requires rep
        review for messages that carry voice/tone risk.
      </>,
      <>
        <strong>Enrichment errors compound.</strong> Every enrichment carries a
        confidence score; low-confidence data is flagged, never silently used.
      </>,
      <>
        <strong>Bounce-rate cascades</strong> that get domains blacklisted —
        Pitch monitors sender reputation and auto-pauses sequences before damage
        is done.
      </>,
      <>
        <strong>Opt-out handling</strong> is a legal and trust failure point —
        Pitch runs a dedicated detector on every reply.
      </>,
    ],
    build: [
      <>
        12 JS modules including <code>signal-scorer</code>,{" "}
        <code>meddic-gap-check</code>, <code>icp-router</code>,{" "}
        <code>enrichment-confidence</code>, <code>bounce-rate-check</code>,{" "}
        <code>compliance-check</code>, <code>sequence-pauser</code>,{" "}
        <code>opt-out-detector</code>, <code>interrupt-checker</code>.
      </>,
      <>
        Lobster pipelines for signal sweeps, enrichment, sequence execution,
        reply handling, MEDDIC scans.
      </>,
      <>
        Interrupt-checker runs on every outbound — pauses for rep review any
        time the conversation crosses a relationship-risk threshold.
      </>,
      <>
        MEDDIC gap-check surfaces the specific missing qualifier on every open
        opportunity.
      </>,
    ],
  },
  {
    id: "pulse",
    name: "Pulse",
    role: "Marketing Intelligence & Ops",
    lede: (
      <>
        Runs the intelligence layer autonomously — monitoring, research, GEO
        tracking, competitive intel, voice scoring.{" "}
        <strong>
          The marketer is brought in exactly when human judgment is what the
          work requires: publishing content.
        </strong>
      </>
    ),
    failures: [
      <>
        <strong>
          &ldquo;Slop&rdquo; was Merriam-Webster&apos;s Word of the Year for
          2025.
        </strong>{" "}
        Pulse never ships content to an audience without marketer review.
      </>,
      <>
        <strong>60% of users report lower trust in automated content.</strong>{" "}
        Autonomous publication is where reputational damage accumulates — Pulse
        architects against it.
      </>,
      <>
        <strong>Sensitive claims</strong> (medical, legal, financial) surface
        with a hard-stop marker — never auto-published.
      </>,
      <>
        <strong>GEO drift</strong> — how your brand appears in AI answer engines
        changes weekly. Pulse tracks it continuously.
      </>,
    ],
    build: [
      <>
        A hard split between the <strong>intelligence layer</strong>{" "}
        (autonomous) and the <strong>publication layer</strong> (marketer
        confirms every piece).
      </>,
      <>
        10 JS modules — <code>voice-scorer</code>,{" "}
        <code>sensitive-claim-detector</code>, <code>geo-monitor</code>,{" "}
        <code>geo-checker</code>, <code>freshness-tracker</code>,{" "}
        <code>queue-limiter</code>, <code>email-analyzer</code>,{" "}
        <code>performance-connector</code>,{" "}
        <code>calendar-conflict-checker</code>, <code>activation-check</code>.
      </>,
      <>
        Three Lobster pipelines: <code>content-generate</code>,{" "}
        <code>monitoring-sweep</code>, <code>weekly-digest</code>.
      </>,
      <>
        Voice-scorer calibrates every draft to the brand voice profile before it
        reaches the marketer — no off-tone surprises.
      </>,
    ],
  },
  {
    id: "scout",
    name: "Scout",
    role: "Continuous Sourcing",
    lede: (
      <>
        Monitors the web for buying signals, enriches leads through
        vertical-specific database waterfalls, scores them against your ICP, and
        deposits clean, fully briefed leads into Pitch&apos;s outreach queue —
        or directly into the CRM. <strong>Scout never sends outreach.</strong>
      </>
    ),
    failures: [
      <>
        <strong>Lead-gen tools that also send outreach</strong> create the
        blast-cold-email failure mode. Scout is scope-locked — its only output
        is a scored, enriched lead.
      </>,
      <>
        <strong>
          Enrichment waterfalls that silently fall back to bad data
        </strong>{" "}
        — Scout keeps a confidence score on every field and caches per-provider
        health.
      </>,
      <>
        <strong>Duplicate leads</strong> and <strong>stale records</strong> —
        dedicated dedup-check and match-rate monitoring run on every deposit.
      </>,
      <>
        <strong>Compliance misses</strong> (GDPR, CAN-SPAM, company block-lists)
        — compliance-check runs before any lead reaches a downstream system.
      </>,
    ],
    build: [
      <>
        11 JS modules including <code>icp-scorer</code>,{" "}
        <code>enrichment-waterfall</code>, <code>enrichment-cache</code>,{" "}
        <code>dossier-builder</code>, <code>dedup-check</code>,{" "}
        <code>compliance-check</code>, <code>source-health-check</code>,{" "}
        <code>vertical-router</code>, <code>volume-limiter</code>.
      </>,
      <>
        Six Lobster pipelines: <code>daily-source</code>,{" "}
        <code>signal-monitor</code>, <code>enrich-and-score</code>,{" "}
        <code>visitor-alert</code>, <code>deposit-lead</code>,{" "}
        <code>weekly-report</code>.
      </>,
      <>
        ICP inference from natural language is the only LLM task; everything
        after the brief is confirmed is deterministic.
      </>,
      <>
        Vertical-router sends each lead through the right database waterfall
        for its industry.
      </>,
    ],
  },
  {
    id: "tally",
    name: "Tally",
    role: "Finance Co-pilot",
    lede: (
      <>
        Handles the mechanical work — categorization, reconciliation, anomaly
        detection, metric calculation, report generation, tax prep — so the
        finance person can focus on judgment, strategy, and sign-off.{" "}
        <strong>
          Tally is not a replacement. It&apos;s what makes the finance person
          faster and more accurate.
        </strong>
      </>
    ),
    failures: [
      <>
        <strong>$306M in failed AI bookkeeping companies</strong> taught one
        lesson: AI cannot replace the judgment, context, and accountability a
        finance person brings. Tally is built on the opposite premise.
      </>,
      <>
        <strong>Silent miscategorization</strong> compounds every month — Tally
        surfaces low-confidence categorizations for batch approval instead of
        auto-committing.
      </>,
      <>
        <strong>Chain-of-custody</strong> gaps in AI bookkeepers — Tally logs
        the source and rationale for every number it produces.
      </>,
      <>
        <strong>Anomalies hidden in the close</strong> — the anomaly-detector
        runs continuously, not just at month-end.
      </>,
    ],
    build: [
      <>
        Two-tier architecture — mechanical work runs automated, judgment calls
        route to the finance person for sign-off. This is the architecture, not
        a configuration option.
      </>,
      <>
        10 JS modules — <code>categorization-engine</code>,{" "}
        <code>reconciliation</code>, <code>anomaly-detector</code>,{" "}
        <code>metrics-calculator</code>, <code>close-engine</code>,{" "}
        <code>tax-tracker</code>, <code>chain-of-custody</code>,{" "}
        <code>approval-batcher</code>, <code>data-export</code>,{" "}
        <code>activation-check</code>.
      </>,
      <>
        Every number Tally produces is traceable back to its source transaction
        and the rule that categorized it.
      </>,
      <>
        Approval-batcher groups low-confidence items so the finance person
        reviews them in one pass, not one-by-one.
      </>,
    ],
  },
  {
    id: "thread",
    name: "Thread",
    role: "Unified Communications",
    lede: (
      <>
        A single surface for everything inbound and outbound — email, Slack,
        SMS, WhatsApp, Telegram. Everything arrives in one stream, labeled by
        channel and triaged by priority.{" "}
        <strong>The user never switches apps.</strong>
      </>
    ),
    failures: [
      <>
        <strong>
          NIST documented 57% success rates on injection attacks
        </strong>{" "}
        against agents with email access. Thread runs every inbound message
        through a dedicated injection-detector.
      </>,
      <>
        <strong>Microsoft&apos;s EchoLeak</strong> allowed zero-interaction data
        exfiltration from Outlook — content sanitization runs before anything
        reaches the LLM.
      </>,
      <>
        <strong>The Anthropic safety experiment</strong> showed an AI agent
        using inbox information for blackmail. Thread is scope-locked to
        reading and routing — it doesn&apos;t act on inbox content without the
        user.
      </>,
      <>
        <strong>App-switching fatigue</strong> — the user should never open
        three clients to find a single conversation.
      </>,
    ],
    build: [
      <>
        Thread is a <em>surface</em>, not a replacement — channels remain
        unchanged, contacts experience nothing different.
      </>,
      <>
        Eight JS modules — <code>injection-detector</code>,{" "}
        <code>message-sanitizer</code>, <code>channel-router</code>,{" "}
        <code>triage-scorer</code>, <code>contact-context</code>,{" "}
        <code>followup-tracker</code>, <code>preference-learner</code>,{" "}
        <code>activation-check</code>.
      </>,
      <>
        Sanitization happens <em>before</em> the LLM ever sees message content —
        the detector and sanitizer are the first line, not a post-hoc filter.
      </>,
      <>
        Triage-scorer and preference-learner adapt to how the user actually
        reads their inbox.
      </>,
    ],
  },
  {
    id: "vera",
    name: "Vera",
    role: "Customer Support",
    lede: (
      <>
        Resolves customers&apos; problems instantly — without making them feel
        like they&apos;re talking to a machine.{" "}
        <strong>Vera exists to resolve, not to deflect.</strong> Every behavior
        is in service of that single principle.
      </>
    ),
    failures: [
      <>
        <strong>Support bots that optimize for deflection.</strong> Vera&apos;s
        routing logic optimizes for resolution — including fast escalation when
        escalation is the right answer.
      </>,
      <>
        <strong>Agents that dodge hard questions</strong> behind canned
        fallbacks. Vera is built to take the hit, surface the real answer, and
        flag what it doesn&apos;t know.
      </>,
      <>
        <strong>Tone failures</strong> at moments of customer frustration —
        sentiment-detector runs continuously and changes behavior at the right
        threshold.
      </>,
      <>
        <strong>Stale escalations</strong> — escalation-health monitors every
        open thread so nothing sits unreplied.
      </>,
    ],
    build: [
      <>
        Seven JS modules — <code>intake-classifier</code>,{" "}
        <code>sentiment-detector</code>, <code>escalation-builder</code>,{" "}
        <code>escalation-health</code>, <code>ticket-closer</code>,{" "}
        <code>metrics-calculator</code>, <code>activation-check</code>.
      </>,
      <>
        Three Lobster pipelines — one for intake/resolve, one for escalation,
        one for agent-assist (human support staff get background help from Vera
        on their own tickets).
      </>,
      <>
        Vera is not a replacement for the support team. It makes the team faster
        and focuses them on the conversations that actually require human
        judgment.
      </>,
    ],
  },
];

export function OurAgents() {
  const [activeId, setActiveId] = useState(AGENTS[0].id);
  const agent = AGENTS.find((a) => a.id === activeId) ?? AGENTS[0];

  return (
    <section className="landing-agents" id="agents">
      <div className="section-inner">
        <div className="agents-intro">
          <p className="section-eyebrow reveal">Our Agents</p>
          <h2 className="section-h2 reveal">
            We built each agent <em>backwards from the failures.</em>
          </h2>
          <p className="agents-lede">
            Before writing a line of code, we read the post-mortems. Every isol8
            agent opens with{" "}
            <strong>the specific failures it was engineered against</strong> —
            and ships with hand-written code for the mechanical work, so the
            LLM is only invoked where real judgment is required.
          </p>
        </div>

        <div className="agents-tabs" role="tablist" aria-label="isol8 agents">
          {AGENTS.map((a) => (
            <button
              key={a.id}
              type="button"
              role="tab"
              aria-selected={a.id === activeId}
              aria-controls={`agents-panel-${a.id}`}
              className={`agents-tab${a.id === activeId ? " active" : ""}`}
              onClick={() => setActiveId(a.id)}
            >
              {a.name}
            </button>
          ))}
        </div>

        <div
          className="agents-panel"
          role="tabpanel"
          id={`agents-panel-${agent.id}`}
          key={agent.id}
        >
          <div className="agents-panel-head">
            <div className="agents-panel-name">{agent.name}</div>
            <div className="agents-panel-role">{agent.role}</div>
          </div>
          <p className="agents-panel-lede">{agent.lede}</p>
          <div className="agents-panel-body">
            <div>
              <div className="agents-panel-label">Built against</div>
              <ul className="agents-panel-list">
                {agent.failures.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="agents-panel-label">How it&apos;s built</div>
              <ul className="agents-panel-list">
                {agent.build.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
