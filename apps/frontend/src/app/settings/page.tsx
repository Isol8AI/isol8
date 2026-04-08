"use client";

import "./settings.css";
import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useUser, UserButton, useOrganization } from "@clerk/nextjs";
import { useBilling } from "@/hooks/useBilling";
import { MyChannelsSection } from "@/components/settings/MyChannelsSection";
import { cn } from "@/lib/utils";

// =============================================================================
// Types & Navigation
// =============================================================================

type Panel = "profile" | "billing" | "channels";

const NAV_SECTIONS = [
  {
    label: "Account",
    items: [
      { id: "profile" as Panel, name: "Profile", icon: "profile" },
      { id: "billing" as Panel, name: "Billing", icon: "billing" },
      { id: "channels" as Panel, name: "Channels", icon: "channels" },
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
    case "channels":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
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
// Channels Panel
// =============================================================================

function ChannelsPanel() {
  return (
    <div className="settings-panel" id="panel-channels" role="tabpanel">
      <h1 className="settings-page-title">Channels</h1>
      <p className="settings-page-desc">Link your personal Telegram, Discord, and Slack accounts to your organization&apos;s bots.</p>
      <MyChannelsSection />
    </div>
  );
}

// =============================================================================
// Panel Registry
// =============================================================================

const PANELS: Record<Panel, () => React.ReactElement> = {
  profile: ProfilePanel,
  billing: BillingPanel,
  channels: ChannelsPanel,
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

