import type { Page } from '@playwright/test';

/**
 * The /chat page wraps its content in `ProvisioningStepper`. After provisioning
 * succeeds, the stepper advances to phase `"channels"` whenever the user has
 * no main bot linked (`hasMainBot(linksData) === false`) and shows a "Set up
 * Telegram" wizard over the chat view — `ChatInput` is not mounted. The
 * stepper's `onboardingComplete` state is in-memory only (useState), so it
 * re-shows on every fresh page load until the user clicks "Cancel" or
 * completes the wizard.
 *
 * This helper detects the wizard and clicks "Cancel" to dismiss it, falling
 * through if it's not present (user is already past channel setup).
 */
export async function dismissChannelSetupIfPresent(page: Page): Promise<void> {
  const setupHeading = page.getByRole('heading', { name: 'Set up Telegram' });
  try {
    await setupHeading.waitFor({ state: 'visible', timeout: 5_000 });
  } catch {
    return;
  }
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await setupHeading.waitFor({ state: 'hidden', timeout: 5_000 });
  console.log('[e2e] Dismissed channel setup wizard');
}
