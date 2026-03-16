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
    },
  },
});
