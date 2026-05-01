import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// The ProviderPicker is currently defined as a non-exported function inside
// ProvisioningStepper.tsx. To test it directly we'll export it from that
// file (see Step 3 of this task) and import it here.
import { ProviderPicker } from "../ProvisioningStepper";

// useApi is invoked inside the component on Pick — stub it.
vi.mock("@/lib/api", () => ({
  useApi: () => ({
    post: vi.fn(),
    get: vi.fn(),
  }),
}));

describe("ProviderPicker", () => {
  it("renders all three provider cards for personal users", () => {
    render(<ProviderPicker isOrg={false} />);
    expect(screen.getByText("Sign in with ChatGPT")).toBeInTheDocument();
    expect(screen.getByText("Bring your own API key")).toBeInTheDocument();
    expect(screen.getByText("Powered by Claude")).toBeInTheDocument();
  });

  it("hides the ChatGPT OAuth card for org users", () => {
    render(<ProviderPicker isOrg={true} orgName="Acme" />);
    expect(screen.queryByText("Sign in with ChatGPT")).not.toBeInTheDocument();
    expect(screen.getByText("Bring your own API key")).toBeInTheDocument();
    expect(screen.getByText("Powered by Claude")).toBeInTheDocument();
  });

  it('uses "Three ways" headline for personal users', () => {
    render(<ProviderPicker isOrg={false} />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "One price. Three ways to power it.",
    );
  });

  it('uses "Two ways" headline for org users', () => {
    render(<ProviderPicker isOrg={true} orgName="Acme" />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "One price. Two ways to power it.",
    );
  });

  it("uses 2-col centered grid for org users and 3-col grid otherwise", () => {
    const { container: orgContainer } = render(
      <ProviderPicker isOrg={true} orgName="Acme" />,
    );
    expect(orgContainer.querySelector(".md\\:grid-cols-2")).toBeInTheDocument();
    expect(orgContainer.querySelector(".max-w-3xl")).toBeInTheDocument();

    const { container: personalContainer } = render(<ProviderPicker isOrg={false} />);
    expect(personalContainer.querySelector(".md\\:grid-cols-3")).toBeInTheDocument();
  });
});
