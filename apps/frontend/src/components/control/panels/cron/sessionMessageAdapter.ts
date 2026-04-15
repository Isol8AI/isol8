export interface AdaptedMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
}

interface RawContentBlock {
  type: string;
  text?: string;
}

interface RawMessage {
  role: string;
  content?: RawContentBlock[];
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
    out.push({
      id: `history-${out.length}`,
      role: m.role,
      content,
      ...(thinking ? { thinking } : {}),
    });
  }
  return out;
}
