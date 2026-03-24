"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useUser, UserButton } from "@clerk/nextjs";
import { useApi } from "@/lib/api";
import { useBilling } from "@/hooks/useBilling";

type Panel = "profile" | "billing" | "keys" | "preferences" | "danger";

const NAV_SECTIONS = [
  {
    label: "Account",
    items: [
      { id: "profile" as Panel, name: "Profile", icon: "profile" },
      { id: "billing" as Panel, name: "Billing", icon: "billing" },
    ],
  },
  {
    label: "Configuration",
    items: [
      { id: "keys" as Panel, name: "API Keys", icon: "keys" },
      { id: "preferences" as Panel, name: "Preferences", icon: "preferences" },
    ],
  },
  {
    label: "Danger",
    items: [{ id: "danger" as Panel, name: "Delete Account", icon: "danger" }],
  },
];

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
    case "keys":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.78 7.78 5.5 5.5 0 0 1 7.78-7.78zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
        </svg>
      );
    case "preferences":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      );
    case "danger":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        </svg>
      );
    default:
      return null;
  }
}

function ToggleSwitch({
  checked,
  onChange,
  labelId,
  descId,
}: {
  checked: boolean;
  onChange: (val: boolean) => void;
  labelId: string;
  descId: string;
}) {
  return (
    <label className="settings-toggle-switch" aria-labelledby={labelId} aria-describedby={descId}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="settings-toggle-slider" />
    </label>
  );
}

/* ── PROFILE PANEL ── */
function ProfilePanel() {
  const { user } = useUser();
  const [firstName, setFirstName] = useState(user?.firstName ?? "");
  const [lastName, setLastName] = useState(user?.lastName ?? "");

  const email = user?.primaryEmailAddress?.emailAddress ?? "";
  const initials = `${(user?.firstName ?? "")[0] ?? ""}${(user?.lastName ?? "")[0] ?? ""}`.toUpperCase();

  return (
    <div className="settings-panel" id="panel-profile" role="tabpanel">
      <h1 className="settings-page-title">Profile</h1>
      <p className="settings-page-desc">Manage your personal information and account details.</p>

      <div className="settings-card">
        <div className="settings-profile-row">
          <div className="settings-profile-avatar-lg" aria-hidden="true">{initials}</div>
          <div className="settings-profile-info">
            <div className="settings-profile-name">
              {user?.fullName ?? "User"} <span className="settings-profile-badge">Pro</span>
            </div>
            <div className="settings-profile-email">{email}</div>
          </div>
        </div>
        <div className="settings-field-grid">
          <div className="settings-field-group">
            <label className="settings-field-label" htmlFor="field-firstname">First name</label>
            <input
              className="settings-field-input"
              id="field-firstname"
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              autoComplete="given-name"
            />
          </div>
          <div className="settings-field-group">
            <label className="settings-field-label" htmlFor="field-lastname">Last name</label>
            <input
              className="settings-field-input"
              id="field-lastname"
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              autoComplete="family-name"
            />
          </div>
          <div className="settings-field-group" style={{ gridColumn: "1 / -1" }}>
            <label className="settings-field-label" htmlFor="field-email">Email</label>
            <input
              className="settings-field-input"
              id="field-email"
              type="email"
              value={email}
              disabled
              autoComplete="email"
              aria-describedby="email-hint"
            />
            <span id="email-hint" style={{ fontSize: 12, color: "#6b655e", marginTop: 6, display: "block", lineHeight: 1.5 }}>
              Managed by your authentication provider.
            </span>
          </div>
        </div>
        <div className="settings-save-bar">
          <button type="button" className="settings-btn-save">Save changes</button>
        </div>
      </div>
    </div>
  );
}

