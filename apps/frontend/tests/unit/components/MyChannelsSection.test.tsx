import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { MyChannelsSection } from "@/components/settings/MyChannelsSection";

const mockData = {
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
    default: () => ({ data: mockData, error: null, isLoading: false, mutate: vi.fn() }),
  };
});

vi.mock("@/lib/api", () => ({
  useApi: () => ({
    get: vi.fn().mockResolvedValue(mockData),
    del: vi.fn(),
  }),
}));

describe("MyChannelsSection", () => {
  it("lists bots grouped by provider", () => {
    render(<MyChannelsSection />);
    expect(screen.getByText(/telegram/i)).toBeInTheDocument();
    expect(screen.getByText(/@main/)).toBeInTheDocument();
    expect(screen.getByText(/@sales/)).toBeInTheDocument();
  });

  it("shows Link button for unlinked bots", () => {
    render(<MyChannelsSection />);
    expect(screen.getByRole("button", { name: /^link$/i })).toBeInTheDocument();
  });

  it("shows Unlink for linked bots", () => {
    render(<MyChannelsSection />);
    expect(screen.getByRole("button", { name: /unlink/i })).toBeInTheDocument();
  });

  it("shows empty state with Agents-tab hint for non-admin members", () => {
    render(<MyChannelsSection />);
    // Discord has no bots and can_create_bots is false
    expect(screen.getByText(/no discord bots/i)).toBeInTheDocument();
  });
});
