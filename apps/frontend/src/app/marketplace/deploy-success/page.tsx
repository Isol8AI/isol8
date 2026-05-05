"use client";

import { useAuth } from "@clerk/nextjs";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";
const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "https://app.isol8.co";

/**
 * Post-purchase / post-deploy landing page.
 *
 * Two entry shapes:
 *   1. Free deploy: BuyButton already POSTed /deploy and got an agent_uuid
 *      back. URL is /deploy-success?listing_slug=…&agent_uuid=…
 *      We render the success card immediately.
 *
 *   2. Paid checkout return: Stripe redirects here on completion with
 *      session_id={CHECKOUT_SESSION_ID} substituted. URL is
 *      /deploy-success?listing_slug=…&session_id=…
 *      We fire the deploy on mount. If the entitlement check 403s
 *      (Stripe webhook hasn't written the marketplace-purchases row yet),
 *      we surface a "refresh in a few seconds" message — Phase 2 could
 *      add automatic retry-with-backoff, but for v0 a manual refresh
 *      is acceptable.
 */
export default function DeploySuccessPage() {
  return (
    <Suspense fallback={<Loading />}>
      <DeploySuccessInner />
    </Suspense>
  );
}

function Loading() {
  return (
    <main className="max-w-md mx-auto px-6 py-16 text-center">
      <h1 className="text-2xl font-bold mb-4">Loading…</h1>
    </main>
  );
}

function DeploySuccessInner() {
  const params = useSearchParams();
  const listingSlug = params.get("listing_slug") ?? "";
  const sessionId = params.get("session_id");
  const initialAgentUuid = params.get("agent_uuid");

  const { isSignedIn, getToken, isLoaded } = useAuth();

  const [agentUuid, setAgentUuid] = useState<string | null>(initialAgentUuid);
  const [phase, setPhase] = useState<
    "idle" | "deploying" | "ready" | "entitlement_pending" | "error"
  >(initialAgentUuid ? "ready" : "idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Not signed in on this domain — Stripe shouldn't ever land us here without
  // a Clerk session, but if it happens send the user to sign-in with a
  // redirect back to this same URL. Side effect lives in useEffect so it
  // doesn't fire during render (Strict Mode would double-invoke; the redirect
  // is also an anti-pattern in render bodies).
  useEffect(() => {
    if (isLoaded && !isSignedIn) {
      window.location.href = `/sign-in?redirect_url=${encodeURIComponent(window.location.href)}`;
    }
  }, [isLoaded, isSignedIn]);

  // Paid-return path: fire deploy on mount once Clerk auth is loaded.
  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    if (initialAgentUuid) return; // free-deploy path already has the result
    if (!sessionId) return; // no session_id → nothing to verify
    if (!listingSlug) return;
    if (phase !== "idle") return;

    let cancelled = false;
    (async () => {
      setPhase("deploying");
      try {
        const jwt = await getToken();
        const resp = await fetch(
          `${API}/api/v1/marketplace/listings/${encodeURIComponent(listingSlug)}/deploy`,
          {
            method: "POST",
            headers: {
              "content-type": "application/json",
              Authorization: `Bearer ${jwt}`,
            },
          }
        );
        if (cancelled) return;
        if (resp.status === 403) {
          // Webhook race — purchase row not yet written. Tell the user to refresh.
          setPhase("entitlement_pending");
          return;
        }
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(body?.detail ?? `deploy failed (${resp.status})`);
        }
        const body = (await resp.json()) as { agent_uuid?: string };
        if (body.agent_uuid) setAgentUuid(body.agent_uuid);
        setPhase("ready");
      } catch (e) {
        if (cancelled) return;
        setErrorMsg(e instanceof Error ? e.message : "Deploy failed.");
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, getToken, listingSlug, sessionId, initialAgentUuid, phase]);

  // While the redirect effect above is firing (or auth is still loading),
  // render a placeholder. The effect handles the actual navigation.
  if (isLoaded && !isSignedIn) {
    return <Loading />;
  }

  return (
    <main className="max-w-md mx-auto px-6 py-16">
      {phase === "deploying" && (
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-4">Verifying purchase and deploying…</h1>
          <p className="text-zinc-400">
            Hang tight — this only takes a second.
          </p>
        </div>
      )}

      {phase === "entitlement_pending" && (
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-4">Almost there</h1>
          <p className="text-zinc-400 mb-6">
            Purchase verification is taking a moment — refresh in a few
            seconds. Stripe&apos;s confirmation webhook may not have completed
            yet.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="px-6 py-3 bg-zinc-100 text-zinc-950 rounded-lg font-semibold"
          >
            Refresh
          </button>
        </div>
      )}

      {phase === "error" && (
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-4">Deploy failed</h1>
          <p className="text-red-400 mb-6">{errorMsg}</p>
          <button
            type="button"
            onClick={() => {
              setErrorMsg(null);
              setPhase("idle");
            }}
            className="px-6 py-3 bg-zinc-100 text-zinc-950 rounded-lg font-semibold"
          >
            Try again
          </button>
        </div>
      )}

      {phase === "ready" && (
        <div>
          <h1 className="text-3xl font-bold mb-4">Deployed!</h1>
          <p className="text-zinc-400 mb-6">
            <span className="font-mono text-zinc-300">{listingSlug}</span> is
            now in your Isol8 container.
          </p>
          {agentUuid && (
            <p className="text-xs text-zinc-500 mb-6">
              Agent ID: <code className="bg-zinc-900 px-2 py-0.5 rounded">{agentUuid}</code>
            </p>
          )}
          <a
            href={
              agentUuid
                ? `${APP_URL}/chat?agent=${encodeURIComponent(agentUuid)}`
                : `${APP_URL}/chat`
            }
            className="inline-block px-6 py-3 bg-zinc-100 text-zinc-950 rounded-lg font-semibold"
          >
            Open in chat →
          </a>
        </div>
      )}

      {phase === "idle" && (
        // Should be transient — useEffect transitions to "deploying" or
        // "ready" almost immediately. Render a soft loading state.
        <Loading />
      )}
    </main>
  );
}
