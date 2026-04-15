import type { ComponentProps } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import {
  JobEditDialog,
  EMPTY_FORM,
  type FormState,
} from "@/components/control/panels/cron/JobEditDialog";

// --- Mock useGatewayRpc ---
//
// DeliveryPicker (rendered in the open Delivery section) and ToolsAllowlist
// and useAgents (in Failure alerts / Advanced) all go through useGatewayRpc.
// Return empty data for every method so nothing throws.

type RpcResult = {
  data: unknown;
  error: Error | undefined;
  isLoading: boolean;
  mutate: () => void;
};

vi.mock("@/hooks/useGatewayRpc", () => ({
  useGatewayRpc: (method: string | null): RpcResult => {
    if (method === "channels.status") {
      return {
        data: { channelAccounts: {} },
        error: undefined,
        isLoading: false,
        mutate: () => {},
      };
    }
    if (method === "tools.catalog") {
      return {
        data: { groups: [] },
        error: undefined,
        isLoading: false,
        mutate: () => {},
      };
    }
    if (method === "agents.list") {
      return {
        data: { defaultId: "a1", agents: [{ id: "a1", name: "Agent One" }] },
        error: undefined,
        isLoading: false,
        mutate: () => {},
      };
    }
    return { data: undefined, error: undefined, isLoading: false, mutate: () => {} };
  },
  useGatewayRpcMutation: () => vi.fn(),
}));

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

  // --- Task 16 ---

  it("EMPTY_FORM create-defaults: scheduleKind=every, wakeMode=next-heartbeat, failureAlert off", () => {
    expect(EMPTY_FORM.scheduleKind).toBe("every");
    expect(EMPTY_FORM.everyValue).toBe(1);
    expect(EMPTY_FORM.everyUnit).toBe("days");
    expect(EMPTY_FORM.enabled).toBe(true);
    expect(EMPTY_FORM.wakeMode).toBe("next-heartbeat");
    expect(EMPTY_FORM.failureAlertEnabled).toBe(false);
    expect(EMPTY_FORM.failureAlertAfter).toBe(3);
    expect(EMPTY_FORM.failureAlertCooldownMs).toBe(3_600_000);
    expect(EMPTY_FORM.deleteAfterRun).toBe(false);
  });

  it("Failure alerts: toggling enabled reveals after/cooldown inputs", () => {
    renderDialog();

    const failureHeader = screen.getByRole("button", { name: /^Failure alerts$/ });
    fireEvent.click(failureHeader);

    // Toggle the master switch on.
    const toggle = screen.getByLabelText(/Alert me when this job fails/);
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);

    // After/cooldown inputs appear.
    expect(screen.getByLabelText(/^Failure alert after$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Failure alert cooldown value$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Failure alert cooldown unit$/)).toBeInTheDocument();
  });

  it("Advanced: wakeMode defaults to next-heartbeat and segmented buttons flip it", () => {
    const { props } = renderDialog();

    // Default: initial form's wakeMode is carried from EMPTY_FORM spread.
    expect(baseInitial.wakeMode).toBe("next-heartbeat");

    // Open Advanced section.
    const advancedHeader = screen.getByRole("button", { name: /^Advanced$/ });
    fireEvent.click(advancedHeader);

    // Click "Now" to flip wakeMode.
    fireEvent.click(screen.getByRole("button", { name: /^Now$/ }));

    // Save and verify outgoing form state.
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ wakeMode: "now" }),
    );
  });

  it("Advanced: enabling deleteAfterRun shows inline confirmation", () => {
    renderDialog();

    const advancedHeader = screen.getByRole("button", { name: /^Advanced$/ });
    fireEvent.click(advancedHeader);

    const toggle = screen.getByLabelText(/Delete after first successful run/);
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);

    // Confirmation banner is present with Cancel + Enable anyway buttons.
    expect(screen.getByText(/will.*delete this cron job/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Enable anyway$/ }),
    ).toBeInTheDocument();
  });
});
