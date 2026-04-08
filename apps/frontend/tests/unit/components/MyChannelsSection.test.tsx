import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { MyChannelsSection } from "@/components/settings/MyChannelsSection";

interface MockBot {
  agent_id: string;
  bot_username: string;
  linked: boolean;
}

interface MockResponse {
  telegram: MockBot[];
  discord: MockBot[];
  slack: MockBot[];
  can_create_bots: boolean;
}

let currentMockData: MockResponse;

const defaultMock: MockResponse = {
  telegram: [
    { agent_id: "main", bot_username: "main", linked: true },
    { agent_id: "sales", bot_username: "sales", linked: false },
  ],
  discord: [],
  slack: [],
  can_create_bots: false,
};

vi.mock("swr", async () => {
  const actual = await vi.importActual<typeof import("swr")>("swr");
  return {
    ...actual,
    default: () => ({
      data: currentMockData,
      error: null,
      isLoading: false,
      mutate: vi.fn(),
    }),
  };
});

vi.mock("@/lib/api", () => ({
  useApi: () => ({
    get: vi.fn().mockResolvedValue(currentMockData),
    del: vi.fn(),
  }),
}));

beforeEach(() => {
  currentMockData = { ...defaultMock };
});

describe("MyChannelsSection", () => {
  it("lists bots grouped by provider", () => {
    render(<MyChannelsSection />);
    expect(screen.getByText(/telegram/i)).toBeInTheDocument();
    expect(screen.getByText(/@main/)).toBeInTheDocument();
    expect(screen.getByText(/@sales/)).toBeInTheDocument();
  });

  it("shows Link button for unlinked bots", () => {
    render(<MyChannelsSection />);
    // After fix 5, buttons have aria-labels like "Link your Telegram to sales".
    // Use getAllByRole + name regex so future test variants with multiple
    // unlinked bots don't break this assertion.
    const linkButtons = screen.getAllByRole("button", {
      name: /^Link your .* to /i,
    });
    expect(linkButtons.length).toBeGreaterThan(0);
  });

  it("shows Unlink for linked bots", () => {
    render(<MyChannelsSection />);
    const unlinkButtons = screen.getAllByRole("button", {
      name: /^Unlink your .* from /i,
    });
    expect(unlinkButtons.length).toBeGreaterThan(0);
  });

  it("shows empty state with Agents-tab hint for non-admin members", () => {
    render(<MyChannelsSection />);
    // Discord has no bots and can_create_bots is false
    expect(screen.getByText(/no discord bots/i)).toBeInTheDocument();
    // Admin-only hint must NOT appear when can_create_bots is false
    expect(screen.queryByText(/set one up from your agent/i)).not.toBeInTheDocument();
  });

  it("shows admin hint in empty state when can_create_bots is true", () => {
    currentMockData = {
      telegram: [],
      discord: [],
      slack: [],
      can_create_bots: true,
    };
    render(<MyChannelsSection />);
    // The hint should appear in all three empty providers
    const hints = screen.getAllByText(/set one up from your agent/i);
    expect(hints.length).toBeGreaterThan(0);
  });
});
