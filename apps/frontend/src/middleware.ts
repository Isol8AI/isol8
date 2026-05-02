import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

const isProtectedRoute = createRouteMatcher(["/chat(.*)", "/onboarding", "/settings(.*)"]);

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
const PAPERCLIP_HOSTS = new Set([
  "company.isol8.co",
  "dev.company.isol8.co",
]);

export default clerkMiddleware(async (auth, req) => {
  const host = (req.headers.get("host") ?? "").toLowerCase();

  // Paperclip proxy: passthrough — let next.config.ts beforeFiles
  // rewrite shuttle the request to the backend.
  if (PAPERCLIP_HOSTS.has(host)) {
    return NextResponse.next();
  }

  const decision = decideAdminHostRouting(host, req.nextUrl.pathname);

  if (decision.kind === "not_found") {
    return new NextResponse(null, { status: 404 });
  }
  if (decision.kind === "redirect") {
    const url = req.nextUrl.clone();
    url.pathname = decision.to;
    return NextResponse.redirect(url);
  }

  const authObj = await auth();

  if (isProtectedRoute(req)) {
    if (!authObj.userId) {
      return authObj.redirectToSignIn();
    }
  }
});

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)',
  ],
};
