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
    return [
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
    ];
  },

  // Exclude heavy ML packages from Vercel's output file tracing
  // We do CLIENT-SIDE inference only, so we don't need onnxruntime-node at all
  // See: https://github.com/huggingface/transformers.js/issues/1164
  // The problematic files are NESTED inside @huggingface/transformers
  outputFileTracingExcludes: {
    '*': [
      // Exclude all onnxruntime-node binaries (400MB+) - not needed for client-side inference
      'node_modules/@huggingface/transformers/node_modules/onnxruntime-node/**/*',
      'node_modules/onnxruntime-node/**/*',
      // Exclude sharp native binaries (32MB+) - not needed for our use case
      'node_modules/@img/sharp-libvips-linux-x64/**/*',
      'node_modules/@img/sharp-libvips-linuxmusl-x64/**/*',
    ],
  },

  // Externalize large packages from serverless functions
  // These are client-only and should not be bundled server-side
  serverExternalPackages: [
    '@huggingface/transformers',
    'onnxruntime-web',
    'onnxruntime-node',
  ],

  // Exclude heavy ML packages from webpack bundles
  webpack: (config, { isServer }) => {
    // Exclude onnxruntime-node and sharp from ALL builds
    // See: https://huggingface.co/docs/transformers.js/en/tutorials/next
    config.resolve.alias = {
      ...config.resolve.alias,
      "sharp$": false,
      "onnxruntime-node$": false,
    };

    // Enable WebAssembly support
    config.experiments = {
      ...config.experiments,
      asyncWebAssembly: true,
      layers: true,
    };

    // For browser builds, additional Node.js module handling
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        path: false,
        crypto: false,
      };
    }

    return config;
  },
};

export default nextConfig;
