import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
