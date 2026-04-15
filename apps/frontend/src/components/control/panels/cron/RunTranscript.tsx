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

/**
 * Tolerance (ms) applied when matching `afterTs` against message `ts`.
 * Run.triggeredAtMs and the message timestamp recorded by OpenClaw are
 * captured at slightly different points in the pipeline, so we allow a
 * small fudge factor before declaring a message "older than this run".
 */
const FIRST_USER_MESSAGE_TS_TOLERANCE_MS = 5_000;

/**
 * Returns the first user message in `messages`. When `afterTs` is provided,
 * skips messages whose `ts` is more than `FIRST_USER_MESSAGE_TS_TOLERANCE_MS`
 * earlier — which is what we want for multi-run sessions where the same
 * sessionKey contains prompts from previous runs. Falls back to the first
 * user message overall when `afterTs` isn't provided or no message satisfies
 * the bound (e.g. the adapter didn't get a `ts` from the history payload).
 */
export function firstUserMessage(
  messages: AdaptedMessage[],
  afterTs?: number,
): string | undefined {
  if (afterTs !== undefined) {
    const cutoff = afterTs - FIRST_USER_MESSAGE_TS_TOLERANCE_MS;
    const scoped = messages.find(
      (m) => m.role === "user" && m.ts !== undefined && m.ts >= cutoff,
    );
    if (scoped) return scoped.content;
  }
  return messages.find((m) => m.role === "user")?.content;
}
