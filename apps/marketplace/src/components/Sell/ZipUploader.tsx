"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";

interface UploadResponse {
  listing_id: string;
  version: number;
  manifest_sha256: string;
  file_count: number;
  bytes: number;
}

interface Props {
  listingId: string;
  onUploaded?: (resp: UploadResponse) => void;
}

/**
 * File picker + uploader for the SKILL.md zip path. Validates client-side
 * that the file is a .zip MIME / extension, then POSTs multipart/form-data
 * to /api/v1/marketplace/listings/{id}/artifact.
 *
 * The backend handles the heavy lifting: unzip, normalize wrapper-strip,
 * pack_skillmd, replace_artifact in S3 + DDB.
 */
export function ZipUploader({ listingId, onUploaded }: Props) {
  const { getToken } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function pick(picked: File | null) {
    setStatus(null);
    if (!picked) {
      setFile(null);
      return;
    }
    const isZip =
      picked.type === "application/zip" ||
      picked.type === "application/x-zip-compressed" ||
      picked.name.toLowerCase().endsWith(".zip");
    if (!isZip) {
      setFile(null);
      setStatus("Only .zip files are supported.");
      return;
    }
    setFile(picked);
  }

  async function upload() {
    if (!file) return;
    setBusy(true);
    setStatus("Uploading…");
    try {
      const jwt = await getToken();
      const fd = new FormData();
      fd.append("file", file);
      const resp = await fetch(
        `${API}/api/v1/marketplace/listings/${encodeURIComponent(listingId)}/artifact`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${jwt}` },
          body: fd,
        },
      );
      if (resp.ok) {
        const body = (await resp.json()) as UploadResponse;
        setStatus(
          `Uploaded ${body.file_count} files (${body.bytes.toLocaleString()} bytes).`,
        );
        onUploaded?.(body);
      } else {
        const txt = await resp.text();
        setStatus(`Upload failed (${resp.status}): ${txt.slice(0, 200)}`);
      }
    } catch (e) {
      setStatus(`Upload failed: ${e instanceof Error ? e.message : "unknown"}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-zinc-800 p-4 space-y-3">
      <p className="text-sm text-zinc-400">
        Drop or pick a <code>.zip</code> with your <code>SKILL.md</code> + helper files.
        Up to 10 MB unpacked, 256 files max. Wrapper folder (if any) is auto-stripped.
      </p>
      <input
        type="file"
        accept=".zip,application/zip,application/x-zip-compressed"
        onChange={(e) => pick(e.target.files?.[0] ?? null)}
        className="block text-sm text-zinc-300 file:mr-3 file:px-3 file:py-1 file:rounded file:bg-zinc-100 file:text-zinc-950 file:border-0 file:font-medium"
      />
      <button
        type="button"
        onClick={upload}
        disabled={!file || busy}
        className="px-4 py-2 bg-zinc-100 text-zinc-950 rounded font-semibold disabled:opacity-50"
      >
        {busy ? "Uploading…" : "Upload zip"}
      </button>
      {status && <p className="text-sm text-zinc-300">{status}</p>}
    </div>
  );
}
