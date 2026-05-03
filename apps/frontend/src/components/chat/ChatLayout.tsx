"use client";

import "./ChatLayout.css";
import { useEffect, useRef, useState } from "react";
import { usePostHog } from "posthog-js/react";
import { useAuth, useOrganization, useOrganizationList, useUser, UserButton } from "@clerk/nextjs";
import { useRouter, useSearchParams } from "next/navigation";
import { Settings, Plus, Bot, CheckCircle, CreditCard, Menu, X, FolderOpen, Pencil, Trash2, Users } from "lucide-react";
import Link from "next/link";

import { ProvisioningStepper } from "@/components/chat/ProvisioningStepper";
import { GallerySection } from "@/components/chat/GallerySection";
import { HealthIndicator } from "@/components/chat/HealthIndicator";
import { TrialBanner } from "@/components/chat/TrialBanner";
import { OutOfCreditsBanner } from "@/components/chat/OutOfCreditsBanner";
import { useGateway } from "@/hooks/useGateway";
import { useApi } from "@/lib/api";
import { useAgents, getAgentModelString, agentDisplayName, type Agent } from "@/hooks/useAgents";
import { useBilling } from "@/hooks/useBilling";
import { ControlSidebar } from "@/components/control/ControlSidebar";
import { FileViewer } from "@/components/chat/FileViewer";
import { AgentCreateDialog, AgentRenameDialog, AgentDeleteDialog } from "@/components/chat/AgentDialogs";

interface ChatLayoutProps {
  children: React.ReactNode;
  activeView: "chat" | "control";
  onViewChange: (view: "chat" | "control") => void;
  activePanel?: string;
  onPanelChange?: (panel: string) => void;
  fileViewerOpen?: boolean;
  activeFilePath?: string | null;
  onOpenFile?: (path: string) => void;
  onCloseFileViewer?: () => void;
}

function dispatchSelectAgentEvent(agentId: string): void {
  window.dispatchEvent(
    new CustomEvent("selectAgent", { detail: { agentId } }),
  );
}

