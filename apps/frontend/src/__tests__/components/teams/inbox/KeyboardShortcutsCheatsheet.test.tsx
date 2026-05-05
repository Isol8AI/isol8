import { test, expect } from "vitest";
import { render } from "@testing-library/react";
import { KeyboardShortcutsCheatsheetContent } from "@/components/teams/inbox/KeyboardShortcutsCheatsheet";

test("renders Inbox section heading + at least 4 shortcuts", () => {
  const { getByText, container } = render(<KeyboardShortcutsCheatsheetContent />);
  expect(getByText(/inbox/i)).toBeInTheDocument();
  expect(container.querySelectorAll("kbd").length).toBeGreaterThanOrEqual(4);
});
