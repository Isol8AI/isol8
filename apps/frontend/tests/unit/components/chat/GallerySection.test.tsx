import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GallerySection } from "@/components/chat/GallerySection";

const deployMock = vi.fn().mockResolvedValue({
  agent_id: "agent_new",
  name: "Pitch",
  slug: "pitch",
  version: 3,
  skills_added: [],
  plugins_enabled: [],
});
const refreshMock = vi.fn();

vi.mock("@/hooks/useCatalog", () => ({
  useCatalog: () => ({
    agents: [
      { slug: "pitch", name: "Pitch", version: 3, emoji: "🎯", vibe: "", description: "",
        suggested_model: "", suggested_channels: [], required_skills: [], required_plugins: [] },
    ],
    isLoading: false,
    deploy: deployMock,
    refresh: refreshMock,
  }),
}));

vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({ refresh: refreshMock }),
}));

describe("GallerySection", () => {
  it("renders the header and each agent row", () => {
    render(<GallerySection onAgentDeployed={vi.fn()} />);
    expect(screen.getByText(/gallery/i)).toBeInTheDocument();
    expect(screen.getByText("Pitch")).toBeInTheDocument();
  });

  it("calls onAgentDeployed with new agent info after deploy", async () => {
    const onAgentDeployed = vi.fn();
    render(<GallerySection onAgentDeployed={onAgentDeployed} />);
    await userEvent.click(screen.getByRole("button", { name: /deploy pitch/i }));
    await vi.waitFor(() => expect(onAgentDeployed).toHaveBeenCalled());
    expect(onAgentDeployed.mock.calls[0][0]).toMatchObject({ agent_id: "agent_new" });
  });
});
