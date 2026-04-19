import type { Page } from '@playwright/test';

/**
 * Drive the /onboarding "Personal" path. Programmatic sign-in leaves the
 * page wherever it landed (BASE_URL); we need to navigate into /chat for
 * ChatLayout's "fresh user → /onboarding" redirect to fire.
 */
export async function onboardPersonal(page: Page): Promise<void> {
  await page.goto('/chat');
  await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
  await page.getByRole('button', { name: 'Personal' }).click();
  await page.waitForURL(/\/chat/, { timeout: 30_000 });
}

/**
 * Drive the /onboarding "Organization" path. Same redirect dance — navigate
 * into /chat to trigger the onboarding redirect, then click "Organization"
 * which mounts Clerk's CreateOrganization widget. Returns the new org id so
 * teardown can delete it.
 */
export async function onboardOrganization(
  page: Page,
  orgName: string,
): Promise<{ orgId: string }> {
  await page.goto('/chat');
  await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
  await page.getByRole('button', { name: 'Organization' }).click();
  await page.getByRole('textbox', { name: /name/i }).fill(orgName);
  await page.getByRole('button', { name: /create|next/i }).first().click();
  await page.waitForURL(/\/chat/, { timeout: 60_000 });

  const orgId = await page.evaluate(() => {
    const w = window as Window & {
      Clerk?: { organization?: { id?: string } };
    };
    return w.Clerk?.organization?.id ?? '';
  });
  if (!orgId) throw new Error('No active org after CreateOrganization');
  return { orgId };
}
