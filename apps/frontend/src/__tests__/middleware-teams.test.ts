// Tests the /teams feature-flag gate inside the Next middleware.
//
// We mock @clerk/nextjs/server so that:
//   - clerkMiddleware just returns the handler we pass in (it's a passthrough
//     wrapper for the auth callback)
//   - createRouteMatcher returns a regex-ish matcher that mirrors the prod
//     behavior for the patterns we care about ("/teams(.*)", etc.)
//
// The auth() callback is stubbed to return { userId: "test-user" } so the
// Clerk-protected branch doesn't try to sign-in-redirect during the
// "flag is on" passthrough case.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { NextRequest, type NextResponse } from 'next/server';

type ClerkAuthCallback = (
  auth: () => Promise<{ userId: string | null; redirectToSignIn: () => unknown }>,
  req: NextRequest,
  evt: unknown,
) => unknown;

type RouteMatcherReq = { nextUrl: { pathname: string } };

vi.mock('@clerk/nextjs/server', () => {
  return {
    clerkMiddleware: (handler: ClerkAuthCallback) => {
      return (req: NextRequest, evt: unknown) => {
        const auth = async () => ({
          userId: 'test-user',
          redirectToSignIn: () => ({ kind: 'redirect-to-sign-in' }),
        });
        return handler(auth, req, evt);
      };
    },
    createRouteMatcher: (patterns: string[]) => {
      const regexes = patterns.map(
        (p) => new RegExp('^' + p.replace(/\(\.\*\)/g, '.*') + '$'),
      );
      return (req: RouteMatcherReq) =>
        regexes.some((r) => r.test(req.nextUrl.pathname));
    },
  };
});

type MiddlewareFn = (
  req: NextRequest,
  evt: unknown,
) => Promise<NextResponse | undefined> | NextResponse | undefined;

async function loadMiddleware(): Promise<MiddlewareFn> {
  const mod = await import('../middleware');
  return mod.default as MiddlewareFn;
}

describe('middleware /teams feature flag gate', () => {
  const ORIGINAL_FLAG = process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED;

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    if (ORIGINAL_FLAG === undefined) {
      delete process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED;
    } else {
      process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED = ORIGINAL_FLAG;
    }
  });

  it('rewrites /teams to /404 when the flag is unset', async () => {
    delete process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED;
    const middleware = await loadMiddleware();
    const req = new NextRequest(new URL('https://app.isol8.co/teams'), {
      headers: { host: 'app.isol8.co' },
    });
    const result = await middleware(req, {});
    expect(result).toBeDefined();
    // NextResponse.rewrite sets x-middleware-rewrite to the target URL.
    expect(result?.headers.get('x-middleware-rewrite') ?? '').toContain('/404');
  });

  it('rewrites /teams to /404 when the flag is "false"', async () => {
    process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED = 'false';
    const middleware = await loadMiddleware();
    const req = new NextRequest(new URL('https://app.isol8.co/teams/agents'), {
      headers: { host: 'app.isol8.co' },
    });
    const result = await middleware(req, {});
    expect(result).toBeDefined();
    expect(result?.headers.get('x-middleware-rewrite') ?? '').toContain('/404');
  });

  it('rewrites nested /teams/* paths to /404 when the flag is off', async () => {
    process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED = 'false';
    const middleware = await loadMiddleware();
    const req = new NextRequest(
      new URL('https://app.isol8.co/teams/inbox/123'),
      { headers: { host: 'app.isol8.co' } },
    );
    const result = await middleware(req, {});
    expect(result?.headers.get('x-middleware-rewrite') ?? '').toContain('/404');
  });

  it('passes /teams through (no /404 rewrite) when the flag is "true"', async () => {
    process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED = 'true';
    const middleware = await loadMiddleware();
    const req = new NextRequest(new URL('https://app.isol8.co/teams'), {
      headers: { host: 'app.isol8.co' },
    });
    const result = await middleware(req, {});
    // Either undefined (no early return) or some non-404 response. The key
    // assertion is that the middleware did not rewrite to /404.
    const rewrite = result?.headers.get('x-middleware-rewrite') ?? '';
    expect(rewrite).not.toContain('/404');
  });

  it('does not gate non-/teams paths when the flag is off', async () => {
    process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED = 'false';
    const middleware = await loadMiddleware();
    const req = new NextRequest(new URL('https://app.isol8.co/chat'), {
      headers: { host: 'app.isol8.co' },
    });
    const result = await middleware(req, {});
    const rewrite = result?.headers.get('x-middleware-rewrite') ?? '';
    expect(rewrite).not.toContain('/404');
  });

  it('does not match /teamsfoo (path must be /teams or /teams/*)', async () => {
    process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED = 'false';
    const middleware = await loadMiddleware();
    const req = new NextRequest(new URL('https://app.isol8.co/teamsfoo'), {
      headers: { host: 'app.isol8.co' },
    });
    const result = await middleware(req, {});
    const rewrite = result?.headers.get('x-middleware-rewrite') ?? '';
    expect(rewrite).not.toContain('/404');
  });
});
