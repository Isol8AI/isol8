import type { Page } from '@playwright/test';
import { createSignInToken } from '../fixtures/clerk-admin';

/**
 * Programmatic sign-in via Clerk's ticket strategy. Bypasses the UI form
 * entirely — there's nothing for us to gain by exercising Clerk's own login
 * page (it's covered by Clerk's tests), and the form selectors are fragile.
 * Mirrors the pattern the old chat.smoke.spec.ts used.
 */
export async function signIn(
  page: Page,
  baseUrl: string,
  clerkUserId: string,
): Promise<void> {
  const secretKey = process.env.CLERK_SECRET_KEY;
  if (!secretKey) throw new Error('CLERK_SECRET_KEY required for signIn');

  const ticket = await createSignInToken({ secretKey, userId: clerkUserId });

  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => {
      const w = window as Window & {
        Clerk?: { loaded?: boolean; client?: unknown };
      };
      return w.Clerk?.loaded === true && w.Clerk?.client != null;
    },
    { timeout: 30_000 },
  );

  await page.evaluate(async (t: string) => {
    const w = window as unknown as {
      Clerk: {
        client: {
          signIn: {
            create: (
              opts: Record<string, string>,
            ) => Promise<{ createdSessionId: string }>;
          };
        };
        setActive: (opts: { session: string }) => Promise<void>;
      };
    };
    const si = await w.Clerk.client.signIn.create({ strategy: 'ticket', ticket: t });
    await w.Clerk.setActive({ session: si.createdSessionId });
  }, ticket);
}
