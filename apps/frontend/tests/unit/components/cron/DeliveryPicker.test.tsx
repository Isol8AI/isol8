import { useState } from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DeliveryPicker } from "@/components/control/panels/cron/DeliveryPicker";
import type { CronDelivery } from "@/components/control/panels/cron/types";

// --- Mock useGatewayRpc so channels.status returns a controlled snapshot ---

type RpcResult = {
  data: unknown;
  error: Error | undefined;
  isLoading: boolean;
  mutate: () => void;
};

let mockChannelAccounts: Record<string, { accountId: string }[]> = {};

vi.mock("@/hooks/useGatewayRpc", () => ({
  useGatewayRpc: (method: string | null): RpcResult => {
    if (method === "channels.status") {
      return {
        data: { channelAccounts: mockChannelAccounts },
        error: undefined,
        isLoading: false,
        mutate: () => {},
      };
    }
    return { data: undefined, error: undefined, isLoading: false, mutate: () => {} };
  },
}));

function renderPicker(overrides: {
  value?: CronDelivery | undefined;
  accounts?: Record<string, { accountId: string }[]>;
} = {}) {
  mockChannelAccounts = overrides.accounts ?? {
    telegram: [{ accountId: "a1" }],
    discord: [],
    slack: [],
  };
  const onChange = vi.fn();
  const utils = render(
    <DeliveryPicker value={overrides.value} onChange={onChange} />,
  );
  return { ...utils, onChange };
}

