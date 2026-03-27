"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth, UserButton } from "@clerk/nextjs";
import { Bot, CreditCard, Trash2 } from "lucide-react";

import { ProvisioningStepper } from "@/components/chat/ProvisioningStepper";
import { useApi } from "@/lib/api";
import { useAgents, type Agent } from "@/hooks/useAgents";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
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
  const api = useApi();
  const { agents, defaultId, deleteAgent } = useAgents();
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

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden relative selection:bg-primary/20">
      {/* Global Grain Overlay */}
      <div className="fixed inset-0 z-0 pointer-events-none bg-noise opacity-[0.03]" />

      <div className="relative z-10 flex w-full h-full">
        <div className="w-64 hidden md:flex flex-col border-r border-border bg-sidebar/50 backdrop-blur-xl">
          {/* Tab Switcher */}
          <div className="flex border-b border-border">
            <button
              className={cn(
                "flex-1 px-3 py-2 text-xs font-medium uppercase tracking-wider transition-colors",
                activeView === "chat"
                  ? "text-foreground border-b-2 border-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
              onClick={() => onViewChange("chat")}
            >
              Chat
            </button>
            <button
              className={cn(
                "flex-1 px-3 py-2 text-xs font-medium uppercase tracking-wider transition-colors",
                activeView === "control"
                  ? "text-foreground border-b-2 border-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
              onClick={() => onViewChange("control")}
            >
              Control
            </button>
          </div>

          {activeView === "chat" ? (
            <>
              {/* Agent List */}
              <ScrollArea className="flex-1 px-3 py-2">
                <div className="space-y-1">
                  {agents.map((agent) => (
                    <div key={agent.id} className="group flex items-center">
                      <Button
                        variant="ghost"
                        className={cn(
                          "flex-1 justify-start gap-2 font-normal truncate transition-all h-auto py-1.5",
                          currentAgentId === agent.id
                            ? "bg-accent text-accent-foreground"
                            : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                        )}
                        onClick={() => handleSelectAgent(agent.id)}
                      >
                        <Bot className="h-4 w-4 flex-shrink-0 opacity-70" />
                        <div className="flex flex-col items-start min-w-0">
                          <span className="truncate w-full text-left">{agentDisplayName(agent)}</span>
                          {agent.model && (
                            <span className="text-[10px] text-muted-foreground/60 truncate w-full text-left">
                              {agent.model.split("/").pop()?.replace(/-v\d+:\d+$/, "") || agent.model}
                            </span>
                          )}
                        </div>
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                        onClick={() => handleDeleteAgent(agent.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </>
          ) : (
            <ControlSidebar activePanel={activePanel} onPanelChange={onPanelChange} />
          )}

          <div className="p-4 border-t border-border text-[10px] text-muted-foreground/40 text-center uppercase tracking-widest font-mono">
            Isol8 v0.1
          </div>
        </div>

        <main className="flex-1 min-h-0 flex flex-col relative bg-background/20">
          <header className="h-14 border-b border-border flex items-center justify-end gap-2 px-4 backdrop-blur-sm bg-background/20 absolute top-0 right-0 left-0 z-20">
            <UserButton
              appearance={{
                elements: {
                  avatarBox: "h-8 w-8",
                },
              }}
            >
              <UserButton.MenuItems>
                <UserButton.Link label="Billing" labelIcon={<CreditCard className="h-4 w-4" />} href="/settings/billing" />
              </UserButton.MenuItems>
            </UserButton>
          </header>

          <div className="flex-1 min-h-0 pt-14 flex flex-col overflow-y-auto">
            <ProvisioningStepper>{children}</ProvisioningStepper>
          </div>
        </main>
      </div>
    </div>
  );
}
