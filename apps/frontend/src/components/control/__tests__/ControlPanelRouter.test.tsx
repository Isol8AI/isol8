import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { ControlPanelRouter } from "../ControlPanelRouter";

const mockSWRData = vi.fn();
vi.mock("swr", () => ({
  default: () => ({ data: mockSWRData(), error: null, isLoading: false, mutate: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  useApi: () => ({ get: vi.fn(), post: vi.fn() }),
}));

// Stub OverviewPanel and CreditsPanel so we can assert which one mounts
// without dragging their full deps into the test sandbox.
vi.mock("../panels/OverviewPanel", () => ({
  OverviewPanel: () => <div data-testid="overview-panel" />,
}));
vi.mock("../panels/CreditsPanel", () => ({
  CreditsPanel: () => <div data-testid="credits-panel" />,
}));
// All other panels can stub-render too — they shouldn't mount in these
// tests but the import graph evaluates the module.
vi.mock("../panels/InstancesPanel", () => ({ InstancesPanel: () => null }));
vi.mock("../panels/SessionsPanel", () => ({ SessionsPanel: () => null }));
vi.mock("../panels/UsagePanel", () => ({ UsagePanel: () => null }));
vi.mock("../panels/CronPanel", () => ({ CronPanel: () => null }));
vi.mock("../panels/AgentsPanel", () => ({ AgentsPanel: () => null }));
vi.mock("../panels/SkillsPanel", () => ({ SkillsPanel: () => null }));
vi.mock("../panels/NodesPanel", () => ({ NodesPanel: () => null }));
vi.mock("../panels/ConfigPanel", () => ({ ConfigPanel: () => null }));
vi.mock("../panels/DebugPanel", () => ({ DebugPanel: () => null }));
vi.mock("../panels/LogsPanel", () => ({ LogsPanel: () => null }));
vi.mock("../panels/LLMPanel", () => ({ LLMPanel: () => null }));

describe("ControlPanelRouter", () => {
  beforeEach(() => {
    mockSWRData.mockReset();
  });

  it("renders CreditsPanel when panel='credits' and user is bedrock_claude", () => {
    mockSWRData.mockReturnValue({ provider_choice: "bedrock_claude" });
    render(<ControlPanelRouter panel="credits" />);
    expect(screen.getByTestId("credits-panel")).toBeInTheDocument();
  });

  it("falls back to OverviewPanel when panel='credits' and user is byo_key", () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key" });
    render(<ControlPanelRouter panel="credits" />);
    expect(screen.getByTestId("overview-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("credits-panel")).not.toBeInTheDocument();
  });

  it("falls back to OverviewPanel when panel='credits' and user is chatgpt_oauth", () => {
    mockSWRData.mockReturnValue({ provider_choice: "chatgpt_oauth" });
    render(<ControlPanelRouter panel="credits" />);
    expect(screen.getByTestId("overview-panel")).toBeInTheDocument();
  });

  it("renders CreditsPanel while /users/me is still loading", () => {
    mockSWRData.mockReturnValue(undefined);
    render(<ControlPanelRouter panel="credits" />);
    expect(screen.getByTestId("credits-panel")).toBeInTheDocument();
  });
});
