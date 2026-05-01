import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { LLMPanel } from "../LLMPanel";

const mockSWRData = vi.fn();
const mockMutate = vi.fn();
vi.mock("swr", () => ({
  default: () => ({ data: mockSWRData(), error: null, isLoading: false, mutate: mockMutate }),
}));

const mockApiPut = vi.fn();
vi.mock("@/lib/api", () => ({
  useApi: () => ({
    get: vi.fn(),
    post: vi.fn(),
    put: mockApiPut,
  }),
}));

const mockDisconnect = vi.fn();
vi.mock("@/hooks/useChatGPTOAuth", () => ({
  useChatGPTOAuth: () => ({ disconnect: mockDisconnect }),
}));

describe("LLMPanel", () => {
  beforeEach(() => {
    mockSWRData.mockReset();
    mockMutate.mockReset();
    mockApiPut.mockReset();
    mockDisconnect.mockReset();
  });

  it("renders the ChatGPT hero + Connected status + Disconnect button for chatgpt_oauth", () => {
    mockSWRData.mockReturnValue({ provider_choice: "chatgpt_oauth" });
    render(<LLMPanel />);
    expect(screen.getByText("Sign in with ChatGPT")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /disconnect/i })).toBeInTheDocument();
  });

  it("calls disconnect and revalidates SWR when Disconnect is clicked", async () => {
    mockSWRData.mockReturnValue({ provider_choice: "chatgpt_oauth" });
    mockDisconnect.mockResolvedValueOnce(undefined);
    render(<LLMPanel />);
    fireEvent.click(screen.getByRole("button", { name: /disconnect/i }));
    await waitFor(() => expect(mockDisconnect).toHaveBeenCalledTimes(1));
    expect(mockMutate).toHaveBeenCalled();
  });

  it("renders the OpenAI hero + Replace key form for byo_key + openai", () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key", byo_provider: "openai" });
    render(<LLMPanel />);
    expect(screen.getByText("Bring your own OpenAI key")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/sk-proj-/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument();
  });

  it("renders the Anthropic hero for byo_key + anthropic", () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key", byo_provider: "anthropic" });
    render(<LLMPanel />);
    expect(screen.getByText("Bring your own Anthropic key")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/sk-ant-/)).toBeInTheDocument();
  });

  it("renders the Bedrock hero + Manage credits button for bedrock_claude", () => {
    mockSWRData.mockReturnValue({ provider_choice: "bedrock_claude" });
    render(<LLMPanel />);
    expect(screen.getByText("Powered by Claude")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /manage credits/i })).toBeInTheDocument();
  });

  it("renders the empty-state when provider_choice is null", () => {
    mockSWRData.mockReturnValue({ provider_choice: null });
    render(<LLMPanel />);
    expect(screen.getByText(/haven't picked a provider/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /re-onboard/i })).toBeInTheDocument();
  });

  it("surfaces a save error from PUT /settings/keys/{provider}", async () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key", byo_provider: "openai" });
    mockApiPut.mockRejectedValueOnce(new Error("Invalid key"));
    render(<LLMPanel />);
    const input = screen.getByPlaceholderText(/sk-proj-/);
    fireEvent.change(input, { target: { value: "sk-proj-bad" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(screen.getByText("Invalid key")).toBeInTheDocument());
  });
});
