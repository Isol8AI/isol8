import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConfirmActionDialog } from "@/components/admin/ConfirmActionDialog";

function renderDialog(props?: {
  onConfirm?: () => Promise<void> | void;
  confirmText?: string;
  actionLabel?: string;
}) {
  const onConfirm = props?.onConfirm ?? vi.fn();
  const utils = render(
    <ConfirmActionDialog
      confirmText={props?.confirmText ?? "DELETE"}
      actionLabel={props?.actionLabel ?? "Cancel subscription"}
      destructive
      onConfirm={onConfirm}
    >
      <button type="button">Open</button>
    </ConfirmActionDialog>,
  );
  return { ...utils, onConfirm };
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Open" }));
  // Radix portals the dialog content; wait for it to appear.
  await waitFor(() => {
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });
}

function getConfirmButton(actionLabel = "Cancel subscription"): HTMLButtonElement {
  return screen.getByRole("button", {
    name: `Confirm ${actionLabel}`,
  }) as HTMLButtonElement;
}

describe("ConfirmActionDialog", () => {
  it("renders with trigger and disabled confirm initially", async () => {
    const user = userEvent.setup();
    renderDialog();
    await openDialog(user);

    const confirm = getConfirmButton();
    expect(confirm).toBeDisabled();
  });

  it("enables confirm button when correct text typed", async () => {
    const user = userEvent.setup();
    renderDialog({ confirmText: "DELETE" });
    await openDialog(user);

    const input = screen.getByLabelText("Type DELETE to confirm");
    await user.type(input, "DELETE");

    expect(getConfirmButton()).toBeEnabled();
  });

  it("calls onConfirm when correct text typed and clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    renderDialog({ onConfirm, confirmText: "DELETE" });
    await openDialog(user);

    await user.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    await user.click(getConfirmButton());

    await waitFor(() => {
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });
  });

  it("locks dialog after 3 wrong attempts", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    renderDialog({ onConfirm, confirmText: "DELETE" });
    await openDialog(user);

    const input = screen.getByLabelText("Type DELETE to confirm");
    await user.type(input, "WRONG");

    // Three clicks with mismatched text trigger the lockout.
    for (let i = 0; i < 3; i++) {
      await user.click(getConfirmButton());
    }

    expect(onConfirm).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(
        screen.getByText(/Locked\. Reload the page to try again\./i),
      ).toBeInTheDocument();
    });
    expect(getConfirmButton()).toBeDisabled();
  });

  it("aria-busy during async onConfirm", async () => {
    const user = userEvent.setup();
    let resolveConfirm: (() => void) | undefined;
    const onConfirm = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveConfirm = resolve;
        }),
    );
    renderDialog({ onConfirm, confirmText: "DELETE" });
    await openDialog(user);

    await user.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    const confirm = getConfirmButton();
    await user.click(confirm);

    await waitFor(() => {
      expect(getConfirmButton()).toHaveAttribute("aria-busy", "true");
    });
    expect(getConfirmButton()).toHaveTextContent(/Working/);

    resolveConfirm?.();
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
  });
});
