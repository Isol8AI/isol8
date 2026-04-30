import { describe, expect, it } from "bun:test";
import { runSandboxed } from "../src/sandbox";
import { writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

describe("runSandboxed", () => {
  it("executes a script and returns stdout", async () => {
    const dir = mkdtempSync(join(tmpdir(), "sandbox-"));
    writeFileSync(join(dir, "hi.sh"), "#!/bin/sh\necho hello\n", { mode: 0o755 });
    const result = await runSandboxed({
      cwd: dir,
      command: ["sh", "hi.sh"],
      input: "",
      timeoutMs: 5000,
      memoryMb: 64,
    });
    expect(result.exitCode).toBe(0);
    expect(result.stdout.trim()).toBe("hello");
  });

  it("times out long-running scripts", async () => {
    const dir = mkdtempSync(join(tmpdir(), "sandbox-"));
    writeFileSync(join(dir, "loop.sh"), "#!/bin/sh\nsleep 30\n", { mode: 0o755 });
    const result = await runSandboxed({
      cwd: dir,
      command: ["sh", "loop.sh"],
      input: "",
      timeoutMs: 500,
      memoryMb: 64,
    });
    expect(result.timedOut).toBe(true);
  });

  it("captures stderr separately from stdout", async () => {
    const dir = mkdtempSync(join(tmpdir(), "sandbox-"));
    writeFileSync(join(dir, "err.sh"), "#!/bin/sh\necho out\necho err 1>&2\n", { mode: 0o755 });
    const result = await runSandboxed({
      cwd: dir,
      command: ["sh", "err.sh"],
      input: "",
      timeoutMs: 5000,
      memoryMb: 64,
    });
    expect(result.stdout.trim()).toBe("out");
    expect(result.stderr.trim()).toBe("err");
  });
});
