/**
 * Set the Clerk `unsafeMetadata.onboarded` flag for the given user.
 *
 * `ChatLayout` gates the chat UI on this flag (`src/components/chat/ChatLayout.tsx`);
 * when false, it redirects to `/onboarding` where the user picks "Personal" or
 * "Organization". The onboarding page then flips the flag to true.
 *
 * Uses the /metadata endpoint (merges, does not replace), so other fields on
 * unsafe_metadata are preserved.
 */
export async function setUserOnboardedFlag(userId: string, value: boolean): Promise<void> {
  const secretKey = process.env.CLERK_SECRET_KEY;
  if (!secretKey) throw new Error('[e2e] CLERK_SECRET_KEY not set');

  const res = await fetch(`https://api.clerk.com/v1/users/${userId}/metadata`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${secretKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ unsafe_metadata: { onboarded: value } }),
  });
  if (!res.ok) {
    throw new Error(`[e2e] Clerk metadata PATCH ${res.status}: ${await res.text()}`);
  }
  console.log(`[e2e] Set onboarded=${value} for user ${userId}`);
}

/**
 * Force-flip `unsafeMetadata.onboarded=true`. Shortcut used by the fast chat
 * smoke gate so it can skip the /onboarding click-through and go straight to
 * /chat. The full journey spec should NOT use this — it's supposed to drive
 * the real onboarding flow.
 */
export async function markUserOnboarded(userId: string): Promise<void> {
  await setUserOnboardedFlag(userId, true);
}

/**
 * Force-flip `unsafeMetadata.onboarded=false`. Used by the full journey spec
 * to reset the test user before each run so /chat redirects to /onboarding
 * and the test exercises the real first-login flow.
 */
export async function markUserNotOnboarded(userId: string): Promise<void> {
  await setUserOnboardedFlag(userId, false);
}