describe("DeliveryPicker", () => {
  beforeEach(() => {
    mockChannelAccounts = {};
  });

  it("mode=None hides channel/account/to fields", () => {
    renderPicker({ value: { mode: "none" } });

    // Only the mode segmented buttons are visible. No channel label, no To
    // input, no Webhook URL input.
    expect(screen.queryByLabelText("Delivery channel")).toBeNull();
    expect(screen.queryByLabelText("Delivery to")).toBeNull();
    expect(screen.queryByLabelText("Webhook URL")).toBeNull();
  });

  it("mode=Announce shows channel dropdown with Chat + Telegram only (discord/slack empty)", () => {
    renderPicker({
      value: { mode: "announce" },
      accounts: {
        telegram: [{ accountId: "a1" }],
        discord: [],
        slack: [],
      },
    });

    const channelSelect = screen.getByLabelText("Delivery channel") as HTMLSelectElement;
    const optionLabels = Array.from(channelSelect.options).map((o) => o.textContent);
    expect(optionLabels).toContain("Chat");
    expect(optionLabels).toContain("Telegram");
    expect(optionLabels).not.toContain("Discord");
    expect(optionLabels).not.toContain("Slack");
  });

  it("selecting Telegram (single account) auto-selects account and shows to + threadId", () => {
    const { onChange } = renderPicker({
      value: { mode: "announce" },
      accounts: { telegram: [{ accountId: "a1" }] },
    });

    const channelSelect = screen.getByLabelText("Delivery channel") as HTMLSelectElement;
    fireEvent.change(channelSelect, { target: { value: "telegram" } });

    // onChange called with auto-selected accountId and telegram channel.
    expect(onChange).toHaveBeenCalled();
    const arg = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(arg).toMatchObject({
      mode: "announce",
      channel: "telegram",
      accountId: "a1",
    });
  });

  it("telegram with multiple accounts renders account picker; single account hides it", () => {
    // Multi-account: picker visible.
    const { unmount } = renderPicker({
      value: { mode: "announce", channel: "telegram" },
      accounts: { telegram: [{ accountId: "a1" }, { accountId: "a2" }] },
    });

    expect(screen.getByLabelText("Delivery account")).toBeInTheDocument();
    expect(screen.getByLabelText("Delivery to")).toBeInTheDocument();
    // Telegram supports threads.
    expect(screen.getByLabelText("Delivery thread id")).toBeInTheDocument();
    unmount();

    // Single account: picker hidden.
    renderPicker({
      value: { mode: "announce", channel: "telegram", accountId: "a1" },
      accounts: { telegram: [{ accountId: "a1" }] },
    });
    expect(screen.queryByLabelText("Delivery account")).toBeNull();
    expect(screen.getByLabelText("Delivery to")).toBeInTheDocument();
  });

  it("mode=Webhook shows URL input only; invalid URL shows error", () => {
    const { onChange } = renderPicker({
      value: { mode: "webhook", to: "not a url" },
    });

    // URL input is visible.
    const urlInput = screen.getByLabelText("Webhook URL") as HTMLInputElement;
    expect(urlInput).toBeInTheDocument();
    expect(urlInput.value).toBe("not a url");

    // Channel dropdown is NOT shown in webhook mode.
    expect(screen.queryByLabelText("Delivery channel")).toBeNull();

    // Invalid URL shows the inline error.
    expect(screen.getByText(/Enter a valid http\(s\) URL/)).toBeInTheDocument();

    // Typing a valid URL should call onChange (we just assert the handler is
    // wired up).
    fireEvent.change(urlInput, { target: { value: "https://example.com/hook" } });
    expect(onChange).toHaveBeenCalled();
  });

  it("preserves failureDestination when toggling mode webhook -> announce -> none -> webhook", () => {
    mockChannelAccounts = { telegram: [{ accountId: "a1" }] };

    // Start with a webhook delivery that already has a configured failure
    // destination (announce → telegram).
    const observed: (CronDelivery | undefined)[] = [];
    function Harness() {
      const [value, setValue] = useState<CronDelivery | undefined>({
        mode: "webhook",
        to: "https://example.com/hook",
        failureDestination: {
          mode: "announce",
          channel: "telegram",
          accountId: "a1",
          to: "@ops",
        },
      });
      return (
        <DeliveryPicker
          value={value}
          onChange={(d) => {
            observed.push(d);
            setValue(d);
          }}
        />
      );
    }
    render(<Harness />);

    // webhook -> announce: failureDestination must survive.
    fireEvent.click(screen.getByRole("button", { name: /^Announce$/ }));
    const afterToAnnounce = observed[observed.length - 1];
    expect(afterToAnnounce?.mode).toBe("announce");
    expect(afterToAnnounce?.failureDestination).toEqual({
      mode: "announce",
      channel: "telegram",
      accountId: "a1",
      to: "@ops",
    });

    // announce -> none: failureDestination must still survive (user can
    // only clear it via the explicit "Remove failure destination" button).
    fireEvent.click(screen.getByRole("button", { name: /^None$/ }));
    const afterToNone = observed[observed.length - 1];
    expect(afterToNone?.mode).toBe("none");
    expect(afterToNone?.failureDestination).toEqual({
      mode: "announce",
      channel: "telegram",
      accountId: "a1",
      to: "@ops",
    });

    // none -> webhook: failureDestination must survive the round-trip.
    fireEvent.click(screen.getByRole("button", { name: /^Webhook$/ }));
    const afterToWebhook = observed[observed.length - 1];
    expect(afterToWebhook?.mode).toBe("webhook");
    expect(afterToWebhook?.failureDestination).toEqual({
      mode: "announce",
      channel: "telegram",
      accountId: "a1",
      to: "@ops",
    });
  });

  it("failure-destination toggle: open renders nested picker, change writes failureDestination and drops threadId/bestEffort", () => {
    mockChannelAccounts = { telegram: [{ accountId: "a1" }] };

    const observed: (CronDelivery | undefined)[] = [];
    function Harness() {
      const [value, setValue] = useState<CronDelivery | undefined>({
        mode: "announce",
      });
      return (
        <DeliveryPicker
          value={value}
          onChange={(d) => {
            observed.push(d);
            setValue(d);
          }}
        />
      );
    }
    render(<Harness />);

    // Initially collapsed — the nested picker is not rendered.
    expect(screen.queryByTestId("delivery-picker-nested")).toBeNull();

    // Toggle open.
    fireEvent.click(
      screen.getByRole("button", {
        name: /Send failures to a different destination/,
      }),
    );

    // Nested picker visible with custom label and no "None" mode.
    const nested = screen.getByTestId("delivery-picker-nested");
    expect(
      within(nested).getByText(
        /Where to send failure notifications \(if different\)/,
      ),
    ).toBeInTheDocument();
    expect(
      within(nested).queryByRole("button", { name: /^None$/ }),
    ).toBeNull();

    // Switch nested mode to Webhook.
    fireEvent.click(within(nested).getByRole("button", { name: /^Webhook$/ }));

    // After state flush the URL input is rendered — type a URL.
    const nested2 = screen.getByTestId("delivery-picker-nested");
    const urlInput = within(nested2).getByLabelText("Webhook URL");
    fireEvent.change(urlInput, { target: { value: "https://fail.example.com" } });

    // Outer onChange observed a value whose failureDestination is a webhook
    // pointing at the URL, with no threadId/bestEffort.
    const matching = observed.find(
      (v) =>
        v?.failureDestination?.mode === "webhook" &&
        v.failureDestination.to === "https://fail.example.com",
    );
    expect(matching).toBeDefined();
    expect(matching?.failureDestination).not.toHaveProperty("threadId");
    expect(matching?.failureDestination).not.toHaveProperty("bestEffort");
  });
});
