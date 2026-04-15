export interface AdaptedMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  /**
   * Wall-clock timestamp (ms since epoch) of the underlying message, when
   * the OpenClaw history payload supplies one. Used by RunDetailPanel to
   * scope the displayed prompt to a specific run in multi-run sessions —
   * see `firstUserMessage` in RunTranscript.tsx.
   */
  ts?: number;
}

interface RawContentBlock {
  type: string;
  text?: string;
}

interface RawMessage {
  role: string;
  content?: RawContentBlock[];
  /** OpenClaw history messages typically carry `ts` in ms; some shapes use `timestamp`. */
  ts?: number;
  timestamp?: number;
}

function extractText(content: RawContentBlock[] | undefined): string {
  if (!content) return "";
  return content
    .filter((b) => b.type === "text" && typeof b.text === "string")
    .map((b) => b.text)
    .join("");
}

function extractThinking(content: RawContentBlock[] | undefined): string | undefined {
  if (!content) return undefined;
  const thinking = content
    .filter((b) => b.type === "thinking" && typeof b.text === "string")
    .map((b) => b.text)
    .join("");
  return thinking || undefined;
}

/**
 * Adapts a raw session-message payload from `chat.history` / `sessions.get`
 * into the Message shape MessageList consumes. Mirrors the decoder in
 * useAgentChat.ts:193-204 with two deliberate departures:
 *   1. `id` uses the output array's length, not the raw-input index, so
 *      filtered entries (non-user/assistant, empty content) don't leave
 *      gaps in the sequence — produces stable, dense React keys.
 *   2. Role filtering and empty-content filtering happen in one pass
 *      rather than filter/map/filter, so a message with neither text nor
 *      thinking is dropped before receiving an id.
 */
export function adaptSessionMessages(raw: unknown[] | undefined): AdaptedMessage[] {
  if (!raw) return [];
  const out: AdaptedMessage[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const m = item as RawMessage;
    if (m.role !== "user" && m.role !== "assistant") continue;
    const content = extractText(m.content);
    const thinking = extractThinking(m.content);
    if (!content && !thinking) continue;
    const tsRaw = typeof m.ts === "number" ? m.ts : m.timestamp;
    const ts = typeof tsRaw === "number" && Number.isFinite(tsRaw) ? tsRaw : undefined;
    out.push({
      id: `history-${out.length}`,
      role: m.role,
      content,
      ...(thinking ? { thinking } : {}),
      ...(ts !== undefined ? { ts } : {}),
    });
  }
  return out;
}
