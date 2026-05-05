// Smoke tests for filterNavActions — empty query, label substring matching,
// keyword alias matching, and no-match returns empty.

import { describe, test, expect } from "vitest";
import { NAV_ACTIONS, filterNavActions } from "@/components/teams/command-palette/commandPaletteActions";

describe("filterNavActions", () => {
  test("empty query returns all 14 actions", () => {
    expect(filterNavActions("")).toHaveLength(14);
    expect(filterNavActions("   ")).toHaveLength(14);
  });

  test("substring matches label (case-insensitive)", () => {
    const result = filterNavActions("INBO");
    expect(result.map((a) => a.id)).toEqual(["go-inbox"]);
  });

  test("matches by keyword alias", () => {
    const result = filterNavActions("people");
    expect(result.map((a) => a.id)).toContain("go-members");
    expect(filterNavActions("hierarchy").map((a) => a.id)).toEqual(["go-org-chart"]);
  });

  test("returns empty when no match", () => {
    expect(filterNavActions("xyzzy")).toHaveLength(0);
  });

  test("NAV_ACTIONS is exported with 14 entries", () => {
    expect(NAV_ACTIONS).toHaveLength(14);
  });
});
