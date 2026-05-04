import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Minimal Clerk mocks — pending invitations + no memberships + no org.
const buildClerkMocks = (
  overrides: { invitations?: unknown[]; memberships?: unknown[] } = {},
) => ({
  useAuth: () => ({ isLoaded: true, orgId: null }),
  useUser: () => ({ user: { update: vi.fn() } }),
  useOrganization: () => ({ organization: null, isLoaded: true }),
  useOrganizationList: () => ({
    userMemberships: { data: overrides.memberships ?? [] },
    userInvitations: {
      data: overrides.invitations ?? [],
      revalidate: vi.fn(),
    },
    isLoaded: true,
    setActive: vi.fn(),
  }),
  CreateOrganization: () => <div>CreateOrganization mock</div>,
});

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ useApi: () => ({ syncUser: vi.fn() }) }));
vi.mock("posthog-js/react", () => ({ usePostHog: () => null }));

describe("OnboardingPage", () => {
  // vitest caches dynamically-imported modules, so a `vi.doMock` registered
  // in test N has no effect on test N+1 unless we reset the module cache
  // (and the previous mock) between tests.
  beforeEach(() => {
    vi.resetModules();
    vi.doUnmock("@clerk/nextjs");
  });

  it("forces invitation mode when pending invitations exist — no Skip button", async () => {
    vi.doMock("@clerk/nextjs", () =>
      buildClerkMocks({
        invitations: [
          {
            id: "orginv_1",
            publicOrganizationData: { name: "Acme Org" },
            accept: vi.fn(),
          },
        ],
      }),
    );
    const { default: Page } = await import("../page");
    render(<Page />);
    // Invitation card is shown — the org name is the unique anchor
    // (the "Pending invitation" helper text appears alongside it but
    // is not a single-match anchor).
    expect(screen.getByText("Acme Org")).toBeInTheDocument();
    // No "Skip invitations" escape hatch
    expect(
      screen.queryByRole("button", { name: /skip invitations/i }),
    ).toBeNull();
  });

  it("renders the personal/org chooser when no pending invitations", async () => {
    vi.doMock("@clerk/nextjs", () => buildClerkMocks());
    const { default: Page } = await import("../page");
    render(<Page />);
    expect(
      screen.getByRole("button", { name: /personal/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /organization/i }),
    ).toBeInTheDocument();
  });
});
