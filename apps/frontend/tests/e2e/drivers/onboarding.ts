import type { Page } from '@playwright/test';

export async function onboardPersonal(page: Page): Promise<void> {
  await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
  await page.getByRole('button', { name: 'Personal' }).click();
  await page.waitForURL(/\/chat/, { timeout: 30_000 });
}

export async function onboardOrganization(
  page: Page,
  orgName: string,
): Promise<{ orgId: string }> {
  await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
  await page.getByRole('button', { name: 'Organization' }).click();
  await page.getByLabel(/name/i).fill(orgName);
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
