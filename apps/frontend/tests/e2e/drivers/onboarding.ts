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
 * which mounts Clerk's CreateOrganization widget.
 *
 * Takes `onOrgCreated` so the caller can record the orgId on the test
 * fixture BEFORE we wait for the /chat redirect. Without that, a
 * successful org create followed by a UI failure (URL wait timeout,
 * network blip) would leak the org because afterAll's cleanupUser would
 * skip deleteOrg (Codex P1 on PR #309).
 */
export async function onboardOrganization(
  page: Page,
  orgName: string,
  onOrgCreated: (orgId: string) => void,
): Promise<{ orgId: string }> {
  await page.goto('/chat');
  await page.waitForURL(/\/onboarding/, { timeout: 30_000 });
  await page.getByRole('button', { name: 'Organization' }).click();
  await page.getByRole('textbox', { name: /name/i }).fill(orgName);
  await page.getByRole('button', { name: /create|next/i }).first().click();

  // Clerk's CreateOrganization shows an "Invite new members" screen after
  // create — `skipInvitationScreen={false}` in onboarding/page.tsx. Click
  // "Skip" so the flow can advance to /chat. Without this the page hangs
  // on the invitation screen and the /chat URL wait below times out
  // (verified from PR #309 deploy artifact, 2026-04-20).
  await page.getByRole('button', { name: /^skip$/i }).click({ timeout: 30_000 });

  // Wait for Clerk to register the new org BEFORE waiting for any URL —
  // the org is the load-bearing teardown handle. Hand it to the caller
  // immediately so even a downstream throw still leaves cleanupUser able
  // to delete it.
  await page.waitForFunction(
    () => {
      const w = window as Window & {
        Clerk?: { organization?: { id?: string } };
      };
      return Boolean(w.Clerk?.organization?.id);
    },
    { timeout: 60_000 },
  );
  const orgId = await page.evaluate(() => {
    const w = window as Window & {
      Clerk?: { organization?: { id?: string } };
    };
    return w.Clerk!.organization!.id!;
  });
  onOrgCreated(orgId);

  // Now wait for the /chat redirect. If this throws, orgId is already
  // recorded so cleanup will still delete it.
  await page.waitForURL(/\/chat/, { timeout: 60_000 });

  return { orgId };
}
