import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useProvisioningState } from "../useProvisioningState";

// Clerk's useAuth — return a stub.
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({
    getToken: vi.fn().mockResolvedValue("test-token"),
    isSignedIn: true,
  }),
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  // Fresh SWR cache per test to avoid cross-test pollution.
  <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>
);

describe("useProvisioningState", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns phase=normal when /status returns 200 with a container", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "running",
          substatus: "gateway_healthy",
          service_name: "x",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const { result } = renderHook(() => useProvisioningState(), { wrapper });
    await waitFor(() => expect(result.current.phase).toBe("normal"));
    expect(result.current.container?.status).toBe("running");
    expect(result.current.blocked).toBeNull();
  });

  it("returns phase=blocked when /status returns 402 with blocked payload", async () => {
    // Real wire shape: FastAPI's HTTPException(detail=gate.to_payload())
    // serializes to {"detail": {"blocked": {...}}}. Codex P1 on PR #519
    // flagged that the parser was reading body.blocked instead of
    // body.detail.blocked; this test now pins the real backend shape.
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            blocked: {
              code: "credits_required",
              title: "Top up Claude credits",
              message: "Top up some Claude credits to start your Bedrock container.",
              action: {
                kind: "link",
                label: "Top up now",
                href: "/settings/billing#credits",
                admin_only: false,
              },
              owner_role: "admin",
            },
          },
        }),
        { status: 402, headers: { "Content-Type": "application/json" } },
      ),
    );
    const { result } = renderHook(() => useProvisioningState(), { wrapper });
    await waitFor(() => expect(result.current.phase).toBe("blocked"));
    expect(result.current.blocked?.code).toBe("credits_required");
    expect(result.current.blocked?.action.href).toBe("/settings/billing#credits");
    expect(result.current.refreshInterval).toBe(5000);
  });

  it("also accepts a top-level blocked payload (defensive fallback)", async () => {
    // Older mocks / non-FastAPI proxies may put blocked at the top
    // level; the parser should still accept it for resilience.
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          blocked: {
            code: "credits_required",
            title: "",
            message: "",
            action: { kind: "link", label: "", href: "", admin_only: false },
            owner_role: "admin",
          },
        }),
        { status: 402, headers: { "Content-Type": "application/json" } },
      ),
    );
    const { result } = renderHook(() => useProvisioningState(), { wrapper });
    await waitFor(() => expect(result.current.phase).toBe("blocked"));
    expect(result.current.blocked?.code).toBe("credits_required");
  });

  it("returns phase=provision-needed when /status returns 404", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));
    const { result } = renderHook(() => useProvisioningState(), { wrapper });
    await waitFor(() => expect(result.current.phase).toBe("provision-needed"));
    expect(result.current.container).toBeNull();
    expect(result.current.blocked).toBeNull();
  });

  it("polls every 5s for the first minute while blocked", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          blocked: {
            code: "credits_required",
            title: "",
            message: "",
            action: { kind: "link", label: "", href: "", admin_only: false },
            owner_role: "admin",
          },
        }),
        { status: 402, headers: { "Content-Type": "application/json" } },
      ),
    );
    const { result } = renderHook(() => useProvisioningState(), { wrapper });
    await waitFor(() => expect(result.current.phase).toBe("blocked"));
    expect(result.current.refreshInterval).toBe(5000);
  });
});
