import Link from "next/link";

export function Pricing() {
  return (
    <section className="landing-pricing" id="pricing">
      <div className="section-inner">
        <p className="section-eyebrow reveal">Pricing</p>
        <h2 className="section-h2 reveal">
          Simple pricing. <em>No surprises.</em>
        </h2>

        <div className="price-grid">
          {/* Starter */}
          <div className="price-card reveal reveal-d1">
            <p className="plan-name">Starter</p>
            <div className="plan-price">
              <span className="plan-price-num">$25</span>
              <span className="plan-price-mo">/mo</span>
            </div>
            <p className="plan-desc">
              For individuals building their first pod.
            </p>
            <ul className="plan-features">
              <li><span className="plan-dash">—</span> 1 personal pod</li>
              <li><span className="plan-dash">—</span> Persistent memory &amp; personality</li>
              <li><span className="plan-dash">—</span> Core skills included</li>
              <li><span className="plan-dash">—</span> Pay-per-use premium models</li>
              <li><span className="plan-dash">—</span> Standard support</li>
            </ul>
            <Link href="/chat" className="plan-cta default">
              Get started
            </Link>
          </div>

          {/* Pro */}
          <div className="price-card highlight reveal reveal-d2">
            <div className="popular-badge">Most popular</div>
            <p className="plan-name">Pro</p>
            <div className="plan-price">
              <span className="plan-price-num">$75</span>
              <span className="plan-price-mo">/mo</span>
            </div>
            <p className="plan-desc">
              For power users who need the full toolkit.
            </p>
            <ul className="plan-features">
              <li><span className="plan-dash">—</span> Everything in Starter</li>
              <li><span className="plan-dash">—</span> Higher usage budget</li>
              <li><span className="plan-dash">—</span> All premium skills &amp; tools</li>
              <li><span className="plan-dash">—</span> All top-tier models</li>
              <li><span className="plan-dash">—</span> Priority support</li>
            </ul>
            <Link href="/chat" className="plan-cta featured">
              Upgrade to Pro
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
