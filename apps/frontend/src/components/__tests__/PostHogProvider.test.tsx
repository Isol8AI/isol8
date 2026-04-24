import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// Mock posthog-js before any imports that use it
const mockInit = vi.fn();
const mockCapture = vi.fn();
const mockCaptureException = vi.fn();
const mockIdentify = vi.fn();
const mockReset = vi.fn();

vi.mock("posthog-js", () => {
  const posthog = {
    __loaded: true,
    init: mockInit,
    capture: mockCapture,
    captureException: mockCaptureException,
    identify: mockIdentify,
    reset: mockReset,
  };
  return { default: posthog };
});

vi.mock("posthog-js/react", () => ({
  PostHogProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="ph-provider">{children}</div>
  ),
}));

// Clerk mocks — the provider reads `useAuth`/`useUser` but we don't care
// about sign-in state in these tests.
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isSignedIn: false, userId: null }),
  useUser: () => ({ user: null }),
}));

// Stubs for usePathname/useSearchParams: PostHogPageview reads them and
// they'd otherwise throw outside a Next router context.
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(""),
}));

describe("PostHogProvider", () => {
  const originalKey = process.env.NEXT_PUBLIC_POSTHOG_KEY;

  afterEach(() => {
    if (originalKey === undefined) {
      delete process.env.NEXT_PUBLIC_POSTHOG_KEY;
    } else {
      process.env.NEXT_PUBLIC_POSTHOG_KEY = originalKey;
    }
  });

  beforeEach(() => {
    vi.resetModules();
    mockInit.mockClear();
    mockCapture.mockClear();
    mockCaptureException.mockClear();
    mockIdentify.mockClear();
    mockReset.mockClear();
    delete process.env.NEXT_PUBLIC_POSTHOG_KEY;
  });

  it("does NOT initialize PostHog when NEXT_PUBLIC_POSTHOG_KEY is not set", async () => {
    delete process.env.NEXT_PUBLIC_POSTHOG_KEY;

    const mod = await import("../PostHogProvider");
    render(
      <mod.PostHogProvider>
        <div>child content</div>
      </mod.PostHogProvider>
    );

    expect(mockInit).not.toHaveBeenCalled();
  });

  it("initializes PostHog with session_recording + same-origin api_host when key is set", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test_key_123";

    const mod = await import("../PostHogProvider");
    render(
      <mod.PostHogProvider>
        <div>child content</div>
      </mod.PostHogProvider>
    );

    expect(mockInit).toHaveBeenCalledTimes(1);
    const [key, opts] = mockInit.mock.calls[0] as [string, Record<string, unknown>];
    expect(key).toBe("phc_test_key_123");
    // Same-origin proxy (see the next.config.ts /ingest rewrite) — not
    // the env-var driven host from the old test.
    expect(opts.api_host).toBe("/ingest");
    expect(opts.ui_host).toBe("https://us.posthog.com");
    expect(opts.person_profiles).toBe("identified_only");
    expect(opts.capture_pageview).toBe(false);
    expect(opts.capture_pageleave).toBe(true);
    // Session replay must be enabled with masking defaults.
    expect(opts.disable_session_recording).toBe(false);
    const recording = opts.session_recording as {
      maskAllInputs: boolean;
      maskInputOptions: { password: boolean; email: boolean };
      blockSelector: string;
    };
    expect(recording.maskAllInputs).toBe(false);
    expect(recording.maskInputOptions.password).toBe(true);
    expect(recording.blockSelector).toBe("[data-private]");
  });

  it("renders children when NEXT_PUBLIC_POSTHOG_KEY is not set", async () => {
    delete process.env.NEXT_PUBLIC_POSTHOG_KEY;

    const mod = await import("../PostHogProvider");
    render(
      <mod.PostHogProvider>
        <div data-testid="child">Hello</div>
      </mod.PostHogProvider>
    );

    expect(screen.getByTestId("child")).toBeTruthy();
    expect(screen.getByText("Hello")).toBeTruthy();
  });

  it("renders children when NEXT_PUBLIC_POSTHOG_KEY is set", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test_key_123";

    const mod = await import("../PostHogProvider");
    render(
      <mod.PostHogProvider>
        <div data-testid="child">Hello</div>
      </mod.PostHogProvider>
    );

    expect(screen.getByTestId("child")).toBeTruthy();
    expect(screen.getByText("Hello")).toBeTruthy();
  });

  it("forwards uncaught window errors to posthog.captureException", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test_key_123";

    const mod = await import("../PostHogProvider");
    render(
      <mod.PostHogProvider>
        <div>child</div>
      </mod.PostHogProvider>
    );

    const err = new Error("kaboom");
    const ev = new ErrorEvent("error", { error: err, message: "kaboom" });
    window.dispatchEvent(ev);

    expect(mockCaptureException).toHaveBeenCalledTimes(1);
    expect(mockCaptureException).toHaveBeenCalledWith(err);
  });
});
