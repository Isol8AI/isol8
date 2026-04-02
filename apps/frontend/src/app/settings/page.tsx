"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useUser, UserButton, useOrganization } from "@clerk/nextjs";
import { useBilling } from "@/hooks/useBilling";
import { cn } from "@/lib/utils";

// =============================================================================
// Types & Navigation
// =============================================================================

type Panel = "profile" | "billing";

const NAV_SECTIONS = [
  {
    label: "Account",
    items: [
      { id: "profile" as Panel, name: "Profile", icon: "profile" },
      { id: "billing" as Panel, name: "Billing", icon: "billing" },
    ],
  },
];

// =============================================================================
// Constants
// =============================================================================

const PLAN_TIERS = [
  {
    id: "free" as const,
    name: "Free",
    price: 0,
    budget: 2,
    features: [
      "1 personal pod",
      "Persistent memory & personality",
      "Core skills included",
      "$2 included usage budget",
    ],
  },
  {
    id: "starter" as const,
    name: "Starter",
    price: 40,
    budget: 10,
    features: [
      "1 personal pod",
      "Persistent memory & personality",
      "Core skills included",
      "Pay-per-use premium models",
      "$10 included usage budget",
      "Standard support",
    ],
  },
  {
    id: "pro" as const,
    name: "Pro",
    price: 75,
    budget: 40,
    popular: true,
    features: [
      "Everything in Starter",
      "Higher usage budget",
      "All premium skills & tools",
      "All top-tier models",
      "$40 included usage budget",
      "Priority support",
    ],
  },
];

// =============================================================================
// Helpers
// =============================================================================

function formatDollars(amount: number, decimals = 2): string {
  return `$${amount.toFixed(decimals)}`;
}

// =============================================================================
// Icons
// =============================================================================

function NavIcon({ icon }: { icon: string }) {
  switch (icon) {
    case "profile":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
      );
    case "billing":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="1" y="4" width="22" height="16" rx="2" />
          <line x1="1" y1="10" x2="23" y2="10" />
        </svg>
      );
    default:
      return null;
  }
}

// =============================================================================
// Toggle Switch
// =============================================================================

function ToggleSwitch({
  checked,
  onChange,
  disabled,
  labelId,
  descId,
}: {
  checked: boolean;
  onChange: (val: boolean) => void;
  disabled?: boolean;
  labelId: string;
  descId: string;
}) {
  return (
    <label className="settings-toggle-switch" aria-labelledby={labelId} aria-describedby={descId} style={disabled ? { opacity: 0.5, cursor: "not-allowed" } : undefined}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} disabled={disabled} />
      <span className="settings-toggle-slider" />
    </label>
  );
}

// =============================================================================
// Profile Panel
// =============================================================================

