import type { Page } from '@playwright/test';

export async function signIn(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.goto('/sign-in');
  await page.getByLabel(/email/i).fill(email);
  await page.getByRole('button', { name: /continue|sign in/i }).first().click();
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole('button', { name: /continue|sign in/i }).first().click();
  await page.waitForURL((url) => !url.pathname.startsWith('/sign-in'), {
    timeout: 30_000,
  });
}
