import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useBilling } from "../useBilling";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({
    getToken: vi.fn().mockResolvedValue("test-token"),
    isSignedIn: true,
  }),
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>
);

describe("useBilling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns null account when /billing/account returns 404 (no row yet)", async () => {
    // Pre-subscribe owners have no billing row; the hook must surface
    // that as the "no account" empty state, not as an error. This is
    // the load-bearing piece of the useApi migration — the hook now
    // catches ApiError(404) where it previously short-circuited at the
    // fetch layer.
    global.fetch = vi.fn().mockResolvedValue(
      new Response(null, { status: 404 }),
    );
    const { result } = renderHook(() => useBilling(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.account).toBeNull();
    expect(result.current.error).toBeUndefined();
    expect(result.current.isSubscribed).toBe(false);
  });

  it("returns the account when /billing/account returns 200", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          is_subscribed: true,
          current_spend: 12.34,
          lifetime_spend: 99.99,
          subscription_status: "active",
          trial_end: null,
          provider_choice: "bedrock_managed",
          byo_provider: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const { result } = renderHook(() => useBilling(), { wrapper });
    await waitFor(() => expect(result.current.account).not.toBeNull());
    expect(result.current.account?.is_subscribed).toBe(true);
    expect(result.current.isSubscribed).toBe(true);
  });

  it("propagates non-404 ApiError as a real error", async () => {
    // Defensive: a 500 must not be silently swallowed into null —
    // the SWR error slot has to surface so callers can render an
    // error state.
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "internal" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { result } = renderHook(() => useBilling(), { wrapper });
    await waitFor(() => expect(result.current.error).toBeDefined());
    expect(result.current.account).toBeUndefined();
  });
});
