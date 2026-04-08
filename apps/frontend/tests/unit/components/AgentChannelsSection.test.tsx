import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { AgentChannelsSection } from "@/components/control/panels/AgentChannelsSection";

const mockData = {
  telegram: [{ agent_id: "main", bot_username: "main", linked: true }],
  discord: [],
  slack: [],
  can_create_bots: true,
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

describe("AgentChannelsSection", () => {
  it("renders telegram, discord, and slack (no whatsapp)", () => {
    render(<AgentChannelsSection agentId="main" />);
    expect(screen.getByText(/telegram/i)).toBeInTheDocument();
    expect(screen.getByText(/discord/i)).toBeInTheDocument();
    expect(screen.getByText(/slack/i)).toBeInTheDocument();
    expect(screen.queryByText(/whatsapp/i)).not.toBeInTheDocument();
  });

  it("shows add-bot buttons when can_create_bots is true", () => {
    render(<AgentChannelsSection agentId="main" />);
    expect(screen.getAllByRole("button", { name: /add.*bot/i }).length).toBeGreaterThan(0);
  });
});
