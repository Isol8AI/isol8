import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";

// Stripe publishable key has to land in process.env BEFORE CreditsPanel is
// imported — its `stripePromise` is computed at module-load time. Without
// this, every test runs against a null stripePromise and the Add button is
// disabled, so clicks never fire. vi.hoisted runs before imports.
vi.hoisted(() => {
  process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY = "pk_test_credits_panel_unit";
});

import { CreditsPanel } from "../CreditsPanel";

const mockBalance = vi.fn();
const mockStartTopUp = vi.fn();
const mockSetAutoReload = vi.fn();
const mockRefresh = vi.fn();
vi.mock("@/hooks/useCredits", () => ({
  useCredits: () => ({
    balance: mockBalance(),
    startTopUp: mockStartTopUp,
    setAutoReload: mockSetAutoReload,
    refresh: mockRefresh,
  }),
}));

// Stripe is mocked at the module level so the CreditsPanel can import
// Elements / PaymentElement / useStripe / useElements without dragging in
// the real Stripe SDK in jsdom (which would fail to load Stripe.js).
vi.mock("@stripe/stripe-js", () => ({
  loadStripe: vi.fn(() => Promise.resolve({})),
}));
vi.mock("@stripe/react-stripe-js", () => ({
  // Pass children through so tests can assert on the inner form.
  Elements: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PaymentElement: () => <div data-testid="stripe-payment-element" />,
  useStripe: () => ({
    confirmPayment: vi.fn(() => Promise.resolve({ error: undefined })),
  }),
  useElements: () => ({}),
}));

describe("CreditsPanel", () => {
  beforeEach(() => {
    mockBalance.mockReset();
    mockStartTopUp.mockReset();
    mockSetAutoReload.mockReset();
    mockRefresh.mockReset();
  });

  it("renders the BALANCE eyebrow + dollar balance from the hook", () => {
    mockBalance.mockReturnValue({ balance_dollars: "12.50", balance_microcents: 12_500_000 });
    render(<CreditsPanel />);
    expect(screen.getByText("BALANCE")).toBeInTheDocument();
    expect(screen.getByText("$12.50")).toBeInTheDocument();
  });

  it("shows $0.00 placeholder when balance is null", () => {
    mockBalance.mockReturnValue(null);
    render(<CreditsPanel />);
    expect(screen.getByText("$0.00")).toBeInTheDocument();
  });

  it("toggles the active style on quick-pick buttons", () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    render(<CreditsPanel />);
    const fiftyButton = screen.getByRole("button", { name: /\$50/ });
    fireEvent.click(fiftyButton);
    expect(fiftyButton.className).toContain("border-[#06402B]");
  });

  it("calls startTopUp with the selected amount when Add is clicked", async () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    mockStartTopUp.mockResolvedValueOnce({ client_secret: "pi_xxx" });
    render(<CreditsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /\$50/ }));
    fireEvent.click(screen.getByRole("button", { name: /add \$50/i }));
    await waitFor(() => expect(mockStartTopUp).toHaveBeenCalledWith(5000));
  });

  it("reveals threshold + amount inputs when Auto-reload is enabled", () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    render(<CreditsPanel />);
    expect(screen.queryByText(/when balance drops below/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText(/when balance drops below/i)).toBeInTheDocument();
    expect(screen.getByText(/charge me/i)).toBeInTheDocument();
  });

  it("calls setAutoReload with the right payload when Save is clicked", async () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    mockSetAutoReload.mockResolvedValueOnce(undefined);
    render(<CreditsPanel />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() =>
      expect(mockSetAutoReload).toHaveBeenCalledWith({
        enabled: true,
        threshold_cents: 500,
        amount_cents: 2000,
      }),
    );
  });

  it("calls refresh when the refresh icon is clicked", () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    render(<CreditsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    expect(mockRefresh).toHaveBeenCalled();
  });

  it("renders the Stripe PaymentElement + Pay button after Add is clicked", async () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    mockStartTopUp.mockResolvedValueOnce({ client_secret: "pi_xxx_secret_yyy" });
    render(<CreditsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /\$50/ }));
    fireEvent.click(screen.getByRole("button", { name: /^add \$50$/i }));
    await waitFor(() => expect(mockStartTopUp).toHaveBeenCalledWith(5000));
    await waitFor(() =>
      expect(screen.getByTestId("stripe-payment-element")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /pay \$50/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    // Quick-pick selectors should be hidden while the payment form is active
    // so the user can't change amount mid-flow.
    expect(screen.queryByRole("button", { name: /^add \$50$/i })).not.toBeInTheDocument();
  });

  it("returns to the picker view when Cancel is clicked during top-up", async () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    mockStartTopUp.mockResolvedValueOnce({ client_secret: "pi_xxx_secret_yyy" });
    render(<CreditsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /\$50/ }));
    fireEvent.click(screen.getByRole("button", { name: /^add \$50$/i }));
    await waitFor(() =>
      expect(screen.getByTestId("stripe-payment-element")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByTestId("stripe-payment-element")).not.toBeInTheDocument();
    // Add button is back, no refresh fired (cancel != success).
    expect(screen.getByRole("button", { name: /^add \$50$/i })).toBeInTheDocument();
    expect(mockRefresh).not.toHaveBeenCalled();
  });

  it("surfaces a top-up start error and does not enter the payment form", async () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    mockStartTopUp.mockRejectedValueOnce(new Error("billing offline"));
    render(<CreditsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /^add \$20$/i }));
    await waitFor(() => expect(screen.getByText("billing offline")).toBeInTheDocument());
    expect(screen.queryByTestId("stripe-payment-element")).not.toBeInTheDocument();
  });
});
