import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

const isProtectedRoute = createRouteMatcher(["/chat(.*)", "/auth/desktop-callback", "/onboarding"]);

export default clerkMiddleware(async (auth, req) => {
  const authObj = await auth();

  if (isProtectedRoute(req)) {
    if (!authObj.userId) {
      return authObj.redirectToSignIn();
    }

    // Redirect to onboarding if user hasn't completed it yet
    // Skip if already on onboarding page
    if (req.nextUrl.pathname !== "/onboarding") {
      const metadata = authObj.sessionClaims?.unsafeMetadata as Record<string, unknown> | undefined;
      const onboarded = metadata?.onboarded;
      const hasOrg = !!authObj.orgId;

      // User needs onboarding if they haven't chosen personal or org
      if (!onboarded && !hasOrg) {
        return NextResponse.redirect(new URL("/onboarding", req.url));
      }
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
