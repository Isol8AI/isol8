import { readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { runSandboxed } from "./sandbox";

interface SessionContext {
  sessionId: string;
  unpackedDir: string;
  manifest: Record<string, unknown>;
}

function discoverScripts(dir: string): string[] {
  const out: string[] = [];
  const walk = (current: string) => {
    for (const entry of readdirSync(current)) {
      const full = join(current, entry);
      const st = statSync(full);
      if (st.isDirectory()) walk(full);
      else if (
        st.isFile() &&
        (entry.endsWith(".sh") || entry.endsWith(".js") || entry.endsWith(".ts"))
      ) {
        out.push(full);
      }
    }
  };
  walk(dir);
  return out;
}

export function createMcpHandlers(ctx: SessionContext) {
  return {
    async listResources() {
      return {
        resources: [
          {
            uri: `file://${ctx.unpackedDir}/SKILL.md`,
            name: "SKILL.md",
            mimeType: "text/markdown",
          },
        ],
      };
    },
    async readResource(uri: string) {
      // Path-scope check: must resolve under unpackedDir.
      const path = uri.replace(/^file:\/\//, "");
      const resolved = resolve(path);
      if (!resolved.startsWith(ctx.unpackedDir)) {
        throw new Error("path outside session scope");
      }
      return {
        contents: [
          {
            uri,
            mimeType: "text/markdown",
            text: await Bun.file(resolved).text(),
          },
        ],
      };
    },
    async listTools() {
      const scripts = discoverScripts(ctx.unpackedDir);
      return {
        tools: scripts.map(s => ({
          name: relative(ctx.unpackedDir, s).replace(/[\/\\.]/g, "_"),
          description: `Run ${relative(ctx.unpackedDir, s)}`,
          inputSchema: {
            type: "object" as const,
            properties: { input: { type: "string" } },
          },
        })),
      };
    },
    async callTool(name: string, args: { input?: string }) {
      const scripts = discoverScripts(ctx.unpackedDir);
      const target = scripts.find(
        s => relative(ctx.unpackedDir, s).replace(/[\/\\.]/g, "_") === name
      );
      if (!target) throw new Error(`tool not found: ${name}`);
      const interp = target.endsWith(".sh") ? "sh" : "bun";
      const result = await runSandboxed({
        cwd: ctx.unpackedDir,
        command: [interp, target],
        input: args.input ?? "",
        timeoutMs: 30_000,
        memoryMb: 256,
      });
      return {
        content: [
          {
            type: "text" as const,
            text: result.timedOut
              ? `Tool timed out after 30s.`
              : `[exit ${result.exitCode}]\n${result.stdout}\n${result.stderr ? `[stderr]\n${result.stderr}` : ""}`,
          },
        ],
      };
    },
  };
}
