import { mkdirSync, existsSync, chmodSync } from "node:fs";
import { join } from "node:path";
import { homedir, platform } from "node:os";
import { createHash } from "node:crypto";
import { extract } from "tar";
import { detectClient, resolveSkillsDir, type Client } from "./clients.js";
import { getLicense, saveLicense } from "./licenses.js";

interface InstallOpts {
  slug: string;
  licenseKey?: string;
  client?: string;
  ci?: boolean;
  backendBaseUrl?: string;
}

const DEFAULT_BACKEND = process.env.ISOL8_BACKEND_URL || "https://api.isol8.co";

export async function install(opts: InstallOpts): Promise<number> {
  const backend = opts.backendBaseUrl || DEFAULT_BACKEND;
  const home = homedir();
  const client = detectClient({ home, override: opts.client }) as Client;
  if (client === "generic" && !opts.ci) {
    console.error("Could not detect a known AI client. Install paths to try:");
    console.error("  ~/.claude/skills/<slug>/        (Claude Code)");
    console.error("  ~/.cursor/skills/<slug>/        (Cursor)");
    console.error("  ~/.openclaw/skills/<slug>/      (OpenClaw)");
    console.error("Re-run with --client <name> or unpack the tarball manually.");
    return 1;
  }
  const dir = resolveSkillsDir({ home, client, ci: !!opts.ci });

  const licenseKey = opts.licenseKey || getLicense(opts.slug);
  if (!licenseKey) {
    console.error("This appears to be a paid listing. Open the storefront to purchase:");
    console.error(`  https://marketplace.isol8.co/listing/${opts.slug}`);
    return 2;
  }

  const validateUrl = `${backend}/api/v1/marketplace/install/validate`;
  const resp = await fetch(validateUrl, {
    headers: { Authorization: `Bearer ${licenseKey}` },
  });
  if (resp.status === 401) {
    console.error("License invalid or revoked.");
    return 3;
  }
  if (resp.status === 429) {
    console.error("Install rate limit exceeded (10 unique IPs / 24h). Try again later.");
    return 4;
  }
  if (!resp.ok) {
    console.error(`Backend error: ${resp.status}`);
    return 5;
  }
  const meta = (await resp.json()) as {
    listing_id: string;
    listing_slug: string;
    version: number;
    download_url: string;
    manifest_sha256: string;
  };

  // Download tarball.
  const dl = await fetch(meta.download_url);
  if (!dl.ok || !dl.body) {
    console.error("Download failed.");
    return 6;
  }

  const targetDir = join(dir, meta.listing_slug);
  if (!existsSync(targetDir)) {
    mkdirSync(targetDir, { recursive: true, mode: 0o700 });
  }
  if (platform() !== "win32") {
    try {
      chmodSync(targetDir, 0o700);
    } catch {
      // Best-effort — some filesystems (CI) don't support chmod.
    }
  }

  // Buffer tarball, write to disk, extract.
  const buf = Buffer.from(await dl.arrayBuffer());
  const tarPath = join(targetDir, ".__incoming.tar.gz");
  await Bun.write(tarPath, buf);
  await extract({ file: tarPath, cwd: targetDir });
  // Best-effort cleanup of tarball.
  try {
    await Bun.write(tarPath, "");
  } catch {
    // ignore
  }

  // Verify manifest SHA — fail-loud if download was corrupted/tampered.
  const manifestPath = join(targetDir, "manifest.json");
  if (!existsSync(manifestPath)) {
    console.error("manifest.json missing from artifact");
    return 7;
  }
  const manifestBytes = await Bun.file(manifestPath).bytes();
  const manifestSha = createHash("sha256").update(manifestBytes).digest("hex");
  if (manifestSha !== meta.manifest_sha256) {
    console.error(`SHA mismatch: expected ${meta.manifest_sha256}, got ${manifestSha}`);
    console.error("Aborting install. The artifact may be corrupted or tampered.");
    return 8;
  }

  saveLicense(opts.slug, licenseKey, meta.version);
  console.log(`Installed ${opts.slug} (v${meta.version}) into ${targetDir}`);
  return 0;
}
