import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
import { useEffect } from "react";

// Module-level handlers — captured from the mocked useGateway so the
// test can drive synthetic events into the provider.
let eventHandler: ((event: string, data: unknown) => void) | null = null;
const sendMock = vi.fn();
const setIsConnected = vi.fn();

const gatewayState = { isConnected: false };

vi.mock("@/hooks/useGateway", () => ({
  useGateway: () => ({
    isConnected: gatewayState.isConnected,
    send: sendMock,
    onEvent: (handler: (event: string, data: unknown) => void) => {
      eventHandler = handler;
      return () => {
        eventHandler = null;
      };
    },
  }),
}));

const mutateMock = vi.fn();
vi.mock("swr", () => ({
  useSWRConfig: () => ({ mutate: mutateMock }),
}));

import { TeamsEventsProvider } from "@/components/teams/TeamsEventsProvider";

beforeEach(() => {
  sendMock.mockReset();
  mutateMock.mockReset();
  setIsConnected.mockReset();
  eventHandler = null;
  gatewayState.isConnected = false;
});

describe("TeamsEventsProvider", () => {
  it("sends teams.subscribe when connected", async () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    expect(sendMock).toHaveBeenCalledWith({ type: "teams.subscribe" });
  });

  it("invalidates inbox + dashboard + activity + issues on teams.activity.logged", async () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    expect(eventHandler).not.toBeNull();

    act(() => {
      eventHandler!("teams.activity.logged", { actor: "u1" });
    });

    const keys = mutateMock.mock.calls.map((c) => c[0]);
    expect(keys).toEqual(expect.arrayContaining([
      "/teams/dashboard", "/teams/activity", "/teams/inbox", "/teams/issues",
    ]));
  });

  it("invalidates dashboard + agents on teams.agent.status", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("teams.agent.status", {});
    });
    const keys = mutateMock.mock.calls.map((c) => c[0]);
    expect(keys).toEqual(expect.arrayContaining(["/teams/dashboard", "/teams/agents"]));
  });

  it("invalidates dashboard + inbox on teams.heartbeat.run.queued", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("teams.heartbeat.run.queued", {});
    });
    const keys = mutateMock.mock.calls.map((c) => c[0]);
    expect(keys).toEqual(expect.arrayContaining(["/teams/dashboard", "/teams/inbox"]));
  });

  it("ignores teams.plugin.* events (no UI bound in v1)", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("teams.plugin.ui.updated", {});
      eventHandler!("teams.plugin.worker.crashed", {});
    });
    expect(mutateMock).not.toHaveBeenCalled();
  });

  it("invalidates every distinct mapped key on teams.stream.resumed", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("teams.stream.resumed", {});
    });
    const keys = mutateMock.mock.calls.map((c) => c[0]);
    // Must include each unique key from the event map.
    expect(keys).toEqual(expect.arrayContaining([
      "/teams/dashboard", "/teams/activity", "/teams/inbox", "/teams/issues", "/teams/agents",
    ]));
  });

  it("re-subscribes and invalidates on isConnected false→true transition", () => {
    gatewayState.isConnected = false;
    const { rerender } = render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    expect(sendMock).not.toHaveBeenCalled();

    gatewayState.isConnected = true;
    rerender(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    expect(sendMock).toHaveBeenCalledWith({ type: "teams.subscribe" });
    // And ALL mapped keys are invalidated as a "no backfill" safety net.
    const keys = mutateMock.mock.calls.map((c) => c[0]);
    expect(keys).toEqual(expect.arrayContaining(["/teams/dashboard", "/teams/inbox"]));
  });

  it("sends teams.unsubscribe on unmount", () => {
    gatewayState.isConnected = true;
    const { unmount } = render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    sendMock.mockClear();
    unmount();
    expect(sendMock).toHaveBeenCalledWith({ type: "teams.unsubscribe" });
  });

  it("ignores non-teams events (e.g. an OpenClaw event leaking through)", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("agent_chat", {});
      eventHandler!("openclaw.something", {});
    });
    expect(mutateMock).not.toHaveBeenCalled();
  });
});

// Coverage-only export to suppress unused-import warning on useEffect.
const _u = useEffect;
void _u;
