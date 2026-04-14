export function Skills() {
  return (
    <section className="landing-skills" id="skills">
      <div className="skills-inner">
        <div>
          <p className="skills-eyebrow reveal">Skills &amp; Tools</p>
          <h2 className="skills-h2 reveal">
            Upgrade your agents.
            <br />
            <em>Endlessly.</em>
          </h2>
          <p className="skills-desc">
            Your agents get smarter over time. Browse the skill store to add new
            capabilities — from web search and email to CRM automation and code
            execution. Install what you need, and your agents learn to use them
            on their own.
          </p>
          <div className="skills-bullets">
            <div className="skills-bullet">
              <span className="skills-bullet-num">01</span>
              <span className="skills-bullet-text">
                Browse and install from a growing skill library
              </span>
            </div>
            <div className="skills-bullet">
              <span className="skills-bullet-num">02</span>
              <span className="skills-bullet-text">
                Connect any tool with MCP integrations
              </span>
            </div>
            <div className="skills-bullet">
              <span className="skills-bullet-num">03</span>
              <span className="skills-bullet-text">
                Your agents learn how to use new skills automatically
              </span>
            </div>
          </div>
        </div>

        <div>
          <div className="skill-store-mockup">
            <div className="store-header">
              <div>
                <h3 className="store-title">Skill Store</h3>
                <p className="store-subtitle">Discover and install skills for your agent</p>
              </div>
            </div>
            <div className="store-pills">
              <span className="store-pill active">All</span>
              <span className="store-pill">Installed (5)</span>
              <span className="store-pill">Communication</span>
              <span className="store-pill">Productivity</span>
              <span className="store-pill">Research</span>
            </div>
            <p className="store-section-label">Installed</p>
            <div className="store-card">
              <span className="store-card-emoji">🧠</span>
              <div className="store-card-info">
                <span className="store-card-name">Memory <span className="store-badge">Installed</span></span>
                <span className="store-card-desc">Remember facts and context across conversations</span>
              </div>
            </div>
            <div className="store-card">
              <span className="store-card-emoji">💻</span>
              <div className="store-card-info">
                <span className="store-card-name">Developer <span className="store-badge">Installed</span></span>
                <span className="store-card-desc">Write, run, and debug code in your workspace</span>
              </div>
            </div>
            <p className="store-section-label">Available</p>
            <div className="store-card">
              <img src="/logos/gmail.png" width="24" height="24" alt="Gmail" className="store-card-logo" />
              <div className="store-card-info">
                <span className="store-card-name">Gmail</span>
                <span className="store-card-desc">Read, draft, and send emails on your behalf</span>
              </div>
              <span className="store-install-btn">Install</span>
            </div>
            <div className="store-card">
              <img src="/logos/salesforce.png" width="24" height="24" alt="Salesforce" className="store-card-logo" />
              <div className="store-card-info">
                <span className="store-card-name">Salesforce</span>
                <span className="store-card-desc">Query leads, update deals, and automate CRM</span>
              </div>
              <span className="store-install-btn">Install</span>
            </div>
            <div className="store-card">
              <img src="/logos/gcal.png" width="24" height="24" alt="Google Calendar" className="store-card-logo" />
              <div className="store-card-info">
                <span className="store-card-name">Google Calendar</span>
                <span className="store-card-desc">Manage events, check availability, and schedule</span>
              </div>
              <span className="store-install-btn">Install</span>
            </div>
            <div className="store-card">
              <span className="store-card-emoji">🔍</span>
              <div className="store-card-info">
                <span className="store-card-name">Perplexity</span>
                <span className="store-card-desc">Search the web with AI-powered answers</span>
              </div>
              <span className="store-install-btn">Install</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
