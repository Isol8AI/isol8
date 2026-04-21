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

  it("is a scaffold", () => {
    // Placeholder test - real assertions come in later tasks.
    expect(true).toBe(true);
  });
});
