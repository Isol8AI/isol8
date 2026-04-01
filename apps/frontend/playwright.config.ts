import { defineConfig, devices } from '@playwright/test';
import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '.env.local') });

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  globalTimeout: 15 * 60 * 1000, // 15 minutes — covers full suite including landing tests
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'setup',
      testMatch: /global\.setup\.ts/,
    },
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      dependencies: ['setup'],
    },
  ],
  // Start local dev server only when no BASE_URL is set (i.e., not running against live dev)
  // For local e2e against localhost: start backend manually with:
  //   cd apps/backend && uv run uvicorn main:app --port 8000
  webServer: !process.env.BASE_URL
    ? [{
        command: 'pnpm run dev',
        // cwd defaults to apps/frontend/ (directory of this config file)
        url: 'http://localhost:3000',
        reuseExistingServer: !process.env.CI,
        timeout: 120000,
      }]
    : undefined,
});
