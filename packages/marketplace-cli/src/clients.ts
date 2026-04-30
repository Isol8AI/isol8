import { existsSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

export type Client = "claude-code" | "cursor" | "openclaw" | "copilot" | "generic";

export function detectClient(opts: { home?: string; override?: string } = {}): Client {
  if (opts.override) {
    if (["claude-code", "cursor", "openclaw", "copilot", "generic"].includes(opts.override)) {
      return opts.override as Client;
    }
  }
  if (process.env.ISOL8_CONTAINER === "true") return "openclaw";
  const h = opts.home ?? homedir();
  if (existsSync(join(h, ".claude", "skills"))) return "claude-code";
  if (existsSync(join(h, ".cursor", "skills"))) return "cursor";
  if (existsSync(".cursor/skills")) return "cursor"; // project-local
  if (existsSync(join(h, ".openclaw", "skills"))) return "openclaw";
  if (existsSync(join(h, ".copilot", "skills"))) return "copilot";
  return "generic";
}

export function resolveSkillsDir(opts: { home: string; client: Client; ci: boolean }): string {
  if (opts.ci) return "./.isol8/skills";
  switch (opts.client) {
    case "claude-code":
      return join(opts.home, ".claude", "skills");
    case "cursor":
      return join(opts.home, ".cursor", "skills");
    case "openclaw":
      return join(opts.home, ".openclaw", "skills");
    case "copilot":
      return join(opts.home, ".copilot", "skills");
    case "generic":
      return join(opts.home, ".isol8", "skills");
  }
}
