import { GetObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";

interface CachedArtifact {
  unpackedDir: string;
  manifest: Record<string, unknown>;
  fetchedAt: number;
}

const CACHE = new Map<string, CachedArtifact>();
const TTL_MS = 60_000;

const s3 = new S3Client({});

async function fetchTarball(bucket: string, key: string): Promise<Buffer> {
  const out = await s3.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
  const chunks: Buffer[] = [];
  for await (const chunk of out.Body as AsyncIterable<Uint8Array>) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

export async function fetchArtifact(opts: {
  bucket: string;
  listingId: string;
  version: number;
}): Promise<CachedArtifact> {
  const cacheKey = `${opts.listingId}:${opts.version}`;
  const cached = CACHE.get(cacheKey);
  if (cached && Date.now() - cached.fetchedAt < TTL_MS) {
    return cached;
  }
  const tarPath = `listings/${opts.listingId}/v${opts.version}/workspace.tar.gz`;
  const tarBuf = await fetchTarball(opts.bucket, tarPath);
  const dir = mkdtempSync(join(tmpdir(), `artifact-${opts.listingId}-`));
  const tarFile = join(dir, "skill.tar.gz");
  writeFileSync(tarFile, tarBuf);
  spawnSync("tar", ["-xzf", tarFile, "-C", dir]);

  const manifestPath = join(dir, "manifest.json");
  const manifest = JSON.parse(await Bun.file(manifestPath).text());

  const entry: CachedArtifact = {
    unpackedDir: dir,
    manifest,
    fetchedAt: Date.now(),
  };
  CACHE.set(cacheKey, entry);
  return entry;
}
