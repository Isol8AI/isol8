#!/usr/bin/env node
import { Command } from "commander";

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
    // Real implementation lands in T4. For now, stub-print so the bin entry
    // does something verifiable.
    console.log(JSON.stringify({ msg: "install stub", slug, opts }));
    process.exit(0);
  });

program.parseAsync(process.argv);
