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
          {/* Free */}
          <div className="price-card reveal reveal-d1">
            <p className="plan-name">Free</p>
            <div className="plan-price">
              <span className="plan-price-num">$0</span>
              <span className="plan-price-mo">/mo</span>
            </div>
            <p className="plan-desc">
              Try Isol8 with no commitment.
            </p>
            <ul className="plan-features">
              <li><span className="plan-dash">—</span> 1 personal pod</li>
              <li><span className="plan-dash">—</span> Scale-to-zero container</li>
              <li><span className="plan-dash">—</span> $2 lifetime LLM credit</li>
              <li><span className="plan-dash">—</span> MiniMax M2.5 model</li>
              <li><span className="plan-dash">—</span> Community support</li>
            </ul>
            <Link href="/chat" className="plan-cta default">
              Get started
            </Link>
          </div>

          {/* Starter */}
          <div className="price-card reveal reveal-d2">
            <p className="plan-name">Starter</p>
            <div className="plan-price">
              <span className="plan-price-num">$40</span>
              <span className="plan-price-mo">/mo</span>
            </div>
            <p className="plan-desc">
              For individuals building their first pod.
            </p>
            <ul className="plan-features">
              <li><span className="plan-dash">—</span> Always-on container</li>
              <li><span className="plan-dash">—</span> $10/mo included LLM usage</li>
              <li><span className="plan-dash">—</span> Qwen3 235B primary model</li>
              <li><span className="plan-dash">—</span> Core skills &amp; tools</li>
              <li><span className="plan-dash">—</span> Standard support</li>
            </ul>
            <Link href="/chat" className="plan-cta default">
              Get started
            </Link>
          </div>

          {/* Pro */}
          <div className="price-card highlight reveal reveal-d3">
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
              <li><span className="plan-dash">—</span> 1 vCPU / 2 GB container</li>
              <li><span className="plan-dash">—</span> $40/mo included LLM usage</li>
              <li><span className="plan-dash">—</span> All premium skills &amp; tools</li>
              <li><span className="plan-dash">—</span> Priority support</li>
            </ul>
            <Link href="/chat" className="plan-cta featured">
              Upgrade to Pro
            </Link>
          </div>

          {/* Enterprise */}
          <div className="price-card reveal reveal-d4">
            <p className="plan-name">Enterprise</p>
            <div className="plan-price">
              <span className="plan-price-num">Custom</span>
            </div>
            <p className="plan-desc">
              For teams that need dedicated resources.
            </p>
            <ul className="plan-features">
              <li><span className="plan-dash">—</span> Everything in Pro</li>
              <li><span className="plan-dash">—</span> 2 vCPU / 4 GB container</li>
              <li><span className="plan-dash">—</span> $80/mo included LLM usage</li>
              <li><span className="plan-dash">—</span> Qwen3 235B subagent model</li>
              <li><span className="plan-dash">—</span> Dedicated support</li>
            </ul>
            <a href="mailto:team@isol8.co" className="plan-cta default">
              Contact us
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
