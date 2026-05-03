import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest } from "next/server";

const isProtectedRoute = createRouteMatcher([
  "/chat(.*)",
  "/onboarding",
  "/settings(.*)",
  "/teams(.*)",
]);

/**
 * Feature flag gate for the native Teams UI (Paperclip integration).
 *
 * When `NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED !== "true"` we 404 the entire
 * `/teams` tree at the middleware layer — defense in depth for prod where
 * the route should be invisible until cutover. Default off; dev/preview
 * environments flip the env var to enable.
 *
 * See spec §8 Phase 1 (flag-gated parallel deployment).
 */
function isTeamsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_TEAMS_NATIVE_UI_ENABLED === "true";
}

const DEFAULT_ADMIN_HOSTS = "admin.isol8.co,admin.dev.isol8.co,admin.localhost:3000";

function parseAdminHosts(raw: string | undefined): Set<string> {
  const source = raw && raw.length > 0 ? raw : DEFAULT_ADMIN_HOSTS;
  return new Set(
    source
      .split(",")
      .map((h) => h.trim().toLowerCase())
      .filter(Boolean),
  );
}

const ADMIN_HOSTS = parseAdminHosts(process.env.NEXT_PUBLIC_ADMIN_HOSTS);

export type AdminHostDecision =
  | { kind: "passthrough" }
  | { kind: "not_found" }
  | { kind: "redirect"; to: string };

/**
 * Pure host/path -> decision function for the admin gate. Exported so the
 * branching logic can be unit-tested without a Next.js request object.
 *
 * Defense in depth (CEO A1): unknown hosts hitting `/admin*` get a 404, not a
 * 403 — we don't want host-header probes to confirm the path even exists.
 * Conversely, an admin host that strays off `/admin` is funneled back to
 * `/admin` so admins can't accidentally land on the public app.
 */
export function decideAdminHostRouting(
  host: string | null | undefined,
  pathname: string,
  adminHosts: Set<string> = ADMIN_HOSTS,
): AdminHostDecision {
  const normalizedHost = (host ?? "").toLowerCase();
  const isAdminHost = adminHosts.has(normalizedHost);
  const isAdminPath = pathname === "/admin" || pathname.startsWith("/admin/");

  if (isAdminPath && !isAdminHost) {
    return { kind: "not_found" };
  }
  if (isAdminHost && !isAdminPath) {
    return { kind: "redirect", to: "/admin" };
  }
  return { kind: "passthrough" };
}

// Hostnames whose traffic is handled by the paperclip-proxy upstream
// via a Next-level rewrite (next.config.ts `beforeFiles`). Middleware
// must passthrough for these or it'll run Clerk auth on a non-Isol8
// host (where there's no Clerk session) and redirect users away
// before the rewrite gets a chance to proxy the request.
//
// IMPORTANT: this check has to run BEFORE clerkMiddleware wraps the
// request — otherwise Clerk's own dev-browser handshake fires (returns
// a 307 to clerk.accounts.dev/v1/client/handshake?...) regardless of
// what our inner callback does. Wrapping clerkMiddleware from outside
// is the only way to fully bypass it for these hosts.
const PAPERCLIP_HOSTS = new Set([
  "company.isol8.co",
  "dev.company.isol8.co",
]);

const _clerkMiddleware = clerkMiddleware(async (auth, req) => {
  const host = (req.headers.get("host") ?? "").toLowerCase();
  const decision = decideAdminHostRouting(host, req.nextUrl.pathname);

  if (decision.kind === "not_found") {
    return new NextResponse(null, { status: 404 });
  }
  if (decision.kind === "redirect") {
    const url = req.nextUrl.clone();
    url.pathname = decision.to;
    return NextResponse.redirect(url);
  }

  // Teams native UI feature flag — when off, 404 before prompting for sign-in
  // so the surface is fully invisible (no Clerk redirect probe).
  if (req.nextUrl.pathname === "/teams" || req.nextUrl.pathname.startsWith("/teams/")) {
    if (!isTeamsEnabled()) {
      const url = req.nextUrl.clone();
      url.pathname = "/404";
      return NextResponse.rewrite(url);
    }
    // Flag is on: fall through to the Clerk auth check below (the matcher
    // already routes /teams(.*) through this middleware).
  }

  const authObj = await auth();

  if (isProtectedRoute(req)) {
    if (!authObj.userId) {
      return authObj.redirectToSignIn();
    }
  }
});

export default function middleware(req: NextRequest, evt: Parameters<typeof _clerkMiddleware>[1]) {
  const host = (req.headers.get("host") ?? "").toLowerCase();
  if (PAPERCLIP_HOSTS.has(host)) {
    // Bypass clerkMiddleware entirely so Clerk's dev-browser handshake
    // doesn't 307-redirect the request away from the beforeFiles rewrite.
    return NextResponse.next();
  }
  return _clerkMiddleware(req, evt);
}

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)',
  ],
};
