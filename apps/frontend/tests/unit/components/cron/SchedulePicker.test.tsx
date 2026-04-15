import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import {
  SchedulePicker,
  scheduleIsValid,
  type SchedulePickerFields,
} from "@/components/control/panels/cron/SchedulePicker";

const EMPTY: SchedulePickerFields = {
  scheduleKind: "cron",
  cronExpr: "",
  cronTz: "",
  everyValue: 30,
  everyUnit: "minutes",
  atDatetime: "",
};

function renderPicker(overrides: Partial<SchedulePickerFields> = {}) {
  const onFieldChange = vi.fn();
  const fields = { ...EMPTY, ...overrides };
  const utils = render(
    <SchedulePicker {...fields} onFieldChange={onFieldChange} />,
  );
  return { ...utils, onFieldChange, fields };
}

describe("SchedulePicker", () => {
  it("cron kind shows expression input, timezone input, and next-fires preview for valid expr", () => {
    renderPicker({
      scheduleKind: "cron",
      cronExpr: "0 9 * * *",
      cronTz: "UTC",
    });

    const exprInput = screen.getByLabelText("Cron expression") as HTMLInputElement;
    expect(exprInput).toBeInTheDocument();
    expect(exprInput.value).toBe("0 9 * * *");

    const tzInput = screen.getByLabelText("Timezone") as HTMLInputElement;
    expect(tzInput).toBeInTheDocument();
    expect(tzInput.value).toBe("UTC");

    const preview = screen.getByTestId("schedule-picker-next-fires");
    expect(preview).toBeInTheDocument();
    const items = within(preview).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    // TZ is shown in the preview heading.
    expect(within(preview).getByText(/Next fires \(UTC\)/)).toBeInTheDocument();
  });

  it("every kind shows number input and unit dropdown", () => {
    const { onFieldChange } = renderPicker({
      scheduleKind: "every",
      everyValue: 30,
      everyUnit: "minutes",
    });

    const valueInput = screen.getByLabelText("Interval value") as HTMLInputElement;
    expect(valueInput).toBeInTheDocument();
    expect(valueInput.value).toBe("30");

    const unit = screen.getByLabelText("Interval unit") as HTMLSelectElement;
    expect(unit).toBeInTheDocument();
    expect(unit.value).toBe("minutes");

    fireEvent.change(unit, { target: { value: "hours" } });
    expect(onFieldChange).toHaveBeenCalledWith("everyUnit", "hours");
  });

  it("at kind shows datetime-local input", () => {
    const { onFieldChange } = renderPicker({
      scheduleKind: "at",
      atDatetime: "2026-05-01T09:00",
    });

    const dt = screen.getByLabelText("Run at") as HTMLInputElement;
    expect(dt).toBeInTheDocument();
    expect(dt.type).toBe("datetime-local");
    expect(dt.value).toBe("2026-05-01T09:00");

    fireEvent.change(dt, { target: { value: "2026-06-01T12:00" } });
    expect(onFieldChange).toHaveBeenCalledWith("atDatetime", "2026-06-01T12:00");
  });

  it("next-fires preview shows 3 parsed dates for a valid cron expression", () => {
    renderPicker({
      scheduleKind: "cron",
      cronExpr: "0 * * * *", // every hour at minute 0
      cronTz: "UTC",
    });

    const preview = screen.getByTestId("schedule-picker-next-fires");
    const items = within(preview).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    // Each item should render a non-empty string (a formatted locale date).
    for (const item of items) {
      expect(item.textContent?.length ?? 0).toBeGreaterThan(0);
    }
  });

  it("invalid cron expression shows an error and marks the input invalid (no preview list)", () => {
    renderPicker({
      scheduleKind: "cron",
      cronExpr: "not-a-cron",
    });

    const exprInput = screen.getByLabelText("Cron expression") as HTMLInputElement;
    expect(exprInput.className).toMatch(/border-destructive/);

    // cronstrue error text appears in the validation line.
    const errors = screen.getAllByText(/.+/, { selector: ".text-destructive" });
    expect(errors.length).toBeGreaterThan(0);

    // No next-fires preview block is rendered for invalid expressions.
    expect(screen.queryByTestId("schedule-picker-next-fires")).toBeNull();

    // scheduleIsValid helper agrees.
    expect(
      scheduleIsValid({
        ...EMPTY,
        scheduleKind: "cron",
        cronExpr: "not-a-cron",
      }),
    ).toBe(false);
  });
});
