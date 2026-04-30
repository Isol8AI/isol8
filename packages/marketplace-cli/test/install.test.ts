import { describe, expect, it, mock } from "bun:test";
import { install } from "../src/install";

describe("install", () => {
  it("returns non-zero on missing license for paid listing", async () => {
    // Without license key, install should redirect to storefront and exit non-zero.
    global.fetch = mock(async () => new Response("", { status: 401 })) as any;
    const code = await install({
      slug: "x",
      backendBaseUrl: "https://api.example",
      // no licenseKey provided
      ci: true,
    });
    expect(code).not.toBe(0);
  });

  it("returns non-zero on backend 401", async () => {
    global.fetch = mock(async () => new Response(
      JSON.stringify({ detail: "license revoked" }),
      { status: 401 }
    )) as any;
    const code = await install({
      slug: "x",
      licenseKey: "iml_revoked",
      backendBaseUrl: "https://api.example",
      ci: true,
    });
    expect(code).toBe(3);
  });

  it("returns non-zero on backend 429", async () => {
    global.fetch = mock(async () => new Response("", { status: 429 })) as any;
    const code = await install({
      slug: "x",
      licenseKey: "iml_xxx",
      backendBaseUrl: "https://api.example",
      ci: true,
    });
    expect(code).toBe(4);
  });
});
