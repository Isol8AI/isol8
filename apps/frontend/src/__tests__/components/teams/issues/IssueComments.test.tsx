import { describe, test, expect, vi } from "vitest";
import { render, fireEvent, screen, waitFor } from "@testing-library/react";
import { IssueComments } from "@/components/teams/issues/IssueComments";
import type { IssueComment } from "@/components/teams/shared/types";

const baseComment = (overrides: Partial<IssueComment> = {}): IssueComment => ({
  id: "c1",
  body: "Hello world",
  createdAt: "2026-05-05T12:00:00Z",
  ...overrides,
});

describe("IssueComments", () => {
  test("renders empty state when no comments", () => {
    render(<IssueComments comments={[]} onSubmit={vi.fn()} />);
    expect(screen.getByText(/no comments yet/i)).toBeInTheDocument();
  });

  test("renders loading state when isLoading + empty", () => {
    render(<IssueComments comments={[]} isLoading onSubmit={vi.fn()} />);
    expect(screen.getByText(/loading comments/i)).toBeInTheDocument();
  });

  test("renders list of comments with body", () => {
    const c1 = baseComment({ id: "c1", body: "First" });
    const c2 = baseComment({ id: "c2", body: "Second" });
    render(<IssueComments comments={[c1, c2]} onSubmit={vi.fn()} />);
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
  });

  test("submit button disabled when body empty", () => {
    render(<IssueComments comments={[]} onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: /comment/i })).toBeDisabled();
  });

  test("submit fires onSubmit with trimmed body and clears textarea", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<IssueComments comments={[]} onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText(/add a comment/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "  Hi there  " } });
    fireEvent.click(screen.getByRole("button", { name: /comment/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("Hi there"));
    await waitFor(() => expect(textarea.value).toBe(""));
  });

  test("Cmd+Enter inside textarea triggers submit", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<IssueComments comments={[]} onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText(/add a comment/i);
    fireEvent.change(textarea, { target: { value: "via shortcut" } });
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("via shortcut"));
  });

  test("Ctrl+Enter inside textarea triggers submit", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<IssueComments comments={[]} onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText(/add a comment/i);
    fireEvent.change(textarea, { target: { value: "windows linux" } });
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("windows linux"));
  });

  test("plain Enter (no modifier) does NOT submit (allows newline insertion)", () => {
    const onSubmit = vi.fn();
    render(<IssueComments comments={[]} onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText(/add a comment/i);
    fireEvent.change(textarea, { target: { value: "test" } });
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("error from onSubmit is displayed", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("server boom"));
    render(<IssueComments comments={[]} onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText(/add a comment/i);
    fireEvent.change(textarea, { target: { value: "test" } });
    fireEvent.click(screen.getByRole("button", { name: /comment/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/server boom/);
  });
});
