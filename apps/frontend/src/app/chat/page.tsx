"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChatLayout } from "@/components/chat/ChatLayout";
import { AgentChatWindow } from "@/components/chat/AgentChatWindow";
import { ControlPanelRouter } from "@/components/control/ControlPanelRouter";
import { GatewayProvider } from "@/hooks/useGateway";

export default function ChatPage() {
  const searchParams = useSearchParams();
  // ?panel=credits opens the credits control panel directly. Used by
  // OutOfCreditsBanner's CTA so blocked card-3 users land on the top-up
  // form. Codex P1 on PR #393 — the previous CTA pointed to a
  // /settings/credits route that doesn't exist.
  const initialPanel = searchParams.get("panel") || "overview";
  const initialView = searchParams.get("panel") ? "control" : "chat";

  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"chat" | "control">(initialView);
  const [activePanel, setActivePanel] = useState<string>(initialPanel);
  const [fileViewerOpen, setFileViewerOpen] = useState(false);
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null);

  const handleOpenFile = useCallback((path: string) => {
    setActiveFilePath(path);
    setFileViewerOpen(true);
  }, []);

  const handleCloseFileViewer = useCallback(() => {
    setFileViewerOpen(false);
    setActiveFilePath(null);
  }, []);

  useEffect(() => {
    function handleSelectAgent(e: Event) {
      const customEvent = e as CustomEvent<{ agentId: string }>;
      setSelectedAgentId(customEvent.detail.agentId);
    }

    window.addEventListener("selectAgent", handleSelectAgent);

    return () => {
      window.removeEventListener("selectAgent", handleSelectAgent);
    };
  }, []);

  return (
    <GatewayProvider>
      <ChatLayout
        activeView={activeView}
        onViewChange={setActiveView}
        activePanel={activePanel}
        onPanelChange={setActivePanel}
        fileViewerOpen={fileViewerOpen}
        activeFilePath={activeFilePath}
        onOpenFile={handleOpenFile}
        onCloseFileViewer={handleCloseFileViewer}
      >
        {/* Keep AgentChatWindow mounted but hidden so chat state
            (messages, scroll position, streaming) survives view switches */}
        <div className={activeView === "chat" ? "flex flex-col h-full min-h-0" : "hidden"}>
          <AgentChatWindow key={selectedAgentId} agentId={selectedAgentId} onOpenFile={handleOpenFile} />
        </div>
        {activeView === "control" && (
          <div className="flex flex-col h-full min-h-0">
            <ControlPanelRouter panel={activePanel} />
          </div>
        )}
      </ChatLayout>
    </GatewayProvider>
  );
}
