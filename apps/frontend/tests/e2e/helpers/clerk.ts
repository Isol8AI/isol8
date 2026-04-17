/**
 * Set the Clerk `unsafeMetadata.onboarded` flag to true for the given user.
 *
 * `ChatLayout` gates the chat UI on this flag (`src/components/chat/ChatLayout.tsx`);
 * when false, it renders `ProvisioningStepper` (the channel setup wizard) instead
 * of `ChatInput`. The test user's flag can drift to false after a Clerk-side
 * reset or when a fresh account is created, so we set it explicitly.
 *
 * Uses the /metadata endpoint (merges, does not replace), so other fields on
 * unsafe_metadata are preserved.
 */
export async function markUserOnboarded(userId: string): Promise<void> {
  const secretKey = process.env.CLERK_SECRET_KEY;
  if (!secretKey) throw new Error('[e2e] CLERK_SECRET_KEY not set');

  const res = await fetch(`https://api.clerk.com/v1/users/${userId}/metadata`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${secretKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ unsafe_metadata: { onboarded: true } }),
  });
  if (!res.ok) {
    throw new Error(`[e2e] Clerk metadata PATCH ${res.status}: ${await res.text()}`);
  }
  console.log(`[e2e] Marked user ${userId} as onboarded`);
}
