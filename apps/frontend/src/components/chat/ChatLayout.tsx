"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth, useUser, UserButton } from "@clerk/nextjs";
import { Settings, Plus, Bot } from "lucide-react";
import Link from "next/link";

import { ProvisioningStepper } from "@/components/chat/ProvisioningStepper";
import { useApi } from "@/lib/api";
import { useAgents, type Agent } from "@/hooks/useAgents";
import { useBilling } from "@/hooks/useBilling";
import { ControlSidebar } from "@/components/control/ControlSidebar";
import { cn } from "@/lib/utils";

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
  const { user } = useUser();
  const api = useApi();
  const { agents, defaultId, deleteAgent, createAgent } = useAgents();
  const { account } = useBilling();
  const [userSelectedId, setUserSelectedId] = useState<string | null>(null);

  // Derive effective agent: user selection > default > first agent
  const currentAgentId = userSelectedId ?? defaultId ?? agents[0]?.id ?? null;

  useEffect(() => {
    if (!isSignedIn) return;

    api.syncUser().catch((err) => console.error("User sync failed:", err));
  }, [isSignedIn, api]);

  // Dispatch DOM event so page.tsx picks up the current agent (external system sync)
  const lastDispatchedRef = useRef<string | null>(null);
  useEffect(() => {
    if (currentAgentId && currentAgentId !== lastDispatchedRef.current) {
      lastDispatchedRef.current = currentAgentId;
      dispatchSelectAgentEvent(currentAgentId);
    }
  }, [currentAgentId]);

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
    const name = `Agent ${agents.length + 1}`;
    await createAgent({ name, workspace: name.toLowerCase().replace(/\s+/g, "-") });
  }

  const planTier = account?.plan_tier ?? "free";
  const userName = user?.fullName || user?.firstName || "User";
  const userInitials =
    user?.firstName && user?.lastName
      ? `${user.firstName[0]}${user.lastName[0]}`
      : user?.firstName?.[0] ?? "U";

  return (
    <>
      <style>{`
        /* ── APP SHELL ── */
        .app-shell {
          display: grid;
          grid-template-columns: 260px 1fr;
          height: 100vh;
          background: #faf7f2;
          color: #1a1a1a;
          overflow: hidden;
        }

        /* ── SIDEBAR ── */
        .app-sidebar {
          display: flex;
          flex-direction: column;
          background: #f3efe6;
          border-right: 1px solid #e0dbd0;
          overflow: hidden;
          font-family: var(--font-dm-sans), 'DM Sans', sans-serif;
        }

        .app-sb-header {
          padding: 16px 16px 0;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .app-sb-logo {
          display: inline-flex;
          transition: opacity 0.2s;
        }
        .app-sb-logo:hover { opacity: 0.8; }

        .app-sb-settings-btn {
          width: 44px;
          height: 44px;
          border-radius: 10px;
          border: none;
          background: transparent;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #706b63;
          transition: background 0.15s ease-out, color 0.15s ease-out;
        }
        .app-sb-settings-btn:hover {
          background: rgba(6,64,43,0.06);
          color: #06402B;
        }

        /* view tabs */
        .app-sb-tabs {
          display: flex;
          margin: 16px 16px 0;
          background: rgba(0,0,0,0.04);
          border-radius: 10px;
          padding: 3px;
        }
        .app-sb-tab {
          flex: 1;
          padding: 10px 0;
          min-height: 44px;
          font-size: 12px;
          font-weight: 600;
          text-align: center;
          border-radius: 8px;
          border: none;
          background: transparent;
          color: #706b63;
          cursor: pointer;
          transition: background 0.15s ease-out, color 0.15s ease-out, box-shadow 0.15s ease-out;
          text-transform: uppercase;
          letter-spacing: 1px;
          font-family: inherit;
        }
        .app-sb-tab.active {
          background: white;
          color: #1a1a1a;
          box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }
        .app-sb-tab:not(.active):hover { color: #4a4640; }
        .app-sb-tab:active { transform: scale(0.98); }

        /* new agent button */
        .app-sb-new-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          width: calc(100% - 32px);
          margin: 12px 16px 0;
          padding: 12px 14px;
          min-height: 44px;
          border-radius: 10px;
          border: 1px dashed #d4cfc5;
          background: transparent;
          font-size: 13px;
          font-weight: 500;
          font-family: inherit;
          color: #706b63;
          cursor: pointer;
          transition: border-color 0.15s ease-out, color 0.15s ease-out, background 0.15s ease-out;
        }
        .app-sb-new-btn:hover {
          border-color: #06402B;
          color: #06402B;
          background: rgba(6,64,43,0.03);
        }
        .app-sb-new-btn:active {
          background: rgba(6,64,43,0.06);
        }

        /* agent list */
        .app-sb-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px 12px;
        }
        .app-sb-list::-webkit-scrollbar { width: 4px; }
        .app-sb-list::-webkit-scrollbar-thumb { background: #d4cfc5; border-radius: 2px; }

        .app-sb-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 12px;
          min-height: 44px;
          border-radius: 10px;
          cursor: pointer;
          transition: background 0.15s ease-out;
          position: relative;
          border: none;
          background: transparent;
          width: 100%;
          text-align: left;
          font-family: inherit;
        }
        .app-sb-item:hover { background: rgba(0,0,0,0.04); }
        .app-sb-item:active { background: rgba(0,0,0,0.07); }
        .app-sb-item.active { background: rgba(6,64,43,0.08); }

        .app-sb-item-avatar {
          width: 32px;
          height: 32px;
          border-radius: 10px;
          background: #06402B;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

        .app-sb-item-info {
          flex: 1;
          min-width: 0;
        }
        .app-sb-item-name {
          font-size: 13px;
          font-weight: 600;
          color: #1a1a1a;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .app-sb-item-model {
          font-size: 12px;
          color: #7a756d;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .app-sb-item-status {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: #4a9e74;
          flex-shrink: 0;
          box-shadow: 0 0 0 2px #f3efe6;
        }
        .app-sb-item.active .app-sb-item-status {
          box-shadow: 0 0 0 2px rgba(6,64,43,0.08);
        }

        /* sidebar footer */
        .app-sb-footer {
          padding: 12px 16px;
          border-top: 1px solid #e0dbd0;
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .app-sb-user-avatar {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: #06402B;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 11px;
          font-weight: 600;
          color: white;
          flex-shrink: 0;
        }
        .app-sb-user-name {
          font-size: 13px;
          font-weight: 500;
          color: #1a1a1a;
          flex: 1;
          min-width: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .app-sb-plan-badge {
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 1px;
          text-transform: uppercase;
          color: #06402B;
          background: rgba(6,64,43,0.08);
          padding: 3px 10px;
          border-radius: 999px;
          flex-shrink: 0;
        }

        /* version text */
        .app-sb-version {
          padding: 0 16px 12px;
          font-size: 10px;
          color: #b0aa9f;
          text-align: center;
          letter-spacing: 2px;
          text-transform: uppercase;
          font-family: monospace;
        }

        /* ── MAIN AREA ── */
        .app-main {
          display: flex;
          flex-direction: column;
          overflow: hidden;
          position: relative;
          background: #faf7f2;
        }

        .app-main-header {
          height: 56px;
          border-bottom: 1px solid #e0dbd0;
          display: flex;
          align-items: center;
          justify-content: flex-end;
          padding: 0 16px;
          background: #faf7f2;
          flex-shrink: 0;
          z-index: 20;
        }

        .app-main-content {
          flex: 1;
          min-height: 0;
          display: flex;
          flex-direction: column;
          overflow-y: auto;
        }

        /* mobile sidebar hidden */
        @media (max-width: 767px) {
          .app-shell {
            grid-template-columns: 1fr;
          }
          .app-sidebar {
            display: none;
          }
        }
      `}</style>

      <div className="app-shell">
        {/* ════════════ SIDEBAR ════════════ */}
        <nav className="app-sidebar" aria-label="Main navigation">
          {/* Header: Logo + Settings */}
          <div className="app-sb-header">
            <Link href="/" className="app-sb-logo" aria-label="isol8 home">
              <svg width="28" height="28" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <rect width="100" height="100" rx="22" fill="#06402B"/>
                <text x="50" y="68" textAnchor="middle" fontFamily="var(--font-lora-serif), 'Lora', serif" fontStyle="italic" fontSize="52" fill="white">8</text>
              </svg>
            </Link>
            <Link href="/settings" className="app-sb-settings-btn" title="Settings" aria-label="Settings">
              <Settings size={16} />
            </Link>
          </div>

          {/* Chat / Control tab switcher */}
          <div className="app-sb-tabs" role="tablist" aria-label="View switcher">
            <button
              className={cn("app-sb-tab", activeView === "chat" && "active")}
              role="tab"
              aria-selected={activeView === "chat"}
              onClick={() => onViewChange("chat")}
            >
              Chat
            </button>
            <button
              className={cn("app-sb-tab", activeView === "control" && "active")}
              role="tab"
              aria-selected={activeView === "control"}
              onClick={() => onViewChange("control")}
            >
              Control
            </button>
          </div>

          {activeView === "chat" ? (
            <>
              {/* New Agent Button */}
              <button className="app-sb-new-btn" onClick={handleCreateAgent}>
                <Plus size={14} strokeWidth={2.5} />
                New Agent
              </button>

              {/* Agent List */}
              <div className="app-sb-list" role="listbox" aria-label="Agents">
                {agents.map((agent) => (
                  <button
                    key={agent.id}
                    className={cn("app-sb-item", currentAgentId === agent.id && "active")}
                    role="option"
                    aria-selected={currentAgentId === agent.id}
                    onClick={() => handleSelectAgent(agent.id)}
                  >
                    <div className="app-sb-item-avatar" aria-hidden="true">
                      <Bot size={14} color="white" />
                    </div>
                    <div className="app-sb-item-info">
                      <div className="app-sb-item-name">{agentDisplayName(agent)}</div>
                      {agent.model && (
                        <div className="app-sb-item-model">
                          {agent.model.split("/").pop()?.replace(/-v\d+:\d+$/, "") || agent.model}
                        </div>
                      )}
                    </div>
                    <div className="app-sb-item-status" aria-label="Online" />
                  </button>
                ))}
              </div>
            </>
          ) : (
            <ControlSidebar activePanel={activePanel} onPanelChange={onPanelChange} />
          )}

          {/* User Footer */}
          <div className="app-sb-footer">
            <div className="app-sb-user-avatar" aria-hidden="true">{userInitials}</div>
            <div className="app-sb-user-name">{userName}</div>
            <div className="app-sb-plan-badge">{planTier}</div>
          </div>

          {/* Version */}
          <div className="app-sb-version">isol8 v0.1</div>
        </nav>

        {/* ════════════ MAIN CONTENT ════════════ */}
        <div className="app-main">
          <header className="app-main-header">
            <UserButton
              appearance={{
                elements: {
                  avatarBox: "h-8 w-8",
                },
              }}
            />
          </header>

          <div className="app-main-content">
            <ProvisioningStepper>{children}</ProvisioningStepper>
          </div>
        </div>
      </div>
    </>
  );
}
