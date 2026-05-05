import { test, expect, vi } from "vitest";
// Smoke tests for SwipeToArchive — confirms children render and that the
// archive callback is not fired without a swipe gesture. Touch-event behavior
// is intentionally not exercised in JSDOM.

import { render } from "@testing-library/react";
import { SwipeToArchive } from "@/components/teams/inbox/SwipeToArchive";

test("renders children", () => {
  const { getByText } = render(
    <SwipeToArchive onArchive={() => {}}>
      <div>row</div>
    </SwipeToArchive>,
  );
  expect(getByText("row")).toBeInTheDocument();
});

test("does not fire onArchive without a swipe gesture", () => {
  const onArchive = vi.fn();
  render(
    <SwipeToArchive onArchive={onArchive}>
      <div>row</div>
    </SwipeToArchive>,
  );
  expect(onArchive).not.toHaveBeenCalled();
});
