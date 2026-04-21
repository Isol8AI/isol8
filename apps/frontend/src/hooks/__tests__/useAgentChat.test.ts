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
  // Unique agent id per test: the hook has a module-level `_messageCache`
  // keyed by `${agentId}:${sessionName}` that persists across tests. Even
  // with `vi.resetModules()`, using a fresh id per test is a belt-and-braces
  // guarantee that no state leaks between cases.
  const nextAgent = (() => {
    let i = 0;
    return () => `agent-${++i}`;
  })();

  beforeEach(() => {
    chatHandlers = [];
    eventHandlers = [];
    sendReq.mockReset().mockResolvedValue({});
    sendChat.mockReset();
    // Reset modules between tests so the module-level `_messageCache`
    // and `_needsBootstrap` inside useAgentChat don't leak state.
    // vi.mock() for useGateway hoists and is re-applied per module load.
    vi.resetModules();
  });

  it("creates one bubble per runId and mirrors cumulative chunk content", async () => {
    const useAgentChat = await importHook();
    const agentId = nextAgent();
    const { result } = renderHook(() => useAgentChat(agentId, "main"));

    // Send a user message
    await act(async () => {
      await result.current.sendMessage("hello");
    });

    // First chunk for runId=R1 creates the bubble.
    emit({ type: "chunk", content: "Hi", agent_id: agentId, runId: "R1" });

    // Find the assistant message
    const assistants = result.current.messages.filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].content).toBe("Hi");
    expect(result.current.isStreaming).toBe(true);

    // Second chunk — cumulative text for R1
    emit({ type: "chunk", content: "Hi there", agent_id: agentId, runId: "R1" });
    expect(result.current.messages.filter((m) => m.role === "assistant")[0].content).toBe("Hi there");

    // done finalizes
    emit({ type: "done", agent_id: agentId, runId: "R1" });
    expect(result.current.isStreaming).toBe(false);
  });

  it("renders two assistant bubbles when two runIds stream within one chat.send", async () => {
    const useAgentChat = await importHook();
    const agentId = nextAgent();
    const { result } = renderHook(() => useAgentChat(agentId, "main"));

    await act(async () => {
      await result.current.sendMessage("do it");
    });

    // Run 1
    emit({ type: "chunk", content: "Let me try", agent_id: agentId, runId: "R1" });
    emit({ type: "done", agent_id: agentId, runId: "R1" });

    // Run 2 — different runId, should create a new bubble
    emit({ type: "chunk", content: "Done.", agent_id: agentId, runId: "R2" });
    emit({ type: "done", agent_id: agentId, runId: "R2" });

    const assistants = result.current.messages.filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(2);
    expect(assistants[0].content).toBe("Let me try");
    expect(assistants[1].content).toBe("Done.");
    expect(result.current.isStreaming).toBe(false);
  });

  it("isStreaming stays true while any run is active (union of runs)", async () => {
    const useAgentChat = await importHook();
    const agentId = nextAgent();
    const { result } = renderHook(() => useAgentChat(agentId, "main"));

    await act(async () => {
      await result.current.sendMessage("work");
    });

    emit({ type: "chunk", content: "a", agent_id: agentId, runId: "R1" });
    expect(result.current.isStreaming).toBe(true);

    // Second run starts before first finishes (interleaved deltas)
    emit({ type: "chunk", content: "b", agent_id: agentId, runId: "R2" });
    expect(result.current.isStreaming).toBe(true);

    emit({ type: "done", agent_id: agentId, runId: "R1" });
    // Still streaming — R2 still active
    expect(result.current.isStreaming).toBe(true);

    emit({ type: "done", agent_id: agentId, runId: "R2" });
    // All runs done — streaming false
    expect(result.current.isStreaming).toBe(false);
  });

  it("error with runId finalizes only that bubble; other runs continue", async () => {
    const useAgentChat = await importHook();
    const agentId = nextAgent();
    const { result } = renderHook(() => useAgentChat(agentId, "main"));

    await act(async () => {
      await result.current.sendMessage("dual");
    });

    emit({ type: "chunk", content: "a", agent_id: agentId, runId: "R1" });
    emit({ type: "chunk", content: "b", agent_id: agentId, runId: "R2" });

    // Error on R1
    emit({ type: "error", message: "oh no", agent_id: agentId, runId: "R1" });

    const assistants = result.current.messages.filter((m) => m.role === "assistant");
    const r1 = assistants.find((m) => m.content.includes("Error:"));
    expect(r1).toBeTruthy();
    expect(result.current.isStreaming).toBe(true); // R2 still active

    emit({ type: "done", agent_id: agentId, runId: "R2" });
    expect(result.current.isStreaming).toBe(false);
  });

  it("error without runId clears all active runs", async () => {
    const useAgentChat = await importHook();
    const agentId = nextAgent();
    const { result } = renderHook(() => useAgentChat(agentId, "main"));

    await act(async () => {
      await result.current.sendMessage("multi");
    });

    emit({ type: "chunk", content: "x", agent_id: agentId, runId: "R1" });
    emit({ type: "chunk", content: "y", agent_id: agentId, runId: "R2" });

    // Global error (no runId)
    emit({ type: "error", message: "global fail", agent_id: undefined });

    expect(result.current.isStreaming).toBe(false);
  });

  it("sendMessage does NOT create an assistant placeholder before first event", async () => {
    const useAgentChat = await importHook();
    const agentId = nextAgent();
    const { result } = renderHook(() => useAgentChat(agentId, "main"));

    await act(async () => {
      await result.current.sendMessage("hi");
    });

    // Only a user message exists; no assistant placeholder yet. `runsRef` is
    // hook-internal, so we assert on the observable outcome: after
    // sendMessage resolves but before any chunk arrives, there should be
    // zero assistant messages.
    expect(
      result.current.messages.filter((m) => m.role === "assistant"),
    ).toHaveLength(0);
    expect(result.current.isStreaming).toBe(true); // sendMessage sets isStreaming = true early
  });

  it("approval.requested event matches toolCallId across any assistant bubble", async () => {
    const useAgentChat = await importHook();
    const agentId = nextAgent();
    const { result } = renderHook(() => useAgentChat(agentId, "main"));

    await act(async () => {
      await result.current.sendMessage("install");
    });

    // Chunk + tool_start into R1
    emit({ type: "chunk", content: "Running", agent_id: agentId, runId: "R1" });
    emit({
      type: "tool_start",
      tool: "exec",
      toolCallId: "tc-1",
      agent_id: agentId,
      runId: "R1",
    });

    // First run finishes with tool_use; second run starts
    emit({ type: "done", agent_id: agentId, runId: "R1" });
    emit({ type: "chunk", content: "More", agent_id: agentId, runId: "R2" });

    // Approval event arrives for the tool in R1's bubble (not the active R2).
    emitEvent("exec.approval.requested", {
      id: "appr-1",
      request: {
        command: "rm -rf /tmp/foo",
        host: "gateway" as const,
        agentId: agentId,
        toolCallId: "tc-1",
        allowedDecisions: ["allow-once", "deny"],
      },
    });

    // Expect R1's bubble to have the tool in pending-approval status.
    const r1 = result.current.messages.find((m) =>
      m.toolUses?.some((t) => t.toolCallId === "tc-1"),
    );
    expect(r1).toBeDefined();
    const tool = r1!.toolUses!.find((t) => t.toolCallId === "tc-1")!;
    expect(tool.status).toBe("pending-approval");
  });
});
