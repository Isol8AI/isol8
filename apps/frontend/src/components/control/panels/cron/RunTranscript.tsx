"use client";

import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { MessageList } from "@/components/chat/MessageList";
import { adaptSessionMessages, type AdaptedMessage } from "./sessionMessageAdapter";

interface ChatHistoryResp {
  messages?: unknown[];
}

export function RunTranscript({
  sessionKey,
  afterTs,
  beforeTs,
}: {
  sessionKey: string | undefined;
  /**
   * When provided, filters transcript messages to those whose `ts` lies in
   * `[afterTs, beforeTs]`. Messages with no `ts` are conservatively kept so
   * older OpenClaw history formats (pre-ts) still render. Used by
   * RunDetailPanel to scope the transcript to a specific run in multi-run
   * sessions (non-isolated cron jobs share a sessionKey across runs).
   */
  afterTs?: number;
  beforeTs?: number;
}) {
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

  const allMessages = adaptSessionMessages(data?.messages);
  const messages = scopeMessagesToRun(allMessages, afterTs, beforeTs);
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
 * Filters `messages` to those whose `ts` is within `[afterTs, beforeTs]`.
 *
 * - Messages with `ts === undefined` are kept conservatively (older history
 *   formats that predate the timestamp field).
 * - When `afterTs` is undefined, no lower bound is applied.
 * - When `beforeTs` is undefined, no upper bound is applied.
 */
export function scopeMessagesToRun(
  messages: AdaptedMessage[],
  afterTs?: number,
  beforeTs?: number,
): AdaptedMessage[] {
  if (afterTs === undefined && beforeTs === undefined) return messages;
  return messages.filter((m) => {
    if (m.ts === undefined) return true;
    if (afterTs !== undefined && m.ts < afterTs) return false;
    if (beforeTs !== undefined && m.ts > beforeTs) return false;
    return true;
  });
}

/**
 * Returns the first user message in `messages`.
 *
 * - When `afterTs` is provided, returns the first user message whose `ts`
 *   is `>= afterTs` (and `<= beforeTs` if provided). No tolerance window:
 *   in shared/non-isolated sessions with back-to-back manual reruns, a
 *   tolerance can let the previous run's prompt slip in. If no message
 *   has a `ts` in range, returns `undefined` (we deliberately do NOT fall
 *   back to the earliest-overall message — that was the old too-permissive
 *   behavior).
 * - When `afterTs` is undefined, returns the first user message overall
 *   without any `ts` check.
 */
export function firstUserMessage(
  messages: AdaptedMessage[],
  afterTs?: number,
  beforeTs?: number,
): string | undefined {
  if (afterTs !== undefined) {
    const scoped = messages.find(
      (m) =>
        m.role === "user" &&
        m.ts !== undefined &&
        m.ts >= afterTs &&
        (beforeTs === undefined || m.ts <= beforeTs),
    );
    return scoped?.content;
  }
  return messages.find((m) => m.role === "user")?.content;
}
