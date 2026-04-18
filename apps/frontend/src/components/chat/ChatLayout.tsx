"use client";

import "./ChatLayout.css";
import { useEffect, useRef, useState } from "react";
import { usePostHog } from "posthog-js/react";
import { useAuth, useOrganization, useOrganizationList, useUser, UserButton } from "@clerk/nextjs";
import { useRouter, useSearchParams } from "next/navigation";
import { Settings, Plus, Bot, CheckCircle, CreditCard, Menu, X, FolderOpen, Pencil, Trash2, Loader2 } from "lucide-react";
import Link from "next/link";

import { ProvisioningStepper } from "@/components/chat/ProvisioningStepper";
import { HealthIndicator } from "@/components/chat/HealthIndicator";
import { useGateway } from "@/hooks/useGateway";
import { useActivityPing } from "@/hooks/useActivityPing";
import { useApi } from "@/lib/api";
import { useAgents, getAgentModelString, type Agent } from "@/hooks/useAgents";
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

function agentDisplayName(agent: Agent): string {
  return agent.identity?.name || agent.name || agent.id;
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
  const { isSignedIn } = useAuth();
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
  const { agents, defaultId, isLoading: agentsLoading, createAgent, deleteAgent, updateAgent } = useAgents();
  const { refresh: refreshBilling, account } = useBilling();
  const { nodeConnected } = useGateway();
  // Emit throttled user_active pings so the backend scale-to-zero reaper
  // can keep idle free-tier containers running while the user is active.
  useActivityPing();
  const searchParams = useSearchParams();

  const [userSelectedId, setUserSelectedId] = useState<string | null>(null);
  const [showSubscriptionSuccess, setShowSubscriptionSuccess] = useState(
    () => searchParams.get("subscription") === "success",
  );
  const [recoveryTriggered, setRecoveryTriggered] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [createFormOpen, setCreateFormOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Agent | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Agent | null>(null);

  // Derive effective agent: user selection > default > first agent
  const currentAgentId = userSelectedId ?? defaultId ?? agents[0]?.id ?? null;

  const planTier = account?.tier ?? "free";
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

  // Post-checkout confirmation: refresh billing + clean URL + auto-dismiss
  useEffect(() => {
    if (!showSubscriptionSuccess) return;

    refreshBilling();
    router.replace("/chat", { scroll: false });

    const timer = setTimeout(() => setShowSubscriptionSuccess(false), 5000);
    return () => clearTimeout(timer);
  }, [showSubscriptionSuccess, refreshBilling, router]);

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
              <Link href="/settings" className="sidebar-settings-link">
                <Settings size={18} />
              </Link>
              <button className="mobile-hamburger" onClick={() => setSidebarOpen(false)} aria-label="Close menu" style={{ display: sidebarOpen ? "flex" : undefined }}>
                <X size={18} />
              </button>
            </div>
          </div>

          {/* Health Indicator */}
          <HealthIndicator onRecoveryReprovision={() => setRecoveryTriggered(true)} />

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
                {agentsLoading && !agents.length ? (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 8,
                      padding: "12px 8px",
                      color: "#8a8578",
                      fontSize: 13,
                    }}
                  >
                    <Loader2 className="h-3 w-3 animate-spin" />
                    <span>Loading agents…</span>
                  </div>
                ) : null}
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
              <span className="plan-badge">{planTier}</span>
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
