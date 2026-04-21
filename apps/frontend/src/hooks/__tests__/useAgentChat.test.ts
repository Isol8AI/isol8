import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { ChatIncomingMessage } from "../useGateway";

// --- Mocks ---------------------------------------------------------------

// Chat-message handlers registered by useAgentChat.
let chatHandlers: Array<(msg: ChatIncomingMessage) => void> = [];
let eventHandlers: Array<(name: string, data: unknown) => void> = [];

const sendReq = vi.fn().mockResolvedValue({});
const sendChat = vi.fn();

vi.mock("../useGateway", () => ({
  useGateway: () => ({
    isConnected: true,
    nodeConnected: false,
    error: null,
    reconnectAttempt: 0,
    send: vi.fn(),
    sendReq,
    sendChat,
    onEvent: (h: (name: string, data: unknown) => void) => {
      eventHandlers.push(h);
      return () => {
        eventHandlers = eventHandlers.filter((x) => x !== h);
      };
    },
    onChatMessage: (h: (msg: ChatIncomingMessage) => void) => {
      chatHandlers.push(h);
      return () => {
        chatHandlers = chatHandlers.filter((x) => x !== h);
      };
    },
    reconnect: vi.fn(),
  }),
}));

vi.mock("posthog-js", () => ({
  default: { capture: vi.fn() },
}));

// Helpers to drive the hook from tests.
function emit(msg: ChatIncomingMessage) {
  act(() => {
    chatHandlers.forEach((h) => h(msg));
  });
}

function emitEvent(name: string, data: unknown) {
  act(() => {
    eventHandlers.forEach((h) => h(name, data));
  });
}

async function importHook() {
  const mod = await import("../useAgentChat");
  return mod.useAgentChat;
}

describe("useAgentChat — multi-bubble", () => {
  beforeEach(() => {
    chatHandlers = [];
    eventHandlers = [];
    sendReq.mockReset().mockResolvedValue({});
    sendChat.mockReset();
  });

  it("creates one bubble per runId and mirrors cumulative chunk content", async () => {
    const useAgentChat = await importHook();
    const { result } = renderHook(() => useAgentChat("agent-A", "main"));

    // Send a user message
    await act(async () => {
      await result.current.sendMessage("hello");
    });

    // First chunk for runId=R1 creates the bubble.
    emit({ type: "chunk", content: "Hi", agent_id: "agent-A", runId: "R1" });

    // Find the assistant message
    const assistants = result.current.messages.filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].content).toBe("Hi");
    expect(result.current.isStreaming).toBe(true);

    // Second chunk — cumulative text for R1
    emit({ type: "chunk", content: "Hi there", agent_id: "agent-A", runId: "R1" });
    expect(result.current.messages.filter((m) => m.role === "assistant")[0].content).toBe("Hi there");

    // done finalizes
    emit({ type: "done", agent_id: "agent-A", runId: "R1" });
    expect(result.current.isStreaming).toBe(false);
  });

  it("renders two assistant bubbles when two runIds stream within one chat.send", async () => {
    const useAgentChat = await importHook();
    const { result } = renderHook(() => useAgentChat("agent-A", "main"));

    await act(async () => {
      await result.current.sendMessage("do it");
    });

    // Run 1
    emit({ type: "chunk", content: "Let me try", agent_id: "agent-A", runId: "R1" });
    emit({ type: "done", agent_id: "agent-A", runId: "R1" });

    // Run 2 — different runId, should create a new bubble
    emit({ type: "chunk", content: "Done.", agent_id: "agent-A", runId: "R2" });
    emit({ type: "done", agent_id: "agent-A", runId: "R2" });

    const assistants = result.current.messages.filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(2);
    expect(assistants[0].content).toBe("Let me try");
    expect(assistants[1].content).toBe("Done.");
    expect(result.current.isStreaming).toBe(false);
  });

  it("isStreaming stays true while any run is active (union of runs)", async () => {
    const useAgentChat = await importHook();
    const { result } = renderHook(() => useAgentChat("agent-A", "main"));

    await act(async () => {
      await result.current.sendMessage("work");
    });

    emit({ type: "chunk", content: "a", agent_id: "agent-A", runId: "R1" });
    expect(result.current.isStreaming).toBe(true);

    // Second run starts before first finishes (interleaved deltas)
    emit({ type: "chunk", content: "b", agent_id: "agent-A", runId: "R2" });
    expect(result.current.isStreaming).toBe(true);

    emit({ type: "done", agent_id: "agent-A", runId: "R1" });
    // Still streaming — R2 still active
    expect(result.current.isStreaming).toBe(true);

    emit({ type: "done", agent_id: "agent-A", runId: "R2" });
    // All runs done — streaming false
    expect(result.current.isStreaming).toBe(false);
  });
});
