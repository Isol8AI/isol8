import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// Mock posthog-js before any imports that use it
const mockInit = vi.fn();
const mockCapture = vi.fn();
const mockIdentify = vi.fn();
const mockReset = vi.fn();

vi.mock("posthog-js", () => {
  const posthog = {
    init: mockInit,
    capture: mockCapture,
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

describe("PostHogProvider", () => {
  const originalKey = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  const originalHost = process.env.NEXT_PUBLIC_POSTHOG_HOST;

  afterEach(() => {
    // Restore original env
    if (originalKey === undefined) {
      delete process.env.NEXT_PUBLIC_POSTHOG_KEY;
    } else {
      process.env.NEXT_PUBLIC_POSTHOG_KEY = originalKey;
    }
    if (originalHost === undefined) {
      delete process.env.NEXT_PUBLIC_POSTHOG_HOST;
    } else {
      process.env.NEXT_PUBLIC_POSTHOG_HOST = originalHost;
    }
  });

  beforeEach(() => {
    vi.resetModules();
    mockInit.mockClear();
    mockCapture.mockClear();
    mockIdentify.mockClear();
    mockReset.mockClear();
    delete process.env.NEXT_PUBLIC_POSTHOG_KEY;
    delete process.env.NEXT_PUBLIC_POSTHOG_HOST;
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

  it("initializes PostHog when NEXT_PUBLIC_POSTHOG_KEY is set", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test_key_123";
    process.env.NEXT_PUBLIC_POSTHOG_HOST = "https://ph.example.com";

    const mod = await import("../PostHogProvider");
    render(
      <mod.PostHogProvider>
        <div>child content</div>
      </mod.PostHogProvider>
    );

    expect(mockInit).toHaveBeenCalledWith("phc_test_key_123", {
      api_host: "https://ph.example.com",
      person_profiles: "identified_only",
      capture_pageview: false,
      capture_pageleave: true,
    });
  });

  it("renders children when NEXT_PUBLIC_POSTHOG_KEY is not set", async () => {
    delete process.env.NEXT_PUBLIC_POSTHOG_KEY;

    const mod = await import("../PostHogProvider");
    render(
      <mod.PostHogProvider>
        <div data-testid="child">Hello</div>
      </mod.PostHogProvider>
    );

    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("renders children when NEXT_PUBLIC_POSTHOG_KEY is set", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test_key_123";

    const mod = await import("../PostHogProvider");
    render(
      <mod.PostHogProvider>
        <div data-testid="child">Hello</div>
      </mod.PostHogProvider>
    );

    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });
});
