import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ApprovalCard } from "@/components/chat/ApprovalCard";
import type { ApprovalRequest } from "@/components/chat/MessageList";

const baseRequest: ApprovalRequest = {
  id: "approval-123",
  command: "whoami",
  commandArgv: ["whoami"],
  host: "node",
  cwd: "/Users/prasiddha",
  resolvedPath: "/usr/bin/whoami",
  agentId: "main",
  sessionKey: "personal.user_abc.main",
  allowedDecisions: ["allow-once", "allow-always", "deny"],
};

describe("ApprovalCard", () => {
  it("renders the command text as the primary line", () => {
    render(<ApprovalCard pending={baseRequest} onDecide={vi.fn()} />);
    expect(screen.getByText("whoami")).toBeInTheDocument();
  });
});

describe("ApprovalCard layout", () => {
  it("renders host badge, cwd, and agent name", () => {
    render(<ApprovalCard pending={baseRequest} onDecide={vi.fn()} />);
    expect(screen.getByText("node")).toBeInTheDocument();
    expect(screen.getByText("/Users/prasiddha")).toBeInTheDocument();
    expect(screen.getByText("main")).toBeInTheDocument();
  });

  it("renders all three decision buttons when allowedDecisions includes them all", () => {
    render(<ApprovalCard pending={baseRequest} onDecide={vi.fn()} />);
    expect(screen.getByRole("button", { name: /allow once/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /trust/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /deny/i })).toBeEnabled();
  });

  it("disables Trust when allow-always is not in allowedDecisions", () => {
    const r: ApprovalRequest = { ...baseRequest, allowedDecisions: ["allow-once", "deny"] };
    render(<ApprovalCard pending={r} onDecide={vi.fn()} />);
    expect(screen.getByRole("button", { name: /trust/i })).toBeDisabled();
  });

  it("calls onDecide with the correct decision on click", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalCard pending={baseRequest} onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: /allow once/i }));
    expect(onDecide).toHaveBeenCalledWith("allow-once");
  });

  it("shows resolvedPath and argv when Details is toggled open", () => {
    render(<ApprovalCard pending={baseRequest} onDecide={vi.fn()} />);
    expect(screen.queryByText("/usr/bin/whoami")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /details/i }));
    expect(screen.getByText("/usr/bin/whoami")).toBeInTheDocument();
  });
});
