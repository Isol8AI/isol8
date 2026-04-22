import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { unpublishMock } = vi.hoisted(() => ({
  unpublishMock: vi.fn(async () => ({ ok: true, status: 200 })),
}));
vi.mock("@/app/admin/_actions/catalog", () => ({
  unpublishSlug: unpublishMock,
}));

vi.mock("@/components/admin/ConfirmActionDialog", () => ({
  ConfirmActionDialog: ({
    children,
    onConfirm,
    confirmText,
  }: {
    children: React.ReactNode;
    onConfirm: () => Promise<void>;
    confirmText: string;
  }) => (
    <div data-testid="confirm-dialog" data-confirm-text={confirmText}>
      {children}
      <button onClick={onConfirm}>__confirm__</button>
    </div>
  ),
}));

import { CatalogRowActions } from "@/app/admin/catalog/CatalogRowActions";

describe("CatalogRowActions", () => {
  beforeEach(() => {
    unpublishMock.mockReset();
    unpublishMock.mockResolvedValue({ ok: true, status: 200 });
  });

  it("renders Unpublish + View versions buttons", () => {
    render(
      <CatalogRowActions slug="pitch" name="Pitch" onOpenVersions={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /unpublish/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /view versions/i }),
    ).toBeInTheDocument();
  });

  it("calls unpublishSlug with the slug when the confirm dialog fires", async () => {
    render(
      <CatalogRowActions slug="pitch" name="Pitch" onOpenVersions={vi.fn()} />,
    );
    const confirm = within(screen.getByTestId("confirm-dialog")).getByText(
      "__confirm__",
    );
    await userEvent.click(confirm);
    expect(unpublishMock).toHaveBeenCalledWith("pitch");
  });

  it("sets confirm text to 'unpublish <slug>'", () => {
    render(
      <CatalogRowActions slug="pitch" name="Pitch" onOpenVersions={vi.fn()} />,
    );
    const dialog = screen.getByTestId("confirm-dialog");
    expect(dialog.getAttribute("data-confirm-text")).toBe("unpublish pitch");
  });

  it("calls onOpenVersions when View versions clicked", async () => {
    const onOpenVersions = vi.fn();
    render(
      <CatalogRowActions
        slug="pitch"
        name="Pitch"
        onOpenVersions={onOpenVersions}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: /view versions/i }),
    );
    expect(onOpenVersions).toHaveBeenCalledWith("pitch");
  });
});
