/**
 * Wraps the Clerk Backend API for e2e fixture lifecycle.
 *
 * NEVER trust the ?email_address[] query filter — verified 2026-04-17 it
 * returned ALL users in the instance regardless of the param. findUserByEmail
 * always filters in JS.
 */

const CLERK_API = 'https://api.clerk.com/v1';

type ClerkUser = {
  id: string;
  email_addresses?: Array<{ email_address?: string }>;
  first_name?: string | null;
  last_name?: string | null;
};

export async function createUser(opts: {
  secretKey: string;
  email: string;
  password: string;
  runId: string;
}): Promise<string> {
  const res = await fetch(`${CLERK_API}/users`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${opts.secretKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      email_address: [opts.email],
      password: opts.password,
      first_name: 'E2E',
      last_name: opts.runId,
      skip_password_checks: true,
      unsafe_metadata: {
        onboarded: false,
        e2e_run_id: opts.runId,
      },
    }),
  });
  if (!res.ok) {
    throw new Error(`Clerk createUser ${res.status}: ${await res.text()}`);
  }
  const body = (await res.json()) as { id: string };
  return body.id;
}

export async function findUserByEmail(opts: {
  secretKey: string;
  email: string;
}): Promise<ClerkUser | null> {
  const res = await fetch(
    `${CLERK_API}/users?email_address[]=${encodeURIComponent(opts.email)}`,
    { headers: { Authorization: `Bearer ${opts.secretKey}` } },
  );
  if (!res.ok) {
    throw new Error(`Clerk findUserByEmail ${res.status}: ${await res.text()}`);
  }
  const allUsers = (await res.json()) as ClerkUser[];
  return (
    allUsers.find((u) =>
      u.email_addresses?.some(
        (e) => e.email_address?.toLowerCase() === opts.email.toLowerCase(),
      ),
    ) ?? null
  );
}

export async function deleteUser(opts: {
  secretKey: string;
  userId: string;
}): Promise<void> {
  const res = await fetch(`${CLERK_API}/users/${opts.userId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${opts.secretKey}` },
  });
  if (!res.ok && res.status !== 404) {
    throw new Error(`Clerk deleteUser ${res.status}: ${await res.text()}`);
  }
}

export async function deleteOrg(opts: {
  secretKey: string;
  orgId: string;
}): Promise<void> {
  const res = await fetch(`${CLERK_API}/organizations/${opts.orgId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${opts.secretKey}` },
  });
  if (!res.ok && res.status !== 404) {
    throw new Error(`Clerk deleteOrg ${res.status}: ${await res.text()}`);
  }
}

export async function createSignInToken(opts: {
  secretKey: string;
  userId: string;
}): Promise<string> {
  const res = await fetch(`${CLERK_API}/sign_in_tokens`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${opts.secretKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ user_id: opts.userId }),
  });
  if (!res.ok) {
    throw new Error(`Clerk sign_in_tokens ${res.status}: ${await res.text()}`);
  }
  const { token } = (await res.json()) as { token: string };
  return token;
}
