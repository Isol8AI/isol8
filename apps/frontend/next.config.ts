import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,

  turbopack: {
    root: path.resolve(__dirname, '../../'),
  },

  // Reverse-proxy PostHog through our own domain so ad-blockers /
  // privacy extensions (uBlock, Brave shields, NextDNS, etc.) don't
  // block telemetry. Requests go to isol8.co/ingest/* which Vercel
  // rewrites to the PostHog ingestion + asset origins. Per PostHog's
  // documented pattern: https://posthog.com/docs/advanced/proxy/nextjs
  // Order matters: /ingest/static/* must come before the catch-all.
  // skipTrailingSlashRedirect is required so PostHog's `decide`
  // endpoint is reached without a 307.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    // beforeFiles runs ahead of Next.js routing — required for the
    // company.* host rewrites because otherwise dev.company.isol8.co/foo
    // would match Next's `/foo` route (or fall through Clerk middleware
    // which redirects unsigned users away). Vercel-only rewrites in
    // vercel.json fire AFTER Next routing for the same reason. Putting
    // them in beforeFiles routes the request to the backend proxy
    // before Next sees it.
    return {
      beforeFiles: [
        {
          source: "/:path*",
          has: [{ type: "host", value: "dev.company.isol8.co" }],
          destination: "https://api-dev.isol8.co/__paperclip_proxy__/:path*",
        },
        {
          source: "/:path*",
          has: [{ type: "host", value: "company.isol8.co" }],
          destination: "https://api.isol8.co/__paperclip_proxy__/:path*",
        },
      ],
      afterFiles: [
        {
          source: "/ingest/static/:path*",
          destination: "https://us-assets.i.posthog.com/static/:path*",
        },
        {
          source: "/ingest/:path*",
          destination: "https://us.i.posthog.com/:path*",
        },
        {
          source: "/ingest/decide",
          destination: "https://us.i.posthog.com/decide",
        },
      ],
    };
  },
};

export default nextConfig;
