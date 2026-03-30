"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth, useOrganization, useUser, UserButton } from "@clerk/nextjs";
import { useRouter, useSearchParams } from "next/navigation";
import { Settings, Plus, Bot, CheckCircle, CreditCard } from "lucide-react";
import Link from "next/link";

import { ProvisioningStepper } from "@/components/chat/ProvisioningStepper";
import { useApi } from "@/lib/api";
import { useAgents, type Agent } from "@/hooks/useAgents";
import { useBilling } from "@/hooks/useBilling";
import { ControlSidebar } from "@/components/control/ControlSidebar";

interface ChatLayoutProps {
  children: React.ReactNode;
  activeView: "chat" | "control";
  onViewChange: (view: "chat" | "control") => void;
  activePanel?: string;
  onPanelChange?: (panel: string) => void;
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
}: ChatLayoutProps): React.ReactElement {
  const { isSignedIn } = useAuth();
  const { user, isLoaded: userLoaded } = useUser();
  const { organization } = useOrganization();
  const router = useRouter();
  const api = useApi();
  const { agents, defaultId, deleteAgent, createAgent } = useAgents();
  const { refresh: refreshBilling, account } = useBilling();
  const searchParams = useSearchParams();

  const [userSelectedId, setUserSelectedId] = useState<string | null>(null);
  const [showSubscriptionSuccess, setShowSubscriptionSuccess] = useState(
    () => searchParams.get("subscription") === "success",
  );

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

  // Client-side onboarding check: redirect if user hasn't onboarded and has no org
  useEffect(() => {
    if (!userLoaded || !isSignedIn) return;
    const onboarded = (user?.unsafeMetadata as Record<string, unknown> | undefined)?.onboarded;
    if (!onboarded && !organization) {
      router.replace("/onboarding");
    }
  }, [userLoaded, isSignedIn, user, organization, router]);

  useEffect(() => {
    if (!isSignedIn) return;

    api.syncUser().catch((err: unknown) => console.error("User sync failed:", err));
  }, [isSignedIn, api]);

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
    setUserSelectedId(agentId);
    dispatchSelectAgentEvent(agentId);
  }

  async function handleDeleteAgent(agentId: string): Promise<void> {
    await deleteAgent(agentId);
    if (currentAgentId === agentId) {
      const remaining = agents.filter((a) => a.id !== agentId);
      if (remaining.length > 0) {
        handleSelectAgent(remaining[0].id);
      } else {
        setUserSelectedId(null);
      }
    }
  }

  async function handleCreateAgent(): Promise<void> {
    const name = "Agent " + (agents.length + 1);
    await createAgent({ name, workspace: name.toLowerCase().replace(/\s+/g, "-") });
  }

  return (
    <>
      <style>{`
        .app-shell {
          display: grid;
          grid-template-columns: 260px 1fr;
          height: 100vh;
          overflow: hidden;
        }
        .cream-sidebar {
          background: #f3efe6;
          border-right: 1px solid #e0dbd0;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .sidebar-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          border-bottom: 1px solid #e0dbd0;
        }
        .sidebar-logo {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .sidebar-logo svg {
          width: 24px;
          height: 24px;
        }
        .sidebar-logo span {
          font-size: 16px;
          font-weight: 600;
          color: #1a1a1a;
          letter-spacing: -0.01em;
        }
        .sidebar-settings-link {
          color: #8a8578;
          transition: color 0.15s;
          display: flex;
          align-items: center;
        }
        .sidebar-settings-link:hover {
          color: #1a1a1a;
        }
        .tab-switcher {
          display: flex;
          margin: 12px 16px;
          background: #e8e3d9;
          border-radius: 999px;
          padding: 3px;
        }
        .tab-btn {
          flex: 1;
          padding: 6px 0;
          font-size: 13px;
          font-weight: 500;
          text-align: center;
          border-radius: 999px;
          border: none;
          cursor: pointer;
          transition: all 0.15s;
          background: transparent;
          color: #8a8578;
        }
        .tab-btn.active {
          background: #fff;
          color: #1a1a1a;
          box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }
        .tab-btn:not(.active):hover {
          color: #1a1a1a;
        }
        .new-agent-btn {
          margin: 4px 16px 8px;
          padding: 8px 12px;
          border: 1.5px dashed #cdc7ba;
          border-radius: 8px;
          background: transparent;
          color: #8a8578;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          transition: all 0.15s;
        }
        .new-agent-btn:hover {
          border-color: #8a8578;
          color: #1a1a1a;
          background: rgba(255,255,255,0.5);
        }
        .agent-list {
          flex: 1;
          overflow-y: auto;
          padding: 0 12px;
        }
        .agent-item {
          display: flex;
          align-items: center;
          padding: 8px 8px;
          border-radius: 8px;
          cursor: pointer;
          transition: background 0.15s;
          position: relative;
          gap: 10px;
        }
        .agent-item:hover {
          background: rgba(255,255,255,0.6);
        }
        .agent-item.active {
          background: #fff;
          box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }
        .agent-avatar {
          width: 32px;
          height: 32px;
          border-radius: 6px;
          background: #2d8a4e;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .agent-avatar svg {
          color: #fff;
          width: 16px;
          height: 16px;
        }
        .agent-info {
          flex: 1;
          min-width: 0;
        }
        .agent-name {
          font-size: 13px;
          font-weight: 500;
          color: #1a1a1a;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .agent-model {
          font-size: 11px;
          color: #8a8578;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .agent-status-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: #2d8a4e;
          flex-shrink: 0;
        }
        .sidebar-footer {
          border-top: 1px solid #e0dbd0;
          padding: 12px 16px;
        }
        .user-row {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .user-avatar {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          background: #d4cfc4;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 12px;
          font-weight: 600;
          color: #5a5549;
          flex-shrink: 0;
        }
        .user-info {
          flex: 1;
          min-width: 0;
        }
        .user-name {
          font-size: 13px;
          font-weight: 500;
          color: #1a1a1a;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .plan-badge {
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          padding: 1px 6px;
          border-radius: 4px;
          background: #e8e3d9;
          color: #8a8578;
        }
        .version-text {
          text-align: center;
          font-size: 10px;
          color: #b5ae9e;
          font-family: monospace;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          padding-top: 8px;
        }
        .main-area {
          background: #faf7f2;
          display: flex;
          flex-direction: column;
          min-height: 0;
          position: relative;
        }
        .main-header {
          height: 56px;
          border-bottom: 1px solid #e0dbd0;
          display: flex;
          align-items: center;
          justify-content: flex-end;
          padding: 0 16px;
          background: #faf7f2;
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          z-index: 20;
        }
        .main-content {
          flex: 1;
          min-height: 0;
          padding-top: 56px;
          display: flex;
          flex-direction: column;
          overflow-y: auto;
        }
        .subscription-banner {
          margin: 8px 16px;
          padding: 12px;
          background: rgba(45,138,78,0.08);
          border: 1px solid rgba(45,138,78,0.2);
          border-radius: 8px;
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .subscription-banner svg {
          color: #2d8a4e;
          flex-shrink: 0;
        }
        .subscription-banner p {
          font-size: 14px;
          color: #2d6b3f;
          margin: 0;
        }
        @media (max-width: 768px) {
          .app-shell {
            grid-template-columns: 1fr;
          }
          .cream-sidebar {
            display: none;
          }
        }
      `}</style>

      <div className="app-shell">
        <div className="cream-sidebar">
          {/* Header */}
          <div className="sidebar-header">
            <div className="sidebar-logo">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="3" y="3" width="18" height="18" rx="4" fill="#1a1a1a"/>
                <rect x="7" y="7" width="4" height="4" rx="1" fill="#f3efe6"/>
                <rect x="13" y="7" width="4" height="4" rx="1" fill="#f3efe6"/>
                <rect x="7" y="13" width="4" height="4" rx="1" fill="#f3efe6"/>
                <rect x="13" y="13" width="4" height="4" rx="1" fill="#2d8a4e"/>
              </svg>
              <span>isol8</span>
            </div>
            <Link href="/settings" className="sidebar-settings-link">
              <Settings size={18} />
            </Link>
          </div>

          {/* Tab Switcher */}
          <div className="tab-switcher">
            <button
              className={`tab-btn${activeView === "chat" ? " active" : ""}`}
              onClick={() => onViewChange("chat")}
            >
              Chat
            </button>
            <button
              className={`tab-btn${activeView === "control" ? " active" : ""}`}
              onClick={() => onViewChange("control")}
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
                {agents.map((agent) => (
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
                      {agent.model && (
                        <div className="agent-model">
                          {agent.model.split("/").pop()?.replace(/-v\d+:\d+$/, "") || agent.model}
                        </div>
                      )}
                    </div>
                    <div className="agent-status-dot" />
                  </div>
                ))}
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

        <div className="main-area">
          <div className="main-header">
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
            <ProvisioningStepper>{children}</ProvisioningStepper>
          </div>
        </div>
      </div>
    </>
  );
}
