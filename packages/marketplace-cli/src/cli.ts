#!/usr/bin/env node
import { Command } from "commander";
import { install } from "./install.js";

const program = new Command();
program
  .name("isol8-marketplace")
  .description("Install AI agents and skills from marketplace.isol8.co")
  .version("0.1.0");

program
  .command("install <slug>")
  .description("Install a skill or agent by slug")
  .option("--license-key <key>", "Use a specific license key (paid listings)")
  .option("--client <name>", "Override client detection: claude-code|cursor|openclaw|copilot")
  .option("--ci", "CI mode — install to ./.isol8/skills/ instead of ~/")
  .action(async (slug, opts) => {
    const code = await install({ slug, ...opts });
    process.exit(code);
  });

program.parseAsync(process.argv);
