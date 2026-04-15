import type { ComponentProps } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import {
  JobEditDialog,
  EMPTY_FORM,
  type FormState,
} from "@/components/control/panels/cron/JobEditDialog";

const baseInitial: FormState = {
  ...EMPTY_FORM,
  name: "Daily digest",
  scheduleKind: "cron",
  cronExpr: "0 7 * * *",
  message: "Summarize today's news",
};

function renderDialog(overrides: Partial<ComponentProps<typeof JobEditDialog>> = {}) {
  const props = {
    initial: baseInitial,
    onSave: vi.fn(),
    onCancel: vi.fn(),
    saving: false,
    ...overrides,
  };
  const utils = render(<JobEditDialog {...props} />);
  return { ...utils, props };
}

describe("JobEditDialog", () => {
  it("renders Basics and Delivery sections open, others closed", () => {
    renderDialog();

    // All five section headers are present.
    const basicsHeader = screen.getByRole("button", { name: /^Basics$/ });
    const deliveryHeader = screen.getByRole("button", { name: /^Delivery$/ });
    const agentHeader = screen.getByRole("button", { name: /^Agent execution$/ });
    const failureHeader = screen.getByRole("button", { name: /^Failure alerts$/ });
    const advancedHeader = screen.getByRole("button", { name: /^Advanced$/ });

    expect(basicsHeader.getAttribute("aria-expanded")).toBe("true");
    expect(deliveryHeader.getAttribute("aria-expanded")).toBe("true");
    expect(agentHeader.getAttribute("aria-expanded")).toBe("false");
    expect(failureHeader.getAttribute("aria-expanded")).toBe("false");
    expect(advancedHeader.getAttribute("aria-expanded")).toBe("false");
  });

  it("calls onSave with current form state when Save is clicked", () => {
    const { props } = renderDialog();

    const saveBtn = screen.getByRole("button", { name: /^Save$/ });
    fireEvent.click(saveBtn);

    expect(props.onSave).toHaveBeenCalledTimes(1);
    // Form state matches initial because no edits were made.
    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Daily digest",
        scheduleKind: "cron",
        cronExpr: "0 7 * * *",
        message: "Summarize today's news",
        enabled: true,
      }),
    );
  });

  it("calls onCancel when Cancel is clicked", () => {
    const { props } = renderDialog();

    const cancelBtn = screen.getByRole("button", { name: /^Cancel$/ });
    fireEvent.click(cancelBtn);

    expect(props.onCancel).toHaveBeenCalledTimes(1);
  });
});
