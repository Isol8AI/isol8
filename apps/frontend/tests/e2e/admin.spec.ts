import { test, expect } from '@playwright/test';
import { clerkSetup, setupClerkTestingToken } from '@clerk/testing/playwright';

/**
 * Admin dashboard golden path (#351).
 *
 * Skipped by default. The admin host is gated by the host-based middleware in
 * `src/middleware.ts`, so this spec only makes sense when `BASE_URL` points at
 * `admin{-dev}.isol8.co`. We also need a real Clerk admin session — until the
 * admin Vercel domain alias + Cloudflare bypass are in place we cannot drive
 * this from CI.
 *
 * TODO Phase F follow-ups (tracked in docs/runbooks/admin-rollout.md):
 *   1. DNS + Vercel domain alias for `admin.dev.isol8.co` -> `isol8-frontend-dev`.
 *   2. Cloudflare bypass + `VERCEL_AUTOMATION_BYPASS_SECRET` for the admin host.
 *   3. Seed a Clerk test user in `PLATFORM_ADMIN_USER_IDS` and surface its
 *      credentials via fixtures (similar to `personal.spec.ts`).
 *   4. Drop the `test.skip(...)` guard once those land. The walk-through below
 *      should pass against a live admin dev environment.
 */

test.describe('admin dashboard golden path', () => {
  test.skip(
    ({ baseURL }) => !baseURL?.includes('admin'),
    'Only runs against the admin host (BASE_URL=https://admin.dev.isol8.co).',
  );

  test('admin can sign in, view a user, fire a read-only action', async ({
    page,
  }) => {
    await clerkSetup();
    await setupClerkTestingToken({ page });

    // 1. Sign in via Clerk admin token.
    //    The fixture for an admin Clerk user lives in apps/frontend/tests/e2e/fixtures/.
    //    For now we just navigate to /sign-in and let the Clerk testing token
    //    drive the sign-in. Once an admin fixture exists, swap to it here.
    await page.goto('/sign-in');
    // TODO: drive sign-in via Clerk admin testing token when fixture lands.

    // 2. Navigate to /admin/users.
    await page.goto('/admin/users');

    // 3. Expect the user table to render OR the empty state.
    const heading = page.getByRole('heading', { name: /users/i });
    await expect(heading).toBeVisible();

    // 4. Click the first user row (or skip if the table is empty).
    const firstRow = page.getByRole('link').filter({ hasText: /user_/ }).first();
    if ((await firstRow.count()) === 0) {
      test.skip(true, 'No users in the directory yet — nothing to drill into.');
    }
    await firstRow.click();

    // 5. Expect the Overview tab to render.
    await expect(page.getByRole('heading', { name: /overview/i })).toBeVisible();

    // 6. Click the Activity tab and assert both sections render.
    await page.getByRole('link', { name: /activity/i }).click();
    await expect(page.getByText(/recent error logs/i)).toBeVisible();
    await expect(page.getByText(/posthog timeline/i)).toBeVisible();

    // 7. Click the Actions tab and assert the page renders.
    await page.getByRole('link', { name: /actions/i }).click();
    await expect(page.getByRole('heading', { name: /admin actions/i })).toBeVisible();
  });
});