export function ChatLayout({
  children,
  activeView,
  onViewChange,
  activePanel,
  onPanelChange,
  fileViewerOpen,
  activeFilePath,
  onOpenFile,
  onCloseFileViewer,
}: ChatLayoutProps): React.ReactElement {
  const posthog = usePostHog();
  const { isSignedIn, getToken } = useAuth();
  const { user, isLoaded: userLoaded } = useUser();
  const { organization, isLoaded: orgLoaded } = useOrganization();
  // Watch all of the user's org memberships so we can auto-activate the
  // first one on fresh logins — Clerk doesn't persist active-org state
  // across sessions, so without this a user who created an org on laptop A
  // would land on /onboarding on laptop B despite already being a member.
  const { userMemberships, userInvitations, setActive, isLoaded: orgListLoaded } = useOrganizationList({
    userMemberships: true,
    userInvitations: true,
  });
  const router = useRouter();
  const api = useApi();
  const { agents, defaultId, createAgent, deleteAgent, updateAgent } = useAgents();
  const { refresh: refreshBilling, account, isSubscribed } = useBilling();
  const { nodeConnected } = useGateway();
  const searchParams = useSearchParams();

  // Cross-subdomain link to the Paperclip company portal. Cross-subdomain
  // navigation must use a plain <a> (not next/link) — Next's Link is for
  // internal app routing. The user's Clerk session cookie is scoped to
  // .isol8.co, so the navigation keeps them signed in; the backend proxy
  // router handles the company.isol8.co request flow.
  //
  // We derive the URL from NEXT_PUBLIC_API_URL — already set per-env in
  // Vercel — instead of requiring a separate NEXT_PUBLIC_COMPANY_URL var.
  // CLAUDE.md mandates version-controlled config, and adding another env
  // var that mirrors information already encoded in NEXT_PUBLIC_API_URL
  // is exactly the kind of drift we want to avoid (the dev frontend
  // shipped pointing at https://company.isol8.co for weeks because the
  // env var was never set in Vercel for Preview).
  //
  // NEXT_PUBLIC_* is baked at build time, so the value is identical on
  // SSR and client — no hydration mismatch. The override path
  // (NEXT_PUBLIC_COMPANY_URL) is kept for explicit overrides like local
  // dev or a future split-stack.
  const companyUrl = (() => {
    const override = process.env.NEXT_PUBLIC_COMPANY_URL;
    if (override) return override;
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
    // Prod (api.isol8.co) → company.isol8.co; anything else (dev,
    // staging, preview) → {env}.company.isol8.co. Matches the
    // Vercel-hosted layout: company.isol8.co is the prod hostname,
    // {env}.company.isol8.co for non-prod.
    if (/\/\/api\.isol8\.co/.test(apiUrl)) return "https://company.isol8.co";
    const m = apiUrl.match(/\/\/api-([^.]+)\.isol8\.co/);
    const env = m ? m[1] : "dev";
    return `https://${env}.company.isol8.co`;
  })();

  const [userSelectedId, setUserSelectedId] = useState<string | null>(null);
  // Stripe Checkout returns either ?subscription=success (legacy) or
  // ?checkout=success (new trial-checkout flow). Both should trigger the
  // billing-refresh + URL-cleanup effect. Codex P2 on PR #393.
  //
  // Two separate state slices keyed off the same URL param so the banner
  // and the polling lifecycle are independent — banner auto-dismisses at
  // 5s, polling continues for up to 30s. Without this split the
  // banner-dismiss tear-down was clobbering the poll interval. Codex P2
  // on PR #399.
  const cameFromCheckout =
    searchParams.get("subscription") === "success" ||
    searchParams.get("checkout") === "success";
  const [showSubscriptionSuccess, setShowSubscriptionSuccess] = useState(() => cameFromCheckout);
  const [pollingForWebhook, setPollingForWebhook] = useState(() => cameFromCheckout);
  const [recoveryTriggered, setRecoveryTriggered] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [createFormOpen, setCreateFormOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Agent | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Agent | null>(null);

  // Derive effective agent: user selection > default > first agent
  const currentAgentId = userSelectedId ?? defaultId ?? agents[0]?.id ?? null;

  const subscriptionStatus = account?.subscription_status ?? null;
  const userName = user?.fullName || user?.firstName || "User";
  const userInitials = userName
    .split(" ")
    .map((n: string) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  // Onboarding / context gate. Three orthogonal states, in priority order:
  //
  // 1. Needs onboarding: never signed the "personal or org" picker. Send
  //    them to /onboarding.
  // 2. Needs auto-activate: already completed onboarding (personal or org)
  //    AND has at least one org membership BUT no org is active in this
  //    Clerk session. Fresh login on a new device lands here. We call
  //    setActive to pick the first membership, which flips `organization`
  //    on the next render and we continue into /chat.
  // 3. Ready: either personal (no memberships, onboarded=true) or org
  //    (organization is non-null).
  //
  // Both the onboarding redirect AND the auto-activate branch BLOCK the
  // main render (early return below). This is critical: we must not let
  // useAgents / useBilling / useContainerStatus / api.syncUser run while
  // the JWT is in a transient personal-context state, or those calls
  // resolve owner_id to the user_id and create phantom personal billing
  // rows. The 3 orphan billing rows we see in prod today came from exactly
  // this race.
  const clerkLoaded = userLoaded && orgLoaded && orgListLoaded;
  const isOnboarded = (user?.unsafeMetadata as Record<string, unknown> | undefined)?.onboarded === true;
  const hasMemberships = (userMemberships?.data?.length ?? 0) > 0;
  const hasPendingInvitations = (userInvitations?.data?.length ?? 0) > 0;

  // A user needs onboarding if they have neither the flag nor any org
  // memberships AND no pending invitations. If they have memberships they're
  // effectively already past the personal/org decision — we just need to
  // activate one. If they have pending invitations, send them to onboarding
  // where they can accept.
  const needsOnboarding = clerkLoaded && isSignedIn === true && !isOnboarded && !hasMemberships && !hasPendingInvitations && !organization;
  const needsAutoActivate = clerkLoaded && isSignedIn === true && !organization && hasMemberships;
  // Users with pending invitations who haven't onboarded should also go to
  // /onboarding where they'll see the invitation acceptance UI.
  const needsInvitationFlow = clerkLoaded && isSignedIn === true && !isOnboarded && !hasMemberships && hasPendingInvitations && !organization;

  useEffect(() => {
    if (needsOnboarding || needsInvitationFlow) {
      router.replace("/onboarding");
    }
  }, [needsOnboarding, needsInvitationFlow, router]);

  useEffect(() => {
    if (!needsAutoActivate || !setActive) return;
    const first = userMemberships?.data?.[0];
    if (!first) return;
    setActive({ organization: first.organization.id }).catch((err: unknown) => {
      console.error("Auto-activate first org membership failed:", err);
    });
  }, [needsAutoActivate, setActive, userMemberships]);

  useEffect(() => {
    if (!isSignedIn) return;
    // Skip /users/sync while we're still resolving the user's org context.
    // Firing sync with a pre-activation JWT used to create phantom personal
    // billing rows — the backend no longer does that write, but we gate
    // here too so other context-sensitive endpoints called from sync
    // paths (future-proofing) don't misresolve owner_id either.
    if (needsAutoActivate || needsOnboarding || needsInvitationFlow) return;
    api.syncUser().catch((err: unknown) => console.error("User sync failed:", err));
  }, [isSignedIn, api, needsAutoActivate, needsOnboarding, needsInvitationFlow]);

  // Dispatch DOM event so page.tsx picks up the current agent (external system sync)
  const lastDispatchedRef = useRef<string | null>(null);
  useEffect(() => {
    if (currentAgentId && currentAgentId !== lastDispatchedRef.current) {
      lastDispatchedRef.current = currentAgentId;
      dispatchSelectAgentEvent(currentAgentId);
    }
  }, [currentAgentId]);

  // Post-checkout confirmation: refresh billing + clean URL.
  // Strip ONLY ?checkout / ?subscription, preserving ?provider= so the
  // ProvisioningStepper can still render the provider-specific step
  // (ChatGPTOAuthStep / ByoKeyStep / CreditsStep) — without this, the
  // OAuth + BYO paths break because the wizard never gets to the step
  // that collects the user's credentials.
  useEffect(() => {
    if (!showSubscriptionSuccess) return;

    refreshBilling();
    const params = new URLSearchParams(searchParams.toString());
    params.delete("checkout");
    params.delete("subscription");
    const remaining = params.toString();
    router.replace(`/chat${remaining ? `?${remaining}` : ""}`, { scroll: false });

    const dismissTimer = setTimeout(() => setShowSubscriptionSuccess(false), 5000);
    return () => clearTimeout(dismissTimer);
  }, [showSubscriptionSuccess, refreshBilling, router, searchParams]);

  // Post-credit-checkout return. Stripe sends users back with
  // ?credits=success (or =cancel) when they finish the credit top-up
  // flow. We just strip the param — the credit balance refresh happens
  // automatically via useCredits' refreshInterval/onFocus, and the
  // ProvisioningStepper re-evaluates needsProviderStep on URL change so
  // the wizard advances out of CreditsStep on success.
  const cameFromCreditsCheckout = searchParams.get("credits") !== null;
  useEffect(() => {
    if (!cameFromCreditsCheckout) return;
    const params = new URLSearchParams(searchParams.toString());
    params.delete("credits");
    const remaining = params.toString();
    router.replace(`/chat${remaining ? `?${remaining}` : ""}`, { scroll: false });
  }, [cameFromCreditsCheckout, router, searchParams]);

  // Race against Stripe webhook delivery: the user returns from Checkout
  // before customer.subscription.created lands at our webhook endpoint
  // (typically <2s, but variable). Without polling, the wizard would
  // bounce back to the ProviderPicker because is_subscribed stays False
  // until the webhook persists subscription_status. Poll every 2s for up
  // to 30s — once is_subscribed flips True we stop early, otherwise we
  // give up so we don't poll forever.
  //
  // Keyed on `pollingForWebhook` (independent of the banner state) so the
  // banner's 5s auto-dismiss doesn't cancel the longer poll loop.
  // Codex P2 on PR #399.
  useEffect(() => {
    if (!pollingForWebhook || isSubscribed) return;
    const pollInterval = setInterval(() => refreshBilling(), 2000);
    const giveUpTimer = setTimeout(() => setPollingForWebhook(false), 30_000);
    return () => {
      clearInterval(pollInterval);
      clearTimeout(giveUpTimer);
    };
  }, [pollingForWebhook, isSubscribed, refreshBilling]);

  function handleSelectAgent(agentId: string): void {
    posthog?.capture("agent_selected", { agent_id: agentId });
    setUserSelectedId(agentId);
    dispatchSelectAgentEvent(agentId);
    setSidebarOpen(false);
  }

  async function handleCreateAgent(): Promise<void> {
    setCreateFormOpen(true);
  }

  // Block the whole chat shell until Clerk hydration + onboarding state are
  // settled AND any pending org auto-activation has landed. This is the
  // hinge for the personal/org race fix: if we render ProvisioningStepper
  // (or any owner_id-aware hook) before the JWT has finished flipping into
  // its final context, it fires POST /container/provision and /billing
  // reads with a stale JWT and we end up with orphan personal rows for a
  // user who was always meant to be an org member.
  if (!clerkLoaded || isSignedIn !== true || needsOnboarding || needsInvitationFlow || needsAutoActivate) {
    return (
      <div className="app-shell" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <div style={{ color: "#6b6b6b", fontSize: 14 }}>Loading…</div>
      </div>
    );
  }

  return (
    <>

      <div className={`app-shell${fileViewerOpen ? " with-file-viewer" : ""}`}>
        <div className={`sidebar-backdrop${sidebarOpen ? " visible" : ""}`} onClick={() => setSidebarOpen(false)} />
        <div className={`cream-sidebar${sidebarOpen ? " mobile-open" : ""}`}>
          {/* Header */}
          <div className="sidebar-header">
            <div className="sidebar-logo">
              <span className="sidebar-logo-8">8</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <a
                href={companyUrl}
                onClick={async (e) => {
                  // The proxy at company.isol8.co accepts a Clerk JWT in the
                  // ?__t= query param as its initial-handshake auth source.
                  // Top-level browser navigation can't carry an Authorization
                  // header, and Clerk's __session cookie is host-scoped to
                  // dev.isol8.co (doesn't cross subdomains in dev mode), so
                  // appending the JWT here is the only way to get the user
                  // signed in on company.isol8.co without a second sign-in.
                  // Backend strips ?__t= via 302 immediately after minting
                  // the session cookie, so the token leaves the URL bar
                  // within ~50ms. JWT TTL is ~60s (Clerk default).
                  e.preventDefault();
                  try {
                    const token = await getToken();
                    if (!token) {
                      // No active session — fall back to plain navigation;
                      // backend will redirect to /chat with the right hint.
                      window.location.href = companyUrl;
                      return;
                    }
                    const url = new URL(companyUrl);
                    url.searchParams.set("__t", token);
                    window.location.href = url.toString();
                  } catch (err) {
                    console.error("Teams handoff: getToken failed", err);
                    window.location.href = companyUrl;
                  }
                }}
                target="_self"
                rel="noopener"
                className="sidebar-settings-link"
                aria-label="Teams"
                title="Teams"
              >
                <Users size={18} />
              </a>
              <Link href="/settings" className="sidebar-settings-link">
                <Settings size={18} />
              </Link>
              <button className="mobile-hamburger" onClick={() => setSidebarOpen(false)} aria-label="Close menu" style={{ display: sidebarOpen ? "flex" : undefined }}>
                <X size={18} />
              </button>
            </div>
          </div>

          {/* Health Indicator — hidden until the user has a subscription. The
              indicator reports the state of an existing per-user container; if
              the user hasn't subscribed there's no container to indicate, and
              "Starting..." is misleading. */}
          {isSubscribed && (
            <HealthIndicator onRecoveryReprovision={() => setRecoveryTriggered(true)} />
          )}

          {/* Node Status */}
          {nodeConnected && (
            <div style={{
              padding: '4px 12px',
              fontSize: '12px',
              color: '#16a34a',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}>
              <span style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                backgroundColor: '#16a34a',
                display: 'inline-block',
              }} />
              Local tools available
            </div>
          )}

          {/* Tab Switcher */}
          <div className="tab-switcher">
            <button
              className={`tab-btn${activeView === "chat" ? " active" : ""}`}
              onClick={() => { onViewChange("chat"); setSidebarOpen(false); }}
            >
              Chat
            </button>
            <button
              className={`tab-btn${activeView === "control" ? " active" : ""}`}
              onClick={() => { posthog?.capture("control_panel_opened"); onViewChange("control"); setSidebarOpen(false); }}
            >
              Control
            </button>
          </div>

          {activeView === "chat" ? (
            <>
              {/* New Agent Button */}
              <button className="new-agent-btn" onClick={handleCreateAgent}>
                <Plus size={14} />
                New Agent
              </button>

              {/* Agent List */}
              <div className="agent-list">
                {agents.map((agent) => {
                  const isDefault = agent.id === defaultId;
                  return (
                    <div
                      key={agent.id}
                      className={`agent-item${currentAgentId === agent.id ? " active" : ""}`}
                      onClick={() => handleSelectAgent(agent.id)}
                    >
                      <div className="agent-avatar">
                        <Bot />
                      </div>
                      <div className="agent-info">
                        <div className="agent-name">{agentDisplayName(agent)}</div>
                        {(() => {
                          // `agent.model` can be a string OR a
                          // `{primary, fallbacks}` object (OpenClaw 4.5
                          // returns the structured shape from agents.list).
                          // Direct `.split` calls here used to crash the
                          // chat UI with `TypeError: e.model.split is not a
                          // function` after sign-in.
                          const modelStr = getAgentModelString(agent);
                          if (!modelStr) return null;
                          const display = modelStr.split("/").pop()?.replace(/-v\d+:\d+$/, "") || modelStr;
                          return <div className="agent-model">{display}</div>;
                        })()}
                      </div>
                      <div className="agent-row-actions">
                        <button
                          type="button"
                          className="agent-row-action"
                          aria-label={`Rename ${agentDisplayName(agent)}`}
                          onClick={(e) => { e.stopPropagation(); setRenameTarget(agent); }}
                        >
                          <Pencil size={13} />
                        </button>
                        {!isDefault && (
                          <button
                            type="button"
                            className="agent-row-action agent-row-action--danger"
                            aria-label={`Delete ${agentDisplayName(agent)}`}
                            onClick={(e) => { e.stopPropagation(); setDeleteTarget(agent); }}
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </div>
                      <div className="agent-status-dot" />
                    </div>
                  );
                })}
              </div>

              {/* Agent catalog gallery — renders below the user's agents.
                  useCatalog filters out already-deployed templates, so this
                  section auto-hides once a user has deployed every template
                  (and never renders while the catalog/deployed fetches are
                  still in flight). On successful deploy we refresh the agent
                  list and auto-select the newly deployed agent. */}
              <GallerySection
                onAgentDeployed={(result) => {
                  // No toast library is wired up in the frontend yet, so we
                  // just log + rely on the auto-select below to give the user
                  // visible feedback that the deploy landed.
                  console.log("[catalog deploy]", result);
                  setUserSelectedId(result.agent_id);
                  dispatchSelectAgentEvent(result.agent_id);
                  setSidebarOpen(false);
                }}
              />
            </>
          ) : (
            <ControlSidebar activePanel={activePanel} onPanelChange={onPanelChange} />
          )}

          {/* Footer */}
          <div className="sidebar-footer">
            <div className="user-row">
              <div className="user-avatar">{userInitials}</div>
              <div className="user-info">
                <div className="user-name">{userName}</div>
              </div>
              {subscriptionStatus && <span className="plan-badge">{subscriptionStatus}</span>}
            </div>
            <div className="version-text">isol8 v0.1</div>
          </div>
        </div>

        <div className="main-area" style={{ gridArea: "main" }}>
          <div className="main-header">
            <button className="mobile-hamburger" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
              <Menu size={22} />
            </button>
            {onOpenFile && (
              <button
                onClick={() => { posthog?.capture("file_browser_opened"); onOpenFile?.(""); }}
                className="flex items-center justify-center text-[#8a8578] hover:text-[#1a1a1a] transition-colors p-1"
                title="Browse workspace files"
              >
                <FolderOpen size={18} />
              </button>
            )}
            <div style={{ flex: 1 }} />
            {process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED === "true" && (
              <Link
                href="/teams"
                className="text-sm text-zinc-700 hover:underline mr-3"
              >
                Teams
              </Link>
            )}
            <UserButton
              appearance={{
                elements: {
                  avatarBox: "h-8 w-8",
                },
              }}
            >
              <UserButton.MenuItems>
                <UserButton.Link label="Settings" labelIcon={<CreditCard className="h-4 w-4" />} href="/settings" />
              </UserButton.MenuItems>
            </UserButton>
          </div>

          <div className="main-content">
            <TrialBanner />
            <OutOfCreditsBanner />
            {showSubscriptionSuccess && (
              <div className="subscription-banner">
                <CheckCircle size={16} />
                <p>Subscription confirmed! Your agent is being upgraded.</p>
              </div>
            )}
            {recoveryTriggered ? (
              <ProvisioningStepper trigger="recovery">{children}</ProvisioningStepper>
            ) : (
              <ProvisioningStepper>{children}</ProvisioningStepper>
            )}
          </div>
        </div>

        {fileViewerOpen && (
          <FileViewer
            agentId={currentAgentId}
            initialFilePath={activeFilePath}
            onClose={() => onCloseFileViewer?.()}
          />
        )}

        {/* Each dialog is keyed on its open/target so it remounts (and
            re-initializes its internal state) on each open, instead of
            using useEffect to reset on close — see AgentDialogs.tsx. */}
        <AgentCreateDialog
          key={createFormOpen ? "create-open" : "create-closed"}
          open={createFormOpen}
          existingIds={agents.map((a) => a.id)}
          onCancel={() => setCreateFormOpen(false)}
          onCreate={async (name) => {
            // OpenClaw's agents.create requires a non-empty `workspace` —
            // see useAgents.createAgent, which fills in the default path
            // (.openclaw/workspaces/{id}) when omitted.
            await createAgent({ name });
            setCreateFormOpen(false);
          }}
        />

        <AgentRenameDialog
          key={`rename-${renameTarget?.id ?? "closed"}`}
          agent={renameTarget}
          onCancel={() => setRenameTarget(null)}
          onRename={async (name) => {
            if (!renameTarget) return;
            await updateAgent(renameTarget.id, { name });
            setRenameTarget(null);
          }}
        />

        <AgentDeleteDialog
          key={`delete-${deleteTarget?.id ?? "closed"}`}
          agent={deleteTarget}
          onCancel={() => setDeleteTarget(null)}
          onDelete={async () => {
            if (!deleteTarget) return;
            await deleteAgent(deleteTarget.id);
            if (userSelectedId === deleteTarget.id) setUserSelectedId(null);
            setDeleteTarget(null);
          }}
        />
      </div>
    </>
  );
}
