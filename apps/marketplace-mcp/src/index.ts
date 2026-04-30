import { serve } from "bun";
import { validateLicense } from "./auth";
import { fetchArtifact } from "./artifact";
import { createMcpHandlers } from "./mcp-handler";
import { createSession } from "./session";

const PORT = Number(process.env.PORT ?? 3000);
const BACKEND = process.env.BACKEND_BASE_URL ?? "https://api.isol8.co";
const SESSIONS_TABLE = process.env.MARKETPLACE_MCP_SESSIONS_TABLE ?? "";
const ARTIFACTS_BUCKET = process.env.MARKETPLACE_ARTIFACTS_BUCKET ?? "";

const server = serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);

    if (url.pathname === "/health") {
      return new Response("ok");
    }

    const sse = url.pathname.match(/^\/mcp\/([^\/]+)\/sse$/);
    if (sse) {
      const auth = req.headers.get("authorization") ?? "";
      const licenseKey = auth.startsWith("Bearer ") ? auth.slice(7) : "";
      const sourceIp = req.headers.get("x-forwarded-for") ?? "unknown";

      const validation = await validateLicense({
        licenseKey, sourceIp, backendBaseUrl: BACKEND,
      });
      if (validation.status !== "valid") {
        return new Response(
          JSON.stringify({ error: validation.status, reason: validation.reason }),
          {
            status:
              validation.status === "revoked" || validation.status === "missing"
                ? 401
                : validation.status === "rate_limited"
                ? 429
                : 502,
            headers: { "content-type": "application/json" },
          }
        );
      }

      const artifact = await fetchArtifact({
        bucket: ARTIFACTS_BUCKET,
        listingId: validation.listingId!,
        version: validation.version!,
      });
      const sessionId = await createSession({
        table: SESSIONS_TABLE,
        licenseKey,
        listingId: validation.listingId!,
        version: validation.version!,
      });
      const handlers = createMcpHandlers({
        sessionId,
        unpackedDir: artifact.unpackedDir,
        manifest: artifact.manifest,
      });

      // SSE response: emit ready event then list tools.
      // Real implementation streams MCP protocol frames; this v1 emits the
      // session metadata + the tool list, then keeps the connection open
      // for tool invocations via a separate POST channel (Plan 3.5+).
      const stream = new ReadableStream({
        async start(controller) {
          const enc = new TextEncoder();
          controller.enqueue(enc.encode(
            `event: ready\ndata: ${JSON.stringify({ session_id: sessionId, manifest: artifact.manifest })}\n\n`
          ));
          const tools = await handlers.listTools();
          controller.enqueue(enc.encode(
            `event: tools\ndata: ${JSON.stringify(tools)}\n\n`
          ));
        },
      });
      return new Response(stream, {
        headers: {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          "x-isol8-session-id": sessionId,
        },
      });
    }

    return new Response("not found", { status: 404 });
  },
});

console.log(JSON.stringify({ msg: "marketplace-mcp listening", port: server.port }));
