export type LicenseStatus = "valid" | "revoked" | "rate_limited" | "missing" | "error";

export interface LicenseResult {
  status: LicenseStatus;
  listingId?: string;
  listingSlug?: string;
  version?: number;
  downloadUrl?: string;
  manifestSha256?: string;
  reason?: string;
}

export async function validateLicense(opts: {
  licenseKey: string;
  sourceIp: string;
  backendBaseUrl: string;
}): Promise<LicenseResult> {
  if (!opts.licenseKey || !opts.licenseKey.startsWith("iml_")) {
    return { status: "missing" };
  }
  const url = `${opts.backendBaseUrl}/api/v1/marketplace/install/validate`;
  const resp = await fetch(url, {
    headers: {
      Authorization: `Bearer ${opts.licenseKey}`,
      "X-Forwarded-For": opts.sourceIp,
    },
  });
  if (resp.status === 401) {
    const body = await resp.json().catch(() => ({})) as { detail?: string };
    return { status: "revoked", reason: body.detail };
  }
  if (resp.status === 429) {
    return { status: "rate_limited" };
  }
  if (!resp.ok) {
    return { status: "error", reason: `backend ${resp.status}` };
  }
  const body = await resp.json() as {
    listing_id: string;
    listing_slug: string;
    version: number;
    download_url: string;
    manifest_sha256: string;
  };
  return {
    status: "valid",
    listingId: body.listing_id,
    listingSlug: body.listing_slug,
    version: body.version,
    downloadUrl: body.download_url,
    manifestSha256: body.manifest_sha256,
  };
}
