import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { FallbackModelList } from "@/components/control/panels/cron/FallbackModelList";

describe("FallbackModelList", () => {
  it("renders one row per value", () => {
    const onChange = vi.fn();
    render(
      <FallbackModelList
        value={["model-a", "model-b", "model-c"]}
        onChange={onChange}
      />,
    );

    expect(screen.getByDisplayValue("model-a")).toBeInTheDocument();
    expect(screen.getByDisplayValue("model-b")).toBeInTheDocument();
    expect(screen.getByDisplayValue("model-c")).toBeInTheDocument();
  });

  it("renders an empty placeholder when value is undefined", () => {
    const onChange = vi.fn();
    render(<FallbackModelList value={undefined} onChange={onChange} />);

    // No inputs, but the "Add fallback" button is present.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /add fallback/i }),
    ).toBeInTheDocument();
  });

  it("'Add fallback' appends an empty row via onChange", () => {
    const onChange = vi.fn();
    render(<FallbackModelList value={["model-a"]} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /add fallback/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(["model-a", ""]);
  });

  it("'Add fallback' from empty state calls onChange with [\"\"]", () => {
    const onChange = vi.fn();
    render(<FallbackModelList value={undefined} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /add fallback/i }));

    expect(onChange).toHaveBeenCalledWith([""]);
  });

  it("clicking up on row 2 swaps rows 1 and 2", () => {
    const onChange = vi.fn();
    render(
      <FallbackModelList value={["first", "second", "third"]} onChange={onChange} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /move fallback 2 up/i }));

    expect(onChange).toHaveBeenCalledWith(["second", "first", "third"]);
  });

  it("clicking down on row 1 swaps rows 1 and 2", () => {
    const onChange = vi.fn();
    render(
      <FallbackModelList value={["first", "second"]} onChange={onChange} />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /move fallback 1 down/i }),
    );

    expect(onChange).toHaveBeenCalledWith(["second", "first"]);
  });

  it("first row's up button and last row's down button are disabled", () => {
    const onChange = vi.fn();
    render(
      <FallbackModelList value={["first", "second"]} onChange={onChange} />,
    );

    const upFirst = screen.getByRole("button", {
      name: /move fallback 1 up/i,
    });
    const downLast = screen.getByRole("button", {
      name: /move fallback 2 down/i,
    });
    expect(upFirst).toBeDisabled();
    expect(downLast).toBeDisabled();
  });

  it("removing a middle row emits the rest", () => {
    const onChange = vi.fn();
    render(
      <FallbackModelList value={["a", "b", "c"]} onChange={onChange} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /remove fallback 2/i }));

    expect(onChange).toHaveBeenCalledWith(["a", "c"]);
  });

  it("removing the final row emits undefined (so form omits the field)", () => {
    const onChange = vi.fn();
    render(<FallbackModelList value={["only"]} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /remove fallback 1/i }));

    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it("typing in a row calls onChange with the updated list", () => {
    const onChange = vi.fn();
    render(<FallbackModelList value={["old"]} onChange={onChange} />);

    const input = screen.getByDisplayValue("old");
    fireEvent.change(input, { target: { value: "new" } });

    expect(onChange).toHaveBeenCalledWith(["new"]);
  });
});
