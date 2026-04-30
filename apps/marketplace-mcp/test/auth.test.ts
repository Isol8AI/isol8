import { describe, expect, it, mock } from "bun:test";
import { validateLicense } from "../src/auth";

describe("validateLicense", () => {
  it("returns valid + listing data when backend says valid", async () => {
    global.fetch = mock(async () => new Response(JSON.stringify({
      listing_id: "l1", listing_slug: "x", version: 1,
      download_url: "https://signed", manifest_sha256: "sha",
      expires_at: "2026-04-30T01:00:00Z",
    }), { status: 200 })) as any;
    const result = await validateLicense({
      licenseKey: "iml_xxx", sourceIp: "1.2.3.4", backendBaseUrl: "https://api"
    });
    expect(result.status).toBe("valid");
    expect(result.listingId).toBe("l1");
  });

  it("rejects empty key as missing", async () => {
    const result = await validateLicense({
      licenseKey: "", sourceIp: "1.2.3.4", backendBaseUrl: "https://api"
    });
    expect(result.status).toBe("missing");
  });

  it("rejects key without iml_ prefix", async () => {
    const result = await validateLicense({
      licenseKey: "Bearer xxx", sourceIp: "1.2.3.4", backendBaseUrl: "https://api"
    });
    expect(result.status).toBe("missing");
  });

  it("propagates 401 from backend as 'revoked'", async () => {
    global.fetch = mock(async () => new Response(
      JSON.stringify({ detail: "license revoked: refunded" }),
      { status: 401 }
    )) as any;
    const result = await validateLicense({
      licenseKey: "iml_revoked", sourceIp: "1.2.3.4", backendBaseUrl: "https://api"
    });
    expect(result.status).toBe("revoked");
  });

  it("propagates 429 as 'rate_limited'", async () => {
    global.fetch = mock(async () => new Response("", { status: 429 })) as any;
    const result = await validateLicense({
      licenseKey: "iml_xxx", sourceIp: "1.2.3.4", backendBaseUrl: "https://api"
    });
    expect(result.status).toBe("rate_limited");
  });
});
