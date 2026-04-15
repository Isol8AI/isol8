import { describe, it, expect } from "vitest";
import { adaptSessionMessages } from "@/components/control/panels/cron/sessionMessageAdapter";

describe("adaptSessionMessages", () => {
  it("maps user and assistant turns with text content", () => {
    const raw = [
      { role: "user", content: [{ type: "text", text: "hi" }] },
      { role: "assistant", content: [{ type: "text", text: "hello" }] },
    ];
    const msgs = adaptSessionMessages(raw);
    expect(msgs).toEqual([
      { id: "history-0", role: "user", content: "hi" },
      { id: "history-1", role: "assistant", content: "hello" },
    ]);
  });

  it("extracts thinking blocks into `thinking` field", () => {
    const raw = [
      {
        role: "assistant",
        content: [
          { type: "thinking", text: "considering options" },
          { type: "text", text: "here you go" },
        ],
      },
    ];
    expect(adaptSessionMessages(raw)).toEqual([
      { id: "history-0", role: "assistant", content: "here you go", thinking: "considering options" },
    ]);
  });

  it("filters out system/tool messages and empty content", () => {
    const raw = [
      { role: "system", content: [{ type: "text", text: "boot" }] },
      { role: "tool", content: [] },
      { role: "user", content: [] },
      { role: "assistant", content: [{ type: "text", text: "done" }] },
    ];
    expect(adaptSessionMessages(raw)).toEqual([
      { id: "history-0", role: "assistant", content: "done" },
    ]);
  });
});
