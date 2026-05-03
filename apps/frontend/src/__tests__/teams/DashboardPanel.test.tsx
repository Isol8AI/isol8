// Test for DashboardPanel — renders 4 metric cards from /dashboard.
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const mockRead = vi.fn(() => ({
  data: {
    dashboard: {
      agents: 5,
      openIssues: 12,
      runsToday: 87,
      spendCents: 4250,
    },
    sidebar_badges: { inbox: 2 },
  },
  isLoading: false,
  error: null,
  mutate: vi.fn(),
}));

vi.mock("@/hooks/useTeamsApi", () => ({
  useTeamsApi: () => ({
    read: mockRead,
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  }),
}));

import { DashboardPanel } from "@/components/teams/panels/DashboardPanel";

describe("DashboardPanel", () => {
  it("renders 4 metric cards with correct values", () => {
    render(<DashboardPanel />);
    expect(screen.getByText("Overview")).toBeInTheDocument();
    expect(screen.getByText("Agents")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Open issues")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Runs today")).toBeInTheDocument();
    expect(screen.getByText("87")).toBeInTheDocument();
    expect(screen.getByText("Spend ($)")).toBeInTheDocument();
    // 4250 cents → $42.50
    expect(screen.getByText("42.50")).toBeInTheDocument();
  });
});
