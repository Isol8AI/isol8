import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}', 'src/**/__tests__/**/*.test.{ts,tsx}'],
    exclude: [
      'tests/e2e/**/*',
      'node_modules/**/*',
    ],
    // Use threads pool with limited workers
    pool: 'threads',
    poolOptions: {
      threads: {
        maxThreads: 2,
        minThreads: 1,
      },
    },
    // Handle heavy dependencies that cause issues with vitest
    server: {
      deps: {
        // Externalize heavy ML packages to prevent bundling hangs
        external: ['@huggingface/transformers', 'onnxruntime-web', 'onnxruntime-node'],
      },
    },
    // Increase test timeout for slow module initialization
    testTimeout: 30000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      exclude: [
        'node_modules/',
        'tests/',
        '.next/',
        '*.config.*',
      ],
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // `server-only` is a Next.js runtime guard that errors on client import.
      // In vitest (node), it's a no-op — alias to an empty stub so server-side
      // modules (e.g. src/app/admin/_lib/url.ts) can be imported for unit tests.
      'server-only': path.resolve(__dirname, './tests/stubs/server-only.ts'),
    },
  },
});
