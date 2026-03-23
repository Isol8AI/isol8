export function Features() {
  return (
    <section className="landing-features" id="features">
      <div className="section-inner">
        <p className="section-eyebrow reveal">Your Pod</p>
        <h2 className="section-h2 reveal">
          A private AI that&apos;s <em>entirely yours.</em>
        </h2>

        <div className="feat-grid">
          <div className="feat-card reveal reveal-d1">
            <div className="feat-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="8" r="4" />
                <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
                <path d="M16 3.5c1.5.8 2.5 2.3 2.5 4s-1 3.2-2.5 4" />
              </svg>
            </div>
            <h3 className="feat-title">Custom Personality</h3>
            <p className="feat-desc">
              Shape how your agent thinks, speaks, and approaches problems.
              Define its tone, values, and working style. It learns your
              preferences and adapts — not the other way around.
            </p>
          </div>
          <div className="feat-card reveal reveal-d2">
            <div className="feat-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </div>
            <h3 className="feat-title">Memory &amp; Privacy</h3>
            <p className="feat-desc">
              Every conversation builds on the last. Your pod runs in a fully
              isolated container — no shared state, no model training on your
              data. What&apos;s yours stays yours, across every session.
            </p>
          </div>
          <div className="feat-card reveal reveal-d3">
            <div className="feat-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
            <h3 className="feat-title">Acts Autonomously</h3>
            <p className="feat-desc">
              Your pod doesn&apos;t just answer — it acts. Schedule tasks, run
              workflows, send messages, and complete multi-step jobs in the
              background while you focus on what matters.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
