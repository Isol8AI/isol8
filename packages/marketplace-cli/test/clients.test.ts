import { describe, expect, it } from "bun:test";
import { detectClient, resolveSkillsDir } from "../src/clients";
import { mkdtempSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir, homedir } from "node:os";

describe("detectClient", () => {
  it("returns 'claude-code' when ~/.claude/skills exists", () => {
    const fakeHome = mkdtempSync(join(tmpdir(), "home-"));
    mkdirSync(join(fakeHome, ".claude", "skills"), { recursive: true });
    expect(detectClient({ home: fakeHome })).toBe("claude-code");
  });

  it("returns 'cursor' when ~/.cursor/skills exists", () => {
    const fakeHome = mkdtempSync(join(tmpdir(), "home-"));
    mkdirSync(join(fakeHome, ".cursor", "skills"), { recursive: true });
    expect(detectClient({ home: fakeHome })).toBe("cursor");
  });

  it("returns 'generic' as fallback", () => {
    const fakeHome = mkdtempSync(join(tmpdir(), "home-"));
    expect(detectClient({ home: fakeHome })).toBe("generic");
  });

  it("respects --client override", () => {
    expect(detectClient({ home: homedir(), override: "openclaw" })).toBe("openclaw");
  });
});

describe("resolveSkillsDir", () => {
  it("returns ./.isol8/skills/ in CI mode", () => {
    expect(resolveSkillsDir({ home: "/h", client: "claude-code", ci: true })).toBe("./.isol8/skills");
  });

  it("returns ~/.claude/skills for claude-code", () => {
    expect(resolveSkillsDir({ home: "/h", client: "claude-code", ci: false })).toBe("/h/.claude/skills");
  });

  it("returns ~/.cursor/skills for cursor", () => {
    const result = resolveSkillsDir({ home: "/h", client: "cursor", ci: false });
    expect(result.endsWith(".cursor/skills") || result.endsWith(".cursor\\skills")).toBe(true);
  });
});
