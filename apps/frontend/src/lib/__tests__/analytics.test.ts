import { describe, it, expect, beforeEach, vi } from "vitest";

// Hoisted mock: the `capture` helper imports posthog-js; we need the mock
// installed before the module-under-test is imported.
const mockCapture = vi.fn();
const mockCaptureException = vi.fn();
const mockState: { __loaded: boolean } = { __loaded: true };

vi.mock("posthog-js", () => {
  const posthog = {
    get __loaded() {
      return mockState.__loaded;
    },
    capture: (...args: unknown[]) => mockCapture(...args),
    captureException: (...args: unknown[]) => mockCaptureException(...args),
  };
  return { default: posthog };
});

// Re-import the module under test per test so the `window` stub flips
// cleanly between SSR and browser. `vi.resetModules()` in beforeEach
// guarantees a fresh module evaluation.
async function importAnalytics() {
  const mod = await import("../analytics");
  return mod;
}

describe("analytics.capture", () => {
  beforeEach(() => {
    vi.resetModules();
    mockCapture.mockReset();
    mockCaptureException.mockReset();
    mockState.__loaded = true;
  });

  it("no-ops when window is undefined (SSR)", async () => {
    // Stash window and blow it away so the guard trips. Restore after.
    const originalWindow = globalThis.window;
    // @ts-expect-error — deliberately shadowing for SSR simulation
    delete globalThis.window;
    try {
      const { capture } = await importAnalytics();
      capture("agent_created", { agent_id: "a1" });
      expect(mockCapture).not.toHaveBeenCalled();
    } finally {
      globalThis.window = originalWindow;
    }
  });

  it("no-ops when PostHog has not finished loading (__loaded=false)", async () => {
    mockState.__loaded = false;
    const { capture } = await importAnalytics();
    capture("agent_deleted", { agent_id: "a1" });
    expect(mockCapture).not.toHaveBeenCalled();
  });

  it("forwards to posthog.capture when loaded", async () => {
    mockState.__loaded = true;
    const { capture } = await importAnalytics();
    capture("chat_message_sent", { agent_id: "a1", message_length: 42 });
    expect(mockCapture).toHaveBeenCalledTimes(1);
    expect(mockCapture).toHaveBeenCalledWith("chat_message_sent", {
      agent_id: "a1",
      message_length: 42,
    });
  });

  it("captureException forwards to posthog.captureException when loaded", async () => {
    mockState.__loaded = true;
    const { captureException } = await importAnalytics();
    const err = new Error("boom");
    captureException(err);
    expect(mockCaptureException).toHaveBeenCalledTimes(1);
    expect(mockCaptureException).toHaveBeenCalledWith(err);
  });

  it("captureException no-ops when PostHog is not loaded", async () => {
    mockState.__loaded = false;
    const { captureException } = await importAnalytics();
    captureException(new Error("silenced"));
    expect(mockCaptureException).not.toHaveBeenCalled();
  });
});
