import { describe, it, expect, vi, beforeEach } from "vitest";

const { authMock, getTokenMock, fetchMock } = vi.hoisted(() => {
  const getTokenMock = vi.fn();
  return {
    getTokenMock,
    authMock: vi.fn(async () => ({ getToken: getTokenMock })),
    fetchMock: vi.fn(),
  };
});

vi.mock("@clerk/nextjs/server", () => ({ auth: authMock }));
vi.stubGlobal("fetch", fetchMock);

import { publishAgent, unpublishSlug } from "@/app/admin/_actions/catalog";

describe("catalog server actions", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    getTokenMock.mockReset();
    getTokenMock.mockResolvedValue("test-token");
  });

  it("publishAgent posts to /admin/catalog/publish", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ slug: "pitch", version: 1, s3_prefix: "pitch/v1" }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await publishAgent("agent_abc");

    expect(result.ok).toBe(true);
    expect(result.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/admin\/catalog\/publish$/);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      agent_id: "agent_abc",
    });
  });

  it("unpublishSlug posts to /admin/catalog/{slug}/unpublish", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ slug: "pitch", last_version: 3 }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await unpublishSlug("pitch");

    expect(result.ok).toBe(true);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/admin\/catalog\/pitch\/unpublish$/);
  });

  it("returns ok=false when token is missing", async () => {
    getTokenMock.mockResolvedValueOnce(null);
    const result = await publishAgent("agent_abc");
    expect(result.ok).toBe(false);
    expect(result.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("propagates backend error status", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("{}", { status: 404 }),
    );
    const result = await unpublishSlug("ghost");
    expect(result.ok).toBe(false);
    expect(result.status).toBe(404);
  });
});
