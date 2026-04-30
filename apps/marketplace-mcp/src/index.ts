import { serve } from "bun";

const PORT = Number(process.env.PORT ?? 3000);

const server = serve({
  port: PORT,
  fetch(req) {
    const url = new URL(req.url);
    if (url.pathname === "/health") {
      return new Response("ok", { status: 200 });
    }
    return new Response("not found", { status: 404 });
  },
});

console.log(JSON.stringify({ msg: "marketplace-mcp listening", port: server.port }));
