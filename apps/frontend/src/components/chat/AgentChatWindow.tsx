"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChatInput } from "./ChatInput";
import { ConnectionStatusBar } from "./ConnectionStatusBar";
import { MessageList, MessageListHandle } from "./MessageList";
import { ChannelCards, isChannelCardsDismissed } from "./ChannelCards";
import { useAgentChat, BOOTSTRAP_MESSAGE } from "@/hooks/useAgentChat";
import { useApi } from "@/lib/api";
import { Loader2 } from "lucide-react";

import type { ToolUse } from "@/hooks/useAgentChat";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  model?: string;
  toolUses?: ToolUse[];
}

interface AgentChatWindowProps {
  agentId: string | null;
}

export function AgentChatWindow({
  agentId,
}: AgentChatWindowProps): React.ReactElement {
  const {
    messages: chatMessages,
    isStreaming,
    error: chatError,
    sendMessage,
    cancelMessage,
    clearMessages,
    isLoadingHistory,
    needsBootstrap,
  } = useAgentChat(agentId);

  const api = useApi();
  const [isUploading, setIsUploading] = useState(false);
  const [showChannelCards, setShowChannelCards] = useState(() => !isChannelCardsDismissed());
  const messageListRef = useRef<MessageListHandle>(null);

  const isInitialState = chatMessages.length === 0;
  const isTyping = isStreaming;

  const prevAgentIdRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (
      prevAgentIdRef.current !== undefined &&
      prevAgentIdRef.current !== agentId
    ) {
      clearMessages();
    }
    prevAgentIdRef.current = agentId;
  }, [agentId, clearMessages]);

  const handleSend = useCallback(
    async (content: string, files?: File[]): Promise<void> => {
      try {
        let message = content;

        if (files && files.length > 0) {
          setIsUploading(true);
          try {
            const result = await api.uploadFiles(files);
            const fileList = result.uploaded
              .map((f) => `- ${f.filename} → ${f.path}`)
              .join("\n");
            const fileNotice = `[The user uploaded files to your workspace. You can read them at these paths:\n${fileList}]\n\n`;
            message = fileNotice + message;
          } catch (err) {
            console.error("Upload failed:", err);
            const errorMsg = err instanceof Error ? err.message : "Upload failed";
            // Still send the text message but note the upload failure
            message = `[File upload failed: ${errorMsg}]\n\n` + message;
          } finally {
            setIsUploading(false);
          }
        }

        if (message.trim()) {
          await sendMessage(message);
          setTimeout(() => messageListRef.current?.scrollToBottom(), 50);
        }
      } catch (err) {
        console.error("Failed to send message:", err);
      }
    },
    [sendMessage, api],
  );

  const messages: Message[] = useMemo(
    () =>
      chatMessages.map((msg, i) => ({
        id: String(i),
        role: msg.role,
        content: msg.content,
        ...(msg.thinking ? { thinking: msg.thinking } : {}),
        ...(msg.toolUses?.length ? { toolUses: msg.toolUses } : {}),
      })),
    [chatMessages],
  );

  if (chatError) {
    return (
      <div className="flex flex-col h-full bg-background/20">
        <ConnectionStatusBar />
        <div className="flex-1 flex flex-col">
          {messages.length > 0 && (
            <MessageList ref={messageListRef} messages={messages} isTyping={isTyping} />
          )}
          <div className="p-4 m-4 bg-red-900/20 text-red-300 rounded-lg">
            <p className="font-medium">Error</p>
            <p className="text-sm">{chatError}</p>
          </div>
          <ChatInput onSend={handleSend} onStop={cancelMessage} disabled={isTyping} isStreaming={isStreaming} isUploading={isUploading} />
        </div>
      </div>
    );
  }

  if (isLoadingHistory) {
    return (
      <div className="flex flex-col h-full bg-background/20">
        <ConnectionStatusBar />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-white/40" />
        </div>
      </div>
    );
  }

  if (isInitialState) {
    // Show channel cards on first visit (one-time onboarding)
    if (showChannelCards) {
      return (
        <div className="flex flex-col h-full bg-background/20">
          <ConnectionStatusBar />
          <div className="flex-1 flex items-center justify-center p-4">
            <ChannelCards onDismiss={() => setShowChannelCards(false)} />
          </div>
        </div>
      );
    }

    return (
      <div className="flex flex-col h-full bg-background/20">
        <ConnectionStatusBar />
        <div className="flex-1 flex flex-col items-center justify-center p-4">
          <div className="text-center mb-8">
            <h1 className="text-4xl font-bold mb-3 text-foreground tracking-tight font-host">
              {agentId ?? "Select an agent"}
            </h1>
            <p className="text-muted-foreground text-lg font-light">
              Start a conversation with your agent
            </p>
          </div>
          <div className="w-full max-w-2xl">
            <ChatInput
              onSend={handleSend}
              onStop={cancelMessage}
              disabled={isTyping || !agentId}
              isStreaming={isStreaming}
              centered
              isUploading={isUploading}
              suggestedMessage={needsBootstrap ? BOOTSTRAP_MESSAGE : undefined}
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0 bg-background/20">
      <ConnectionStatusBar />
      <MessageList ref={messageListRef} messages={messages} isTyping={isTyping} />
      <ChatInput onSend={handleSend} onStop={cancelMessage} disabled={isTyping} isStreaming={isStreaming} isUploading={isUploading} />
    </div>
  );
}
