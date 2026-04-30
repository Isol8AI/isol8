import { describe, expect, it } from "bun:test";
import { createMcpHandlers } from "../src/mcp-handler";
import { writeFileSync, mkdtempSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

describe("createMcpHandlers", () => {
  it("returns the SKILL.md as a resource and exposes companion scripts as tools", async () => {
    const dir = mkdtempSync(join(tmpdir(), "mcp-"));
    writeFileSync(join(dir, "SKILL.md"), "---\nname: x\ndescription: y\n---\nbody");
    mkdirSync(join(dir, "scripts"), { recursive: true });
    writeFileSync(join(dir, "scripts", "do.sh"), "#!/bin/sh\necho ok", { mode: 0o755 });

    const handlers = createMcpHandlers({
      sessionId: "s1",
      unpackedDir: dir,
      manifest: { name: "x", description: "y" },
    });

    const resources = await handlers.listResources();
    expect(resources.resources.length).toBeGreaterThan(0);
    expect(resources.resources[0].uri).toContain("SKILL.md");

    const tools = await handlers.listTools();
    expect(tools.tools.some((t: { name: string }) => t.name.includes("do"))).toBe(true);
  });

  it("rejects path-traversal in readResource", async () => {
    const dir = mkdtempSync(join(tmpdir(), "mcp-"));
    writeFileSync(join(dir, "SKILL.md"), "ok");
    const handlers = createMcpHandlers({
      sessionId: "s1",
      unpackedDir: dir,
      manifest: {},
    });
    let threw = false;
    try {
      await handlers.readResource("file:///etc/passwd");
    } catch {
      threw = true;
    }
    expect(threw).toBe(true);
  });
});
