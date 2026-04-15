import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ToolsAllowlist } from "@/components/control/panels/cron/ToolsAllowlist";

// --- Mock useGatewayRpc so tools.catalog returns a controlled snapshot ---

type RpcResult = {
  data: unknown;
  error: Error | undefined;
  isLoading: boolean;
  mutate: () => void;
};

interface CatalogGroup {
  id: string;
  tools: { id: string; label?: string }[];
}

let mockCatalogGroups: CatalogGroup[] = [];

vi.mock("@/hooks/useGatewayRpc", () => ({
  useGatewayRpc: (method: string | null): RpcResult => {
    if (method === "tools.catalog") {
      return {
        data: { groups: mockCatalogGroups },
        error: undefined,
        isLoading: false,
        mutate: () => {},
      };
    }
    return { data: undefined, error: undefined, isLoading: false, mutate: () => {} };
  },
}));

const DEFAULT_GROUPS: CatalogGroup[] = [
  { id: "core", tools: [{ id: "bash" }, { id: "web_search" }] },
];

describe("ToolsAllowlist", () => {
  beforeEach(() => {
    mockCatalogGroups = DEFAULT_GROUPS;
  });

  it("renders optgroups and options for each catalog group/tool", () => {
    mockCatalogGroups = [
      { id: "core", tools: [{ id: "bash" }, { id: "web_search" }] },
      { id: "plugins", tools: [{ id: "custom_tool" }] },
    ];
    render(
      <ToolsAllowlist agentId={undefined} value={undefined} onChange={vi.fn()} />,
    );

    const select = screen.getByLabelText(/add tool from catalog/i) as HTMLSelectElement;
    const optgroups = select.querySelectorAll("optgroup");
    expect(optgroups).toHaveLength(2);
    expect(optgroups[0].getAttribute("label")).toBe("core");
    expect(optgroups[1].getAttribute("label")).toBe("plugins");

    // Each tool rendered as <option>.
    expect(within(select).getByRole("option", { name: /bash/ })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: /web_search/ })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: /custom_tool/ })).toBeInTheDocument();
  });

  it("selecting a tool from the dropdown adds it as a chip via onChange", () => {
    const onChange = vi.fn();
    render(
      <ToolsAllowlist agentId={undefined} value={undefined} onChange={onChange} />,
    );

    const select = screen.getByLabelText(/add tool from catalog/i);
    fireEvent.change(select, { target: { value: "bash" } });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(["bash"]);
  });

  it("clicking the × on a chip removes that tool (emits undefined when list empties)", () => {
    const onChange = vi.fn();
    render(
      <ToolsAllowlist agentId={undefined} value={["bash"]} onChange={onChange} />,
    );

    // Chip is rendered.
    expect(screen.getByText("bash")).toBeInTheDocument();

    const removeBtn = screen.getByRole("button", { name: /remove tool bash/i });
    fireEvent.click(removeBtn);

    // Empty list -> undefined so spread-if-defined omits the field.
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it("shows 'Empty = all tools allowed' help when selection is empty and hides it when non-empty", () => {
    const { rerender } = render(
      <ToolsAllowlist agentId={undefined} value={undefined} onChange={vi.fn()} />,
    );
    expect(screen.getByText(/empty = all tools allowed/i)).toBeInTheDocument();

    rerender(
      <ToolsAllowlist agentId={undefined} value={["bash"]} onChange={vi.fn()} />,
    );
    expect(screen.queryByText(/empty = all tools allowed/i)).toBeNull();
  });
});