/* ── BILLING PANEL ── */
function BillingPanel() {
  const { account, openPortal } = useBilling();

  const plan = account?.plan_tier ?? "Pro";
  const budget = account?.current_period?.included_budget ?? 75;
  const usage = account?.current_period?.used ?? 0;
  const pct = account?.current_period?.percent_used ?? (budget > 0 ? Math.round((usage / budget) * 100) : 0);
  const renewal = account?.current_period?.end ?? "—";

  return (
    <div className="settings-panel" id="panel-billing" role="tabpanel">
      <h1 className="settings-page-title">Billing</h1>
      <p className="settings-page-desc">Manage your subscription and view usage.</p>

      <div className="settings-card">
        <div className="settings-card-header">
          <div className="settings-card-header-text">
            <div className="settings-card-title">Current Plan</div>
            <div className="settings-card-desc">Your subscription and usage this billing cycle.</div>
          </div>
          <button type="button" className="settings-btn-outline" onClick={() => openPortal?.()}>
            Manage in Stripe
          </button>
        </div>
        <div className="settings-plan-row">
          <div className="settings-plan-info">
            <div className="settings-plan-label">Plan</div>
            <div className="settings-plan-value">{plan}</div>
          </div>
          <div className="settings-plan-info" style={{ textAlign: "right" }}>
            <div className="settings-plan-label">Monthly</div>
            <div className="settings-plan-value">
              <span className="settings-price">${budget}</span>{" "}
              <span className="settings-period">/mo</span>
            </div>
          </div>
        </div>
        <div className="settings-plan-row">
          <div className="settings-plan-info">
            <div className="settings-plan-label">Usage this cycle</div>
            <div className="settings-plan-value">${usage.toFixed(2)}</div>
            <div
              className="settings-usage-bar-wrap"
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Budget usage"
            >
              <div className="settings-usage-bar-bg">
                <div className="settings-usage-bar-fill" style={{ width: `${pct}%` }} />
              </div>
              <div className="settings-usage-text">{pct}% of ${budget} budget used</div>
            </div>
          </div>
          <div className="settings-plan-info" style={{ textAlign: "right" }}>
            <div className="settings-plan-label">Renews</div>
            <div className="settings-plan-value">{renewal}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── API KEYS PANEL ── */
function ApiKeysPanel() {
  const api = useApi();

  const placeholderKeys = [
    { id: "1", provider: "Anthropic", mask: "sk-ant-...dpKw", color: "#FF6B35" },
    { id: "2", provider: "OpenAI", mask: "sk-proj-...3xNq", color: "#10A37F" },
  ];

  return (
    <div className="settings-panel" id="panel-keys" role="tabpanel">
      <h1 className="settings-page-title">API Keys</h1>
      <p className="settings-page-desc">Bring your own keys for LLM providers.</p>

      <div className="settings-card">
        <div className="settings-card-header">
          <div className="settings-card-header-text">
            <div className="settings-card-title">Your Keys</div>
            <div className="settings-card-desc">Keys are encrypted at rest and never leave our servers.</div>
          </div>
          <button type="button" className="settings-btn-outline">+ Add Key</button>
        </div>
        <div className="settings-key-list" role="list">
          {placeholderKeys.map((key) => (
            <div className="settings-key-row" role="listitem" key={key.id}>
              <div className="settings-key-left">
                <div className="settings-key-provider-icon" aria-hidden="true">
                  {key.provider === "Anthropic" ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <path d="M12 2L2 7l10 5 10-5-10-5z" fill={key.color} />
                      <path d="M2 17l10 5 10-5" stroke={key.color} strokeWidth="2" fill="none" />
                      <path d="M2 12l10 5 10-5" stroke={key.color} strokeWidth="2" fill="none" />
                    </svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke={key.color} strokeWidth="2" />
                      <path d="M8 12h8M12 8v8" stroke={key.color} strokeWidth="2" strokeLinecap="round" />
                    </svg>
                  )}
                </div>
                <div>
                  <div className="settings-key-name">{key.provider}</div>
                  <div className="settings-key-mask">{key.mask}</div>
                </div>
              </div>
              <div className="settings-key-actions">
                <span className="settings-key-status active" role="status">Active</span>
                <button type="button" className="settings-btn-danger-text" aria-label={`Remove ${key.provider} key`}>
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── PREFERENCES PANEL ── */
function PreferencesPanel() {
  const [emailNotifs, setEmailNotifs] = useState(true);
  const [weeklyDigest, setWeeklyDigest] = useState(true);
  const [desktopNotifs, setDesktopNotifs] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const [compactChat, setCompactChat] = useState(false);

  return (
    <div className="settings-panel" id="panel-preferences" role="tabpanel">
      <h1 className="settings-page-title">Preferences</h1>
      <p className="settings-page-desc">Customize your isol8 experience.</p>

      <div className="settings-card">
        <div className="settings-card-title" style={{ marginBottom: 16 }}>Notifications</div>
        <div className="settings-toggle-row">
          <div className="settings-toggle-info">
            <div className="settings-toggle-label" id="toggle-email-label">Email notifications</div>
            <div className="settings-toggle-desc" id="toggle-email-desc">Receive email updates about your agent&apos;s activity.</div>
          </div>
          <ToggleSwitch checked={emailNotifs} onChange={setEmailNotifs} labelId="toggle-email-label" descId="toggle-email-desc" />
        </div>
        <div className="settings-toggle-row">
          <div className="settings-toggle-info">
            <div className="settings-toggle-label" id="toggle-digest-label">Weekly usage digest</div>
            <div className="settings-toggle-desc" id="toggle-digest-desc">Summary of your agent&apos;s tasks and usage each week.</div>
          </div>
          <ToggleSwitch checked={weeklyDigest} onChange={setWeeklyDigest} labelId="toggle-digest-label" descId="toggle-digest-desc" />
        </div>
        <div className="settings-toggle-row">
          <div className="settings-toggle-info">
            <div className="settings-toggle-label" id="toggle-desktop-label">Desktop notifications</div>
            <div className="settings-toggle-desc" id="toggle-desktop-desc">Push notifications from the desktop app.</div>
          </div>
          <ToggleSwitch checked={desktopNotifs} onChange={setDesktopNotifs} labelId="toggle-desktop-label" descId="toggle-desktop-desc" />
        </div>
      </div>

      <div className="settings-card">
        <div className="settings-card-title" style={{ marginBottom: 16 }}>Appearance</div>
        <div className="settings-toggle-row">
          <div className="settings-toggle-info">
            <div className="settings-toggle-label" id="toggle-dark-label">Dark mode</div>
            <div className="settings-toggle-desc" id="toggle-dark-desc">Switch to dark theme across the app.</div>
          </div>
          <ToggleSwitch checked={darkMode} onChange={setDarkMode} labelId="toggle-dark-label" descId="toggle-dark-desc" />
        </div>
        <div className="settings-toggle-row">
          <div className="settings-toggle-info">
            <div className="settings-toggle-label" id="toggle-compact-label">Compact chat</div>
            <div className="settings-toggle-desc" id="toggle-compact-desc">Reduce spacing in the chat interface.</div>
          </div>
          <ToggleSwitch checked={compactChat} onChange={setCompactChat} labelId="toggle-compact-label" descId="toggle-compact-desc" />
        </div>
      </div>
    </div>
  );
}

/* ── DELETE ACCOUNT PANEL ── */
function DeleteAccountPanel() {
  return (
    <div className="settings-panel" id="panel-danger" role="tabpanel">
      <h1 className="settings-page-title">Delete Account</h1>
      <p className="settings-page-desc">Permanently remove your account and all associated data.</p>

      <div className="settings-card--danger">
        <div className="settings-danger-title">This action is irreversible</div>
        <p className="settings-danger-text">
          Deleting your account will immediately stop your agent container, remove all workspace files
          from EFS, cancel your Stripe subscription, and permanently delete your data. This cannot be
          undone.
        </p>
        <button type="button" className="settings-btn-danger-outline">Delete my account</button>
      </div>
    </div>
  );
}

const PANELS: Record<Panel, () => React.ReactElement> = {
  profile: ProfilePanel,
  billing: BillingPanel,
  keys: ApiKeysPanel,
  preferences: PreferencesPanel,
  danger: DeleteAccountPanel,
};

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
      <style>{`
        /* ── TOP BAR ── */
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
          transition: background 200ms ease-out, box-shadow 200ms ease-out;
        }
        .settings-btn-back-chat:hover { background: #054d33; }
        .settings-btn-back-chat:active { background: #043d27; }

        /* ── LAYOUT ── */
        .settings-layout {
          display: grid;
          grid-template-columns: 240px 1fr;
          max-width: 1100px;
          margin: 0 auto;
          min-height: calc(100vh - 65px);
        }

        /* ── SIDEBAR ── */
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
        .settings-nav-section-label:not(:first-child) {
          margin-top: 28px;
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
        .settings-nav-item:active {
          background: rgba(6,64,43,.1);
        }
        .settings-nav-item.active {
          color: #06402B;
          background: rgba(6,64,43,.08);
          font-weight: 600;
        }
        .settings-nav-item svg { flex-shrink: 0; color: inherit; opacity: .6; }
        .settings-nav-item.active svg { opacity: 1; }
        .settings-nav-item[data-panel="danger"] { color: #b63025; }
        .settings-nav-item[data-panel="danger"]:hover { color: #962d23; background: rgba(182,48,37,.05); }
        .settings-nav-item[data-panel="danger"].active { color: #b63025; background: rgba(182,48,37,.08); }

        /* ── MAIN CONTENT ── */
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

        /* ── PANEL TRANSITIONS ── */
        .settings-panel {
          animation: settingsPanelFadeIn 200ms ease-out;
        }
        @keyframes settingsPanelFadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }

        /* ── CARDS ── */
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

        /* ── PROFILE ── */
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

        /* ── FORM FIELDS ── */
        .settings-field-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
        }
        .settings-field-group { margin-bottom: 0; }
        .settings-field-label {
          display: block;
          font-size: 13px;
          font-weight: 500;
          color: #433e39;
          margin-bottom: 6px;
          line-height: 1.4;
        }
        .settings-field-input {
          width: 100%;
          padding: 10px 14px;
          min-height: 44px;
          border: 1px solid #e0dbd0;
          border-radius: 10px;
          font-size: 14px;
          font-family: inherit;
          color: #1c1917;
          background: #faf7f2;
          transition: border-color 200ms ease-out, box-shadow 200ms ease-out, background 200ms ease-out;
        }
        .settings-field-input:hover { border-color: #c5bfb6; }
        .settings-field-input:focus {
          border-color: #06402B;
          box-shadow: 0 0 0 3px rgba(6,64,43,.08);
          background: white;
          outline: none;
        }
        .settings-field-input:disabled {
          color: #6b655e;
          cursor: not-allowed;
          opacity: .7;
        }

        /* ── SAVE BAR ── */
        .settings-save-bar {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          margin-top: 28px;
        }

        /* ── PLAN CARD ── */
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

        /* ── USAGE BAR ── */
        .settings-usage-bar-wrap {
          margin-top: 8px;
          width: 200px;
        }
        .settings-usage-bar-bg {
          height: 6px;
          background: #e0dbd0;
          border-radius: 3px;
          overflow: hidden;
        }
        .settings-usage-bar-fill {
          height: 100%;
          background: #06402B;
          border-radius: 3px;
          transition: width 400ms ease-out;
        }
        .settings-usage-text {
          font-size: 12px;
          color: #6b655e;
          margin-top: 4px;
          line-height: 1.5;
        }

        /* ── BUTTONS ── */
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
          transition: background 200ms ease-out, border-color 200ms ease-out, color 200ms ease-out;
        }
        .settings-btn-outline:hover {
          background: rgba(6,64,43,.05);
          border-color: rgba(6,64,43,.35);
        }
        .settings-btn-outline:active {
          background: rgba(6,64,43,.1);
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
          transition: background 200ms ease-out, box-shadow 200ms ease-out;
        }
        .settings-btn-save:hover { background: #054d33; }
        .settings-btn-save:active { background: #043d27; }
        .settings-btn-danger-text {
          font-size: 13px;
          font-weight: 500;
          color: #b63025;
          background: none;
          border: none;
          cursor: pointer;
          padding: 10px 12px;
          min-height: 44px;
          border-radius: 6px;
          transition: color 200ms ease-out, background 200ms ease-out;
        }
        .settings-btn-danger-text:hover {
          color: #8c221a;
          background: rgba(182,48,37,.06);
        }
        .settings-btn-danger-text:active {
          background: rgba(182,48,37,.12);
        }
        .settings-btn-danger-outline {
          padding: 10px 20px;
          min-height: 44px;
          font-size: 14px;
          font-weight: 600;
          font-family: inherit;
          color: #b63025;
          background: transparent;
          border: 1px solid rgba(182,48,37,.25);
          border-radius: 999px;
          cursor: pointer;
          transition: background 200ms ease-out, border-color 200ms ease-out, color 200ms ease-out;
        }
        .settings-btn-danger-outline:hover {
          background: rgba(182,48,37,.06);
          border-color: rgba(182,48,37,.4);
        }
        .settings-btn-danger-outline:active {
          background: rgba(182,48,37,.12);
        }

        /* ── API KEY ROW ── */
        .settings-key-list { display: flex; flex-direction: column; gap: 12px; }
        .settings-key-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 14px 16px;
          background: #faf7f2;
          border: 1px solid #e0dbd0;
          border-radius: 12px;
          transition: border-color 200ms ease-out;
        }
        .settings-key-row:hover { border-color: #c5bfb6; }
        .settings-key-left {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .settings-key-provider-icon {
          width: 36px;
          height: 36px;
          border-radius: 8px;
          background: white;
          border: 1px solid #e0dbd0;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .settings-key-name {
          font-size: 14px;
          font-weight: 600;
          color: #1c1917;
          line-height: 1.4;
        }
        .settings-key-mask {
          font-size: 12px;
          color: #6b655e;
          font-family: ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace;
        }
        .settings-key-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .settings-key-status {
          font-size: 12px;
          font-weight: 600;
          padding: 3px 10px;
          border-radius: 999px;
        }
        .settings-key-status.active {
          color: #06402B;
          background: rgba(6,64,43,.08);
        }

        /* ── TOGGLE SWITCH ── */
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

        /* ── DANGER ZONE ── */
        .settings-card--danger {
          background: white;
          border: 1px solid rgba(182,48,37,.2);
          border-radius: 16px;
          padding: 28px;
          margin-bottom: 24px;
        }
        .settings-danger-title {
          font-size: 16px;
          font-weight: 600;
          color: #b63025;
          margin-bottom: 8px;
          line-height: 1.4;
        }
        .settings-danger-text {
          font-size: 14px;
          color: #59534d;
          line-height: 1.7;
          margin-bottom: 24px;
        }

        /* ── MOBILE ── */
        @media (max-width: 768px) {
          .settings-layout {
            grid-template-columns: 1fr;
          }
          .settings-nav {
            position: relative;
            top: 0;
            border-right: none;
            border-bottom: 1px solid #e0dbd0;
            padding: 12px 16px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
          }
          .settings-nav-items {
            flex-direction: row;
            gap: 4px;
          }
          .settings-nav-item {
            white-space: nowrap;
            padding: 10px 16px;
            min-height: 44px;
          }
          .settings-nav-section-label { display: none; }
          .settings-main { padding: 24px 16px; }
          .settings-field-grid { grid-template-columns: 1fr; }
          .settings-topbar { padding: 12px 16px; }
          .settings-plan-row {
            flex-direction: column;
            align-items: flex-start;
            gap: 12px;
          }
          .settings-card-header {
            flex-direction: column;
            align-items: flex-start;
            gap: 12px;
          }
          .settings-usage-bar-wrap {
            width: 100%;
          }
        }

        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            transition-duration: 0.01ms !important;
            animation-duration: 0.01ms !important;
          }
        }
      `}</style>

      {/* ── TOP BAR ── */}
      <header className="settings-topbar" role="banner" style={{ fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif" }}>
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

      {/* ── MAIN LAYOUT ── */}
      <div className="settings-layout" style={{ fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif", background: "#faf7f2" }}>

        {/* SIDEBAR NAV */}
        <nav className="settings-nav" aria-label="Settings navigation">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label}>
              <div className="settings-nav-section-label">{section.label}</div>
              <ul className="settings-nav-items" role="tablist">
                {section.items.map((item) => (
                  <li
                    key={item.id}
                    id={`settings-nav-${item.id}`}
                    className={`settings-nav-item${activePanel === item.id ? " active" : ""}`}
                    data-panel={item.id}
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

        {/* CONTENT PANELS */}
        <main className="settings-main">
          <ActivePanelComponent key={activePanel} />
        </main>
      </div>
    </>
  );
}