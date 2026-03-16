import { defineConfig, devices } from '@playwright/test';
import dotenv from 'dotenv';
import path from 'path';

// Load .env.local for E2E tests (Playwright doesn't auto-load like Next.js)
dotenv.config({ path: path.resolve(__dirname, '.env.local') });

/**
 * Playwright E2E test configuration for Isol8.
 *
 * Uses Clerk Testing Tokens for authentication bypass.
 * See: https://clerk.com/docs/testing/playwright/overview
 *
 * Run tests:
 *   npm run test:e2e           # Run all E2E tests
 *   npm run test:e2e:ui        # Run with interactive UI
 *   npx playwright test --project=chromium  # Single browser
 *
 * Required environment variables:
 *   CLERK_PUBLISHABLE_KEY      # From Clerk Dashboard
 *   CLERK_SECRET_KEY           # From Clerk Dashboard
 *   E2E_CLERK_USER_USERNAME    # Test user username
 *   E2E_CLERK_USER_PASSWORD    # Test user password
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Run tests serially to avoid race conditions with shared test user
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    // Global setup - obtains Clerk Testing Token before other tests
    {
      name: 'setup',
      testMatch: /global\.setup\.ts/,
    },
    // Browser tests - each test signs in using clerk.signIn()
    // Note: Clerk Testing Tokens work most reliably with Chromium.
    // Firefox and WebKit may have intermittent auth issues.
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      dependencies: ['setup'],
    },
    // Uncomment below to enable cross-browser testing (may have Clerk auth issues)
    // {
    //   name: 'firefox',
    //   use: { ...devices['Desktop Firefox'] },
    //   dependencies: ['setup'],
    // },
    // {
    //   name: 'webkit',
    //   use: { ...devices['Desktop Safari'] },
    //   dependencies: ['setup'],
    // },
  ],
  // For local development: start servers manually before running tests
  // For CI: set CI=true to have Playwright start servers automatically
  webServer: process.env.CI
    ? [
        {
          command: 'npm run dev',
          url: 'http://localhost:3000',
          reuseExistingServer: false,
          timeout: 120000,
        },
        {
          command: '../backend/env/bin/uvicorn main:app --port 8000',
          cwd: '../backend',
          url: 'http://localhost:8000/health',
          reuseExistingServer: false,
          timeout: 120000,
        },
      ]
    : undefined,
});
