"use client";

import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { MessageList } from "@/components/chat/MessageList";
import { adaptSessionMessages, type AdaptedMessage } from "./sessionMessageAdapter";

interface ChatHistoryResp {
  messages?: unknown[];
}

export function RunTranscript({ sessionKey }: { sessionKey: string | undefined }) {
  // Always call the hook (hooks rules). Pass `null` method to skip the fetch
  // when we have no sessionKey — useGatewayRpc short-circuits SWR on null.
  const { data, error, isLoading, mutate } = useGatewayRpc<ChatHistoryResp>(
    sessionKey ? "chat.history" : null,
    sessionKey ? { sessionKey, limit: 200 } : undefined,
  );

  if (!sessionKey) {
    return (
      <div className="p-6 text-sm text-[#8a8578]">
        No transcript available for this run.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-6 text-sm text-[#8a8578]">Loading transcript…</div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-sm text-destructive">
        Transcript unavailable: {String(error?.message ?? error)}.
        <button
          onClick={() => mutate()}
          className="ml-2 underline"
        >
          Retry
        </button>
      </div>
    );
  }

  const messages = adaptSessionMessages(data?.messages);
  if (messages.length === 0) {
    return (
      <div className="p-6 text-sm text-[#8a8578]">
        No transcript available for this run.
      </div>
    );
  }

  return <MessageList messages={messages} />;
}

export function firstUserMessage(messages: AdaptedMessage[]): string | undefined {
  return messages.find((m) => m.role === "user")?.content;
}