function ProfilePanel() {
  const { user } = useUser();
  const { planTier } = useBilling();

  const email = user?.primaryEmailAddress?.emailAddress ?? "";
  const initials = `${(user?.firstName ?? "")[0] ?? ""}${(user?.lastName ?? "")[0] ?? ""}`.toUpperCase();

  return (
    <div className="settings-panel" id="panel-profile" role="tabpanel">
      <h1 className="settings-page-title">Profile</h1>
      <p className="settings-page-desc">Your account information, managed by your authentication provider.</p>

      <div className="settings-card">
        <div className="settings-profile-row">
          <div className="settings-profile-avatar-lg" aria-hidden="true">{initials}</div>
          <div>
            <div className="settings-profile-name">
              {user?.fullName ?? "User"}
              <span className="settings-profile-badge">{planTier}</span>
            </div>
            <div className="settings-profile-email">{email}</div>
          </div>
        </div>
        <div className="settings-card-desc" style={{ marginTop: 0 }}>
          To update your name, email, or password, use the account menu in the top-right corner of the app.
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Billing Panel
// =============================================================================

function BillingPanel() {
  const {
    account,
    isLoading,
    error: accountError,
    isSubscribed,
    planTier,
    createCheckout,
    openPortal,
    toggleOverage,
  } = useBilling();
  const { membership } = useOrganization();

  const isOrgAdmin = !membership || membership.role === "org:admin";

  const [overageEnabled, setOverageEnabled] = useState(false);
  const [overageLimit, setOverageLimit] = useState<string>("");
  const [overageSaving, setOverageSaving] = useState(false);
  const [overageError, setOverageError] = useState<string | null>(null);
  const [overageSuccess, setOverageSuccess] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);

  useEffect(() => {
    if (account) {
      setOverageEnabled(account.overage_enabled);
      setOverageLimit(account.overage_limit != null ? String(account.overage_limit) : "");
    }
  }, [account]);

  const handleCheckout = useCallback(async (tier: "starter" | "pro") => {
    setCheckoutLoading(tier);
    try {
      await createCheckout(tier);
    } catch {
      setCheckoutLoading(null);
    }
  }, [createCheckout]);

  const handlePortal = useCallback(async () => {
    setPortalLoading(true);
    try {
      await openPortal();
    } catch {
      setPortalLoading(false);
    }
  }, [openPortal]);

  const handleOverageToggle = useCallback(async () => {
    const newEnabled = !overageEnabled;
    setOverageSaving(true);
    setOverageError(null);
    setOverageSuccess(false);
    try {
      const limit = overageLimit ? parseFloat(overageLimit) : null;
      await toggleOverage(newEnabled, limit);
      setOverageEnabled(newEnabled);
      setOverageSuccess(true);
      setTimeout(() => setOverageSuccess(false), 2000);
    } catch (err) {
      setOverageError(err instanceof Error ? err.message : "Failed to update overage");
    } finally {
      setOverageSaving(false);
    }
  }, [overageEnabled, overageLimit, toggleOverage]);

  const handleOverageLimitSave = useCallback(async () => {
    setOverageSaving(true);
    setOverageError(null);
    setOverageSuccess(false);
    try {
      const limit = overageLimit ? parseFloat(overageLimit) : null;
      await toggleOverage(overageEnabled, limit);
      setOverageSuccess(true);
      setTimeout(() => setOverageSuccess(false), 2000);
    } catch (err) {
      setOverageError(err instanceof Error ? err.message : "Failed to update overage limit");
    } finally {
      setOverageSaving(false);
    }
  }, [overageEnabled, overageLimit, toggleOverage]);

  // Loading
  if (isLoading) {
    return (
      <div className="settings-panel" id="panel-billing" role="tabpanel">
        <h1 className="settings-page-title">Billing</h1>
        <p className="settings-page-desc">Manage your subscription and view usage.</p>
        <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
          <div className="settings-spinner" />
        </div>
      </div>
    );
  }

  // Org member (non-admin)
  if (membership && membership.role !== "org:admin") {
    return (
      <div className="settings-panel" id="panel-billing" role="tabpanel">
        <h1 className="settings-page-title">Billing</h1>
        <div className="settings-restricted">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#59534d" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          <div className="settings-restricted-title">Billing restricted</div>
          <div className="settings-restricted-desc">Contact your organization admin to manage billing and subscription settings.</div>
        </div>
      </div>
    );
  }

  const currentSpend = account?.current_spend ?? 0;
  const includedBudget = account?.included_budget ?? 0;
  const budgetPercent = includedBudget > 0 ? (currentSpend / includedBudget) * 100 : 0;
  const isPaid = planTier === "starter" || planTier === "pro";
  const barColor = budgetPercent < 75 ? "#06402B" : budgetPercent < 90 ? "#c19a00" : "#b63025";

  return (
    <div className="settings-panel" id="panel-billing" role="tabpanel">
      <h1 className="settings-page-title">Billing</h1>
      <p className="settings-page-desc">Manage your subscription and view usage.</p>

      {accountError && (
        <div className="settings-alert settings-alert-error">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Failed to load billing data. Please refresh the page.
        </div>
      )}

      {/* Current plan summary */}
      {account && (
        <div className="settings-card">
          <div className="settings-card-header">
            <div>
              <div className="settings-card-title" style={{ textTransform: "capitalize" }}>
                {planTier} plan
                {isSubscribed && (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 4, marginLeft: 8, fontSize: 11, fontWeight: 600, color: "#06402B", background: "rgba(6,64,43,.08)", padding: "2px 8px", borderRadius: 999 }}>
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    Active
                  </span>
                )}
              </div>
              <div className="settings-card-desc">
                {isPaid ? `${formatDollars(PLAN_TIERS.find((t) => t.id === planTier)?.price ?? 0, 0)}/month` : "No subscription"}
              </div>
            </div>
            {isSubscribed && (
              <button type="button" className="settings-btn-outline" onClick={handlePortal} disabled={portalLoading}>
                {portalLoading && <span className="settings-spinner" style={{ width: 14, height: 14, borderWidth: 2, marginRight: 6, display: "inline-block", verticalAlign: "middle" }} />}
                Manage Payment
              </button>
            )}
          </div>

          {/* Budget bar */}
          <div className="settings-usage-bar-wrap">
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
              <span style={{ color: "#59534d" }}>Current period spend</span>
              <span style={{ fontWeight: 600, fontFamily: "ui-monospace, monospace", fontSize: 13 }}>
                {formatDollars(currentSpend)} / {formatDollars(includedBudget)}
              </span>
            </div>
            <div className="settings-usage-bar-bg">
              <div className="settings-usage-bar-fill" style={{ width: `${Math.min(budgetPercent, 100)}%`, background: barColor }} />
            </div>
            <div className="settings-usage-text" style={{ color: account.within_included ? "#06402B" : "#c19a00" }}>
              {account.within_included
                ? `${(100 - budgetPercent).toFixed(1)}% of budget remaining`
                : "Exceeding included budget"}
            </div>
          </div>
        </div>
      )}

      {/* Plan tier cards */}
      <div className="settings-card">
        <div className="settings-card-title" style={{ marginBottom: 20 }}>
          {isPaid ? "Change plan" : "Upgrade your plan"}
        </div>
        <div className="settings-tier-grid">
          {PLAN_TIERS.map((tier) => {
            const isCurrent = planTier === tier.id;
            return (
              <div key={tier.id} className={`settings-tier-card${isCurrent ? " current" : ""}${tier.popular && !isCurrent ? " popular" : ""}`}>
                {tier.popular && !isCurrent && <div className="settings-popular-badge">Popular</div>}
                <div className="settings-tier-name">{tier.name}</div>
                <div className="settings-tier-price">
                  {tier.price === 0 ? "Free" : formatDollars(tier.price, 0)}
                  {tier.price > 0 && <span> /mo</span>}
                </div>
                <ul className="settings-tier-features">
                  {tier.features.map((f) => <li key={f}>{f}</li>)}
                </ul>
                {isCurrent ? (
                  <button type="button" className="settings-btn-outline" disabled style={{ width: "100%", textAlign: "center" }}>Current plan</button>
                ) : tier.id === "free" ? (
                  isSubscribed ? (
                    <button type="button" className="settings-btn-outline" onClick={handlePortal} disabled={portalLoading} style={{ width: "100%", textAlign: "center" }}>
                      {portalLoading && <span className="settings-spinner" style={{ width: 14, height: 14, borderWidth: 2, marginRight: 6, display: "inline-block", verticalAlign: "middle" }} />}
                      Downgrade via Portal
                    </button>
                  ) : null
                ) : (
                  <button type="button" className="settings-btn-save" onClick={() => handleCheckout(tier.id as "starter" | "pro")} disabled={checkoutLoading === tier.id} style={{ width: "100%", textAlign: "center" }}>
                    {checkoutLoading === tier.id && <span className="settings-spinner" style={{ width: 14, height: 14, borderWidth: 2, borderTopColor: "white", marginRight: 6, display: "inline-block", verticalAlign: "middle" }} />}
                    {isSubscribed ? "Switch to " : "Subscribe to "}{tier.name}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Overage settings */}
      {isPaid && isOrgAdmin && account && (
        <div className="settings-card">
          <div className="settings-card-title" style={{ marginBottom: 4 }}>Overage settings</div>
          <div className="settings-card-desc" style={{ marginBottom: 20 }}>Control what happens when you exceed your included budget.</div>

          {overageError && (
            <div className="settings-alert settings-alert-error">{overageError}</div>
          )}
          {overageSuccess && (
            <div className="settings-alert settings-alert-success">Overage settings saved.</div>
          )}

          <div className="settings-toggle-row">
            <div>
              <div className="settings-toggle-label" id="toggle-overage-label">Enable pay-as-you-go overage</div>
              <div className="settings-toggle-desc" id="toggle-overage-desc">Continue using agents after exceeding your included budget</div>
            </div>
            <ToggleSwitch
              checked={overageEnabled}
              onChange={handleOverageToggle}
              disabled={overageSaving}
              labelId="toggle-overage-label"
              descId="toggle-overage-desc"
            />
          </div>

          {overageEnabled && (
            <div style={{ borderTop: "1px solid #f0ebe0", paddingTop: 16, marginTop: 0 }}>
              <div className="settings-toggle-label">Maximum overage spending</div>
              <div className="settings-toggle-desc" style={{ marginBottom: 12 }}>Set a cap on overage charges per billing period. Leave empty for no limit.</div>
              <div className="settings-overage-input-row">
                <div className="settings-overage-input-wrap">
                  <input
                    type="number"
                    min="0"
                    step="1"
                    placeholder="No limit"
                    value={overageLimit}
                    onChange={(e) => setOverageLimit(e.target.value)}
                    className="settings-overage-input"
                  />
                </div>
                <button type="button" className="settings-btn-outline" onClick={handleOverageLimitSave} disabled={overageSaving}>
                  {overageSaving && <span className="settings-spinner" style={{ width: 14, height: 14, borderWidth: 2, marginRight: 6, display: "inline-block", verticalAlign: "middle" }} />}
                  Save
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Panel Registry
// =============================================================================

const PANELS: Record<Panel, () => React.ReactElement> = {
  profile: ProfilePanel,
  billing: BillingPanel,
};

// =============================================================================
// Settings Page
// =============================================================================

export default function SettingsPage() {
  const [activePanel, setActivePanel] = useState<Panel>("profile");
  const ActivePanelComponent = PANELS[activePanel];

  const allNavItems = NAV_SECTIONS.flatMap((s) => s.items);

  function handleNavKeyDown(e: React.KeyboardEvent, item: (typeof allNavItems)[number]) {
    const idx = allNavItems.findIndex((n) => n.id === item.id);
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setActivePanel(item.id);
    }
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      e.preventDefault();
      const next = allNavItems[(idx + 1) % allNavItems.length];
      setActivePanel(next.id);
      document.getElementById(`settings-nav-${next.id}`)?.focus();
    }
    if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      e.preventDefault();
      const prev = allNavItems[(idx - 1 + allNavItems.length) % allNavItems.length];
      setActivePanel(prev.id);
      document.getElementById(`settings-nav-${prev.id}`)?.focus();
    }
  }

  return (
    <>
      <style>{settingsStyles}</style>

      {/* Top bar */}
      <header className="settings-topbar" style={{ fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif" }}>
        <div className="settings-topbar-left">
          <Link href="/" className="settings-topbar-logo" aria-label="isol8 home">
            <svg width="32" height="32" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <rect width="100" height="100" rx="22" fill="#06402B" />
              <text x="50" y="68" textAnchor="middle" fontFamily="'Lora', serif" fontStyle="italic" fontSize="52" fill="white">8</text>
            </svg>
          </Link>
          <nav className="settings-topbar-breadcrumb" aria-label="Breadcrumb">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <polyline points="9 18 15 12 9 6" />
            </svg>
            <span className="settings-current" aria-current="page">Settings</span>
          </nav>
        </div>
        <div className="settings-topbar-right">
          <Link href="/chat" className="settings-btn-back-chat">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M19 12H5" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
            Back to Chat
          </Link>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      {/* Main layout */}
      <div className="settings-layout" style={{ fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif", background: "#faf7f2" }}>
        <nav className="settings-nav" aria-label="Settings navigation">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label}>
              <div className="settings-nav-section-label">{section.label}</div>
              <ul className="settings-nav-items" role="tablist">
                {section.items.map((item) => (
                  <li
                    key={item.id}
                    id={`settings-nav-${item.id}`}
                    className={cn("settings-nav-item", activePanel === item.id && "active")}
                    role="tab"
                    tabIndex={activePanel === item.id ? 0 : -1}
                    aria-selected={activePanel === item.id}
                    aria-controls={`panel-${item.id}`}
                    onClick={() => setActivePanel(item.id)}
                    onKeyDown={(e) => handleNavKeyDown(e, item)}
                  >
                    <NavIcon icon={item.icon} />
                    {item.name}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <main className="settings-main">
          <ActivePanelComponent key={activePanel} />
        </main>
      </div>
    </>
  );
}

// =============================================================================
// Styles
// =============================================================================

const settingsStyles = `
  /* Top bar */
  .settings-topbar {
    position: sticky;
    top: 0;
    z-index: 50;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 32px;
    background: rgba(250, 247, 242, .95);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid #e0dbd0;
  }
  .settings-topbar-left {
    display: flex;
    align-items: center;
    gap: 20px;
  }
  .settings-topbar-logo {
    display: inline-flex;
    border-radius: 8px;
    transition: opacity 200ms ease-out;
  }
  .settings-topbar-logo:hover { opacity: .8; }
  .settings-topbar-breadcrumb {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: #59534d;
  }
  .settings-topbar-breadcrumb svg { color: #c5bfb6; }
  .settings-topbar-breadcrumb .settings-current {
    color: #1c1917;
    font-weight: 600;
  }
  .settings-topbar-right {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  .settings-btn-back-chat {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 10px 18px;
    min-height: 44px;
    font-size: 13px;
    font-weight: 600;
    font-family: inherit;
    color: white;
    background: #06402B;
    border: none;
    border-radius: 999px;
    cursor: pointer;
    text-decoration: none;
    transition: background 200ms ease-out;
  }
  .settings-btn-back-chat:hover { background: #054d33; }

  /* Layout */
  .settings-layout {
    display: grid;
    grid-template-columns: 240px 1fr;
    max-width: 1100px;
    margin: 0 auto;
    min-height: calc(100vh - 65px);
  }

  /* Sidebar */
  .settings-nav {
    padding: 32px 0 32px 32px;
    border-right: 1px solid #e0dbd0;
    position: sticky;
    top: 65px;
    height: fit-content;
  }
  .settings-nav-section-label {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #736d67;
    padding: 0 16px;
    margin-bottom: 12px;
  }
  .settings-nav-items {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 0;
    margin: 0;
  }
  .settings-nav-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    min-height: 44px;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 500;
    color: #59534d;
    cursor: pointer;
    transition: color 150ms ease-out, background 150ms ease-out;
    user-select: none;
  }
  .settings-nav-item:hover {
    color: #06402B;
    background: rgba(6,64,43,.04);
  }
  .settings-nav-item.active {
    color: #06402B;
    background: rgba(6,64,43,.08);
    font-weight: 600;
  }
  .settings-nav-item svg { flex-shrink: 0; color: inherit; opacity: .6; }
  .settings-nav-item.active svg { opacity: 1; }

  /* Main content */
  .settings-main {
    padding: 40px 48px;
    font-family: var(--font-dm-sans), 'DM Sans', sans-serif;
    background: #faf7f2;
    color: #1c1917;
    line-height: 1.5;
  }
  .settings-page-title {
    font-family: var(--font-lora-serif), 'Lora', serif;
    font-size: 28px;
    font-weight: 400;
    color: #1c1917;
    margin-bottom: 4px;
    line-height: 1.3;
  }
  .settings-page-desc {
    font-size: 14px;
    color: #59534d;
    margin-bottom: 32px;
    line-height: 1.5;
  }

  /* Panel transitions */
  .settings-panel {
    animation: settingsPanelFadeIn 200ms ease-out;
  }
  @keyframes settingsPanelFadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  /* Cards */
  .settings-card {
    background: white;
    border: 1px solid #e0dbd0;
    border-radius: 16px;
    padding: 28px;
    margin-bottom: 24px;
  }
  .settings-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 24px;
  }
  .settings-card-title {
    font-size: 16px;
    font-weight: 600;
    color: #1c1917;
    line-height: 1.4;
  }
  .settings-card-desc {
    font-size: 13px;
    color: #6b655e;
    margin-top: 2px;
    line-height: 1.5;
  }

  /* Buttons */
  .settings-btn-outline {
    padding: 10px 18px;
    min-height: 44px;
    font-size: 13px;
    font-weight: 600;
    font-family: inherit;
    color: #06402B;
    background: transparent;
    border: 1px solid rgba(6,64,43,.2);
    border-radius: 999px;
    cursor: pointer;
    transition: background 200ms ease-out, border-color 200ms ease-out;
  }
  .settings-btn-outline:hover {
    background: rgba(6,64,43,.05);
    border-color: rgba(6,64,43,.35);
  }
  .settings-btn-outline:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .settings-btn-save {
    padding: 10px 24px;
    min-height: 44px;
    font-size: 14px;
    font-weight: 700;
    font-family: inherit;
    color: white;
    background: #06402B;
    border: none;
    border-radius: 999px;
    cursor: pointer;
    transition: background 200ms ease-out;
  }
  .settings-btn-save:hover { background: #054d33; }
  .settings-btn-save:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* Profile */
  .settings-profile-row {
    display: flex;
    align-items: center;
    gap: 20px;
    margin-bottom: 28px;
  }
  .settings-profile-avatar-lg {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: #06402B;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--font-lora-serif), 'Lora', serif;
    font-size: 24px;
    font-weight: 400;
    color: white;
    flex-shrink: 0;
  }
  .settings-profile-name {
    font-size: 18px;
    font-weight: 600;
    color: #1c1917;
    margin-bottom: 2px;
    line-height: 1.4;
  }
  .settings-profile-email {
    font-size: 14px;
    color: #59534d;
  }
  .settings-profile-badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: #06402B;
    background: rgba(6,64,43,.08);
    border: 1px solid rgba(6,64,43,.15);
    padding: 3px 10px;
    border-radius: 999px;
    margin-left: 8px;
    vertical-align: middle;
  }

  /* Plan rows */
  .settings-plan-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 0;
    border-bottom: 1px solid #f0ebe0;
  }
  .settings-plan-row:last-child { border-bottom: none; padding-bottom: 0; }
  .settings-plan-row:first-child { padding-top: 0; }
  .settings-plan-label {
    font-size: 13px;
    color: #59534d;
    margin-bottom: 4px;
    line-height: 1.4;
  }
  .settings-plan-value {
    font-size: 16px;
    font-weight: 600;
    color: #1c1917;
    line-height: 1.4;
  }
  .settings-price {
    font-family: var(--font-lora-serif), 'Lora', serif;
    font-size: 24px;
  }
  .settings-period {
    font-size: 13px;
    font-weight: 400;
    color: #6b655e;
  }

  /* Usage bar */
  .settings-usage-bar-wrap { margin-top: 8px; }
  .settings-usage-bar-bg {
    height: 6px;
    background: #e0dbd0;
    border-radius: 3px;
    overflow: hidden;
  }
  .settings-usage-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 400ms ease-out;
  }
  .settings-usage-text {
    font-size: 12px;
    color: #6b655e;
    margin-top: 4px;
    line-height: 1.5;
  }

  /* Toggle switch */
  .settings-toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 0;
    border-bottom: 1px solid #f0ebe0;
    gap: 16px;
  }
  .settings-toggle-row:last-child { border-bottom: none; }
  .settings-toggle-label {
    font-size: 14px;
    font-weight: 500;
    color: #1c1917;
    margin-bottom: 2px;
    line-height: 1.4;
  }
  .settings-toggle-desc {
    font-size: 13px;
    color: #6b655e;
    line-height: 1.5;
  }
  .settings-toggle-switch {
    position: relative;
    width: 48px;
    height: 28px;
    flex-shrink: 0;
    cursor: pointer;
    display: inline-block;
  }
  .settings-toggle-switch::after {
    content: '';
    position: absolute;
    inset: -8px 0px;
  }
  .settings-toggle-switch input {
    opacity: 0;
    width: 0;
    height: 0;
    position: absolute;
  }
  .settings-toggle-slider {
    position: absolute;
    cursor: pointer;
    inset: 0;
    background: #c5bfb6;
    border-radius: 14px;
    transition: background 200ms ease-out;
  }
  .settings-toggle-slider::before {
    content: '';
    position: absolute;
    left: 3px;
    top: 3px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: white;
    transition: transform 200ms ease-out;
    will-change: transform;
    box-shadow: 0 1px 3px rgba(0,0,0,.15);
  }
  .settings-toggle-switch input:checked + .settings-toggle-slider {
    background: #06402B;
  }
  .settings-toggle-switch input:checked + .settings-toggle-slider::before {
    transform: translateX(20px);
  }
  .settings-toggle-switch input:focus-visible + .settings-toggle-slider {
    outline: 2px solid #06402B;
    outline-offset: 2px;
    border-radius: 14px;
  }

  /* Plan tier cards */
  .settings-tier-grid {
    display: grid;
    gap: 16px;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    margin-bottom: 24px;
  }
  .settings-tier-card {
    position: relative;
    background: white;
    border: 1px solid #e0dbd0;
    border-radius: 16px;
    padding: 24px;
    transition: border-color 200ms ease-out;
  }
  .settings-tier-card:hover { border-color: #c5bfb6; }
  .settings-tier-card.current {
    border-color: rgba(6,64,43,.4);
    background: rgba(6,64,43,.02);
  }
  .settings-tier-card.popular {
    border-color: rgba(6,64,43,.25);
  }
  .settings-tier-name {
    font-size: 16px;
    font-weight: 600;
    color: #1c1917;
    margin-bottom: 4px;
  }
  .settings-tier-price {
    font-family: var(--font-lora-serif), 'Lora', serif;
    font-size: 28px;
    font-weight: 400;
    color: #1c1917;
    margin-bottom: 16px;
  }
  .settings-tier-price span {
    font-family: var(--font-dm-sans), sans-serif;
    font-size: 13px;
    color: #6b655e;
  }
  .settings-tier-features {
    list-style: none;
    padding: 0;
    margin: 0 0 20px;
    font-size: 13px;
    color: #59534d;
    line-height: 1.6;
  }
  .settings-tier-features li {
    padding: 3px 0;
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }
  .settings-tier-features li::before {
    content: '';
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #06402B;
    margin-top: 7px;
    flex-shrink: 0;
  }
  .settings-popular-badge {
    position: absolute;
    top: -10px;
    left: 16px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: white;
    background: #06402B;
    padding: 3px 10px;
    border-radius: 999px;
  }

  /* Overage input */
  .settings-overage-input-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 12px;
  }
  .settings-overage-input {
    width: 120px;
    padding: 8px 12px 8px 24px;
    min-height: 40px;
    border: 1px solid #e0dbd0;
    border-radius: 10px;
    font-size: 14px;
    font-family: inherit;
    color: #1c1917;
    background: #faf7f2;
    transition: border-color 200ms ease-out, box-shadow 200ms ease-out;
  }
  .settings-overage-input:focus {
    border-color: #06402B;
    box-shadow: 0 0 0 3px rgba(6,64,43,.08);
    outline: none;
  }
  .settings-overage-input-wrap {
    position: relative;
  }
  .settings-overage-input-wrap::before {
    content: '$';
    position: absolute;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 14px;
    color: #6b655e;
    pointer-events: none;
  }

  /* Alert banners */
  .settings-alert {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-radius: 10px;
    font-size: 13px;
    margin-bottom: 16px;
  }
  .settings-alert-error {
    background: rgba(182,48,37,.05);
    border: 1px solid rgba(182,48,37,.2);
    color: #b63025;
  }
  .settings-alert-success {
    background: rgba(6,64,43,.05);
    border: 1px solid rgba(6,64,43,.2);
    color: #06402B;
  }

  /* Loading spinner */
  @keyframes settingsSpin {
    to { transform: rotate(360deg); }
  }
  .settings-spinner {
    width: 20px;
    height: 20px;
    border: 2.5px solid #e0dbd0;
    border-top-color: #06402B;
    border-radius: 50%;
    animation: settingsSpin 0.8s linear infinite;
  }

  /* Restricted message */
  .settings-restricted {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 80px 24px;
    gap: 16px;
  }
  .settings-restricted-title {
    font-size: 18px;
    font-weight: 600;
    color: #1c1917;
  }
  .settings-restricted-desc {
    font-size: 14px;
    color: #59534d;
    max-width: 320px;
  }

  /* Mobile */
  @media (max-width: 768px) {
    .settings-topbar { padding: 12px 16px; }
    .settings-btn-back-chat span { display: none; }
    .settings-layout {
      grid-template-columns: 1fr;
      min-height: auto;
    }
    .settings-nav {
      position: static;
      padding: 16px 16px 0;
      border-right: none;
      border-bottom: 1px solid #e0dbd0;
    }
    .settings-nav-items {
      flex-direction: row;
      gap: 4px;
    }
    .settings-nav-item {
      padding: 8px 14px;
      min-height: 36px;
      font-size: 13px;
    }
    .settings-main {
      padding: 24px 16px;
    }
    .settings-page-title { font-size: 22px; }
    .settings-card { padding: 20px 16px; }
    .settings-card-header { flex-direction: column; align-items: flex-start; gap: 12px; }
    .settings-tier-grid { grid-template-columns: 1fr; }
    .settings-profile-row { flex-direction: column; text-align: center; }
    .settings-profile-avatar-lg { margin: 0 auto; }
  }

  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      transition-duration: 0.01ms !important;
      animation-duration: 0.01ms !important;
    }
  }
`;
