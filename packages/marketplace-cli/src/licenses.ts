import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

interface LicenseStore {
  [slug: string]: { license_key: string; installed_version?: number };
}

function storePath(): string {
  return join(homedir(), ".isol8", "marketplace", "licenses.json");
}

function ensureDir() {
  const dir = join(homedir(), ".isol8", "marketplace");
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
  }
}

export function loadLicenses(): LicenseStore {
  if (!existsSync(storePath())) return {};
  return JSON.parse(readFileSync(storePath(), "utf8"));
}

export function saveLicense(slug: string, license_key: string, installed_version?: number) {
  ensureDir();
  const store = loadLicenses();
  store[slug] = { license_key, installed_version };
  writeFileSync(storePath(), JSON.stringify(store, null, 2));
  chmodSync(storePath(), 0o600);
}

export function getLicense(slug: string): string | undefined {
  return loadLicenses()[slug]?.license_key;
}
