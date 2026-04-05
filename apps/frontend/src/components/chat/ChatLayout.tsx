"use client";

import "./ChatLayout.css";
import { useEffect, useRef, useState } from "react";
import { useAuth, useOrganization, useUser, UserButton } from "@clerk/nextjs";
import { useRouter, useSearchParams } from "next/navigation";
import { Settings, Plus, Bot, CheckCircle, CreditCard, Menu, X, FolderOpen } from "lucide-react";
import Link from "next/link";

import { ProvisioningStepper } from "@/components/chat/ProvisioningStepper";
import { HealthIndicator } from "@/components/chat/HealthIndicator";
import { useGateway } from "@/hooks/useGateway";
import { useApi } from "@/lib/api";
import { useAgents, type Agent } from "@/hooks/useAgents";
import { useBilling } from "@/hooks/useBilling";
import { ControlSidebar } from "@/components/control/ControlSidebar";
import { FileViewer } from "@/components/chat/FileViewer";
import { useNodeBridge } from "@/hooks/useNodeBridge";

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
  const { isSignedIn } = useAuth();
  const { user, isLoaded: userLoaded } = useUser();
  const { organization } = useOrganization();
  const router = useRouter();
  const api = useApi();
  const { agents, defaultId, createAgent } = useAgents();
  const { refresh: refreshBilling, account } = useBilling();
  const { nodeConnected } = useGateway();
  const searchParams = useSearchParams();

  // Desktop app: bridge node commands via browser WebSocket + Tauri IPC
  useNodeBridge();

  const [userSelectedId, setUserSelectedId] = useState<string | null>(null);
  const [showSubscriptionSuccess, setShowSubscriptionSuccess] = useState(
    () => searchParams.get("subscription") === "success",
  );
  const [recoveryTriggered, setRecoveryTriggered] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

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
    setSidebarOpen(false);
  }

  async function handleCreateAgent(): Promise<void> {
    const name = "Agent " + (agents.length + 1);
    await createAgent({ name, workspace: name.toLowerCase().replace(/\s+/g, "-") });
  }

  return (
    <>

      <div className={`app-shell${fileViewerOpen ? " with-file-viewer" : ""}`}>
        <div className={`sidebar-backdrop${sidebarOpen ? " visible" : ""}`} onClick={() => setSidebarOpen(false)} />
        <div className={`cream-sidebar${sidebarOpen ? " mobile-open" : ""}`}>
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
              onClick={() => { onViewChange("control"); setSidebarOpen(false); }}
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
            <button className="mobile-hamburger" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
              <Menu size={22} />
            </button>
            {onOpenFile && (
              <button
                onClick={() => onOpenFile?.("")}
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
      </div>
    </>
  );
}
