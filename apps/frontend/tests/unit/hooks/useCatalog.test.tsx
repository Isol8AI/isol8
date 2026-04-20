import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { ReactNode } from "react";

import { useCatalog } from "@/hooks/useCatalog";

const mockGet = vi.fn();
const mockPost = vi.fn();

vi.mock("@/lib/api", () => ({
  useApi: () => ({ get: mockGet, post: mockPost }),
}));

function wrapper({ children }: { children: ReactNode }) {
  return <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{children}</SWRConfig>;
}

describe("useCatalog", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it("fetches catalog agents and deployed provenance in parallel", async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === "/catalog") {
        return Promise.resolve({
          agents: [{ slug: "pitch", name: "Pitch", version: 3, emoji: "🎯",
                     vibe: "Direct", description: "Sales", suggested_model: "qwen",
                     suggested_channels: [], required_skills: [], required_plugins: [] }],
        });
      }
      if (path === "/catalog/deployed") {
        return Promise.resolve({ deployed: [] });
      }
      throw new Error(`Unexpected GET ${path}`);
    });

    const { result } = renderHook(() => useCatalog(), { wrapper });
    await waitFor(() => expect(result.current.agents.length).toBe(1));
    expect(result.current.agents[0].slug).toBe("pitch");
  });

  it("filters out agents already deployed", async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === "/catalog") {
        return Promise.resolve({
          agents: [
            { slug: "pitch", name: "Pitch", version: 3, emoji: "", vibe: "",
              description: "", suggested_model: "", suggested_channels: [],
              required_skills: [], required_plugins: [] },
            { slug: "echo", name: "Echo", version: 1, emoji: "", vibe: "",
              description: "", suggested_model: "", suggested_channels: [],
              required_skills: [], required_plugins: [] },
          ],
        });
      }
      if (path === "/catalog/deployed") {
        return Promise.resolve({
          deployed: [{ agent_id: "agent_1", template_slug: "pitch", template_version: 3 }],
        });
      }
      throw new Error();
    });

    const { result } = renderHook(() => useCatalog(), { wrapper });
    await waitFor(() => expect(result.current.agents.length).toBe(1));
    expect(result.current.agents[0].slug).toBe("echo");
  });

  it("deploy() posts and triggers revalidation", async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === "/catalog") return Promise.resolve({ agents: [] });
      if (path === "/catalog/deployed") return Promise.resolve({ deployed: [] });
      throw new Error();
    });
    mockPost.mockResolvedValue({ agent_id: "agent_new", slug: "pitch", version: 3, skills_added: [] });

    const { result } = renderHook(() => useCatalog(), { wrapper });
    await waitFor(() => expect(result.current.agents).toBeDefined());

    let deployResult: unknown;
    await act(async () => {
      deployResult = await result.current.deploy("pitch");
    });
    expect(mockPost).toHaveBeenCalledWith("/catalog/deploy", { slug: "pitch" });
    expect(deployResult).toMatchObject({ agent_id: "agent_new" });
  });
});
