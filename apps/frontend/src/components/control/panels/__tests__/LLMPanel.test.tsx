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

  it("calls disconnect, then revalidates SWR after it resolves", async () => {
    mockSWRData.mockReturnValue({ provider_choice: "chatgpt_oauth" });
    mockDisconnect.mockResolvedValueOnce(undefined);
    render(<LLMPanel />);
    fireEvent.click(screen.getByRole("button", { name: /disconnect/i }));
    await waitFor(() => expect(mockDisconnect).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockMutate).toHaveBeenCalled());
    expect(mockDisconnect.mock.invocationCallOrder[0]).toBeLessThan(
      mockMutate.mock.invocationCallOrder[0],
    );
  });

  it("clears busy state and does not revalidate when disconnect fails", async () => {
    mockSWRData.mockReturnValue({ provider_choice: "chatgpt_oauth" });
    mockDisconnect.mockRejectedValueOnce(new Error("network"));
    // The component re-throws the rejection out of the click handler; swallow
    // it on both window (jsdom) and process (node) so vitest's unhandled-
    // rejection guard doesn't fail the run.
    const swallowWin = (e: PromiseRejectionEvent) => e.preventDefault();
    const swallowProc = () => {};
    window.addEventListener("unhandledrejection", swallowWin);
    process.on("unhandledRejection", swallowProc);
    try {
      render(<LLMPanel />);
      const button = screen.getByRole("button", { name: /disconnect/i });
      fireEvent.click(button);
      await waitFor(() => expect(mockDisconnect).toHaveBeenCalled());
      // Busy state cleared (label flips back from "Disconnecting…").
      await waitFor(() => expect(button).toHaveTextContent(/^Disconnect$/));
      // mutate should not have been called on the error path.
      expect(mockMutate).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("unhandledrejection", swallowWin);
      process.off("unhandledRejection", swallowProc);
    }
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

  it("calls onPanelChange('credits') from the Bedrock Manage-credits button when prop provided", () => {
    mockSWRData.mockReturnValue({ provider_choice: "bedrock_claude" });
    const onPanelChange = vi.fn();
    render(<LLMPanel onPanelChange={onPanelChange} />);
    expect(screen.getByText("Powered by Claude")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /manage credits/i }));
    expect(onPanelChange).toHaveBeenCalledWith("credits");
  });

  it("falls back to window.location when onPanelChange is omitted on Bedrock", () => {
    mockSWRData.mockReturnValue({ provider_choice: "bedrock_claude" });
    const originalLocation = window.location;
    // jsdom: replace window.location with a writable stub
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: "" },
    });
    render(<LLMPanel />);
    fireEvent.click(screen.getByRole("button", { name: /manage credits/i }));
    expect(window.location.href).toBe("/chat?panel=credits");
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("renders the empty-state when provider_choice is null", () => {
    mockSWRData.mockReturnValue({ provider_choice: null });
    render(<LLMPanel />);
    // The empty-state copy uses a typographic apostrophe; match either.
    expect(screen.getByText(/haven.{1,3}t picked a provider/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /re-onboard/i })).toBeInTheDocument();
  });

  it("renders the BYOK-incomplete empty-state when provider_choice='byo_key' but byo_provider is missing", () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key", byo_provider: null });
    render(<LLMPanel />);
    expect(
      screen.getByText(/bring-your-own-key configuration is incomplete/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /re-onboard/i })).toBeInTheDocument();
    // Should NOT render the BYO hero/form for an incomplete config.
    expect(screen.queryByText(/Bring your own (OpenAI|Anthropic) key/)).not.toBeInTheDocument();
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
