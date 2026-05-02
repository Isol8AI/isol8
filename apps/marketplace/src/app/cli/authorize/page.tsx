"use client";

import { useAuth, useUser } from "@clerk/nextjs";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Suspense, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";

export default function CliAuthorizePage() {
  // useSearchParams requires a Suspense boundary for static prerender.
  return (
    <Suspense fallback={<main className="max-w-xl mx-auto px-6 py-12" />}>
      <CliAuthorizeContent />
    </Suspense>
  );
}

function CliAuthorizeContent() {
  const { isSignedIn, getToken } = useAuth();
  const { user } = useUser();
  const params = useSearchParams();
  const code = params.get("code") ?? "";
  const [status, setStatus] = useState<"idle" | "authorizing" | "ok" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function authorize() {
    if (!code) return;
    setStatus("authorizing");
    setErrorMsg(null);
    try {
      const jwt = await getToken();
      if (!jwt) throw new Error("no clerk session");
      const resp = await fetch(`${API}/api/v1/marketplace/cli/auth/authorize`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${jwt}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({ device_code: code }),
      });
      if (resp.ok) {
        setStatus("ok");
      } else {
        const txt = await resp.text();
        setErrorMsg(`${resp.status}: ${txt.slice(0, 200)}`);
        setStatus("error");
      }
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "unknown");
      setStatus("error");
    }
  }

  if (!code) {
    return (
      <main className="max-w-xl mx-auto px-6 py-12">
        <h1 className="text-2xl font-bold mb-4">Authorize CLI</h1>
        <p className="text-zinc-400">
          This page is opened by <code>npx @isol8/marketplace install</code> with a
          device code. The link you followed is missing the code parameter.
        </p>
      </main>
    );
  }

  if (!isSignedIn) {
    const next = encodeURIComponent(`/cli/authorize?code=${code}`);
    return (
      <main className="max-w-xl mx-auto px-6 py-12">
        <h1 className="text-2xl font-bold mb-4">Authorize CLI</h1>
        <p className="text-zinc-300 mb-6">
          You need to sign in before linking your CLI to your marketplace account.
        </p>
        <Link
          href={`/sign-in?redirect_url=${next}`}
          className="inline-block px-6 py-2 rounded bg-zinc-100 text-zinc-950 font-semibold"
        >
          Sign in to continue
        </Link>
      </main>
    );
  }

  return (
    <main className="max-w-xl mx-auto px-6 py-12">
      <h1 className="text-2xl font-bold mb-4">Authorize CLI</h1>
      <p className="text-zinc-300 mb-3">
        You&apos;re about to link the CLI session running on your machine to{" "}
        <span className="text-zinc-100 font-medium">
          {user?.primaryEmailAddress?.emailAddress ?? "this account"}
        </span>
        .
      </p>
      <p className="text-zinc-500 text-sm mb-6">
        Device code: <code>{code}</code>
      </p>

      {status === "idle" && (
        <button
          type="button"
          onClick={authorize}
          className="px-6 py-2 rounded bg-zinc-100 text-zinc-950 font-semibold"
        >
          Authorize this device
        </button>
      )}

      {status === "authorizing" && (
        <p className="text-zinc-400">Authorizing…</p>
      )}

      {status === "ok" && (
        <div className="rounded border border-emerald-700/50 bg-emerald-900/30 p-4">
          <p className="text-emerald-200 font-medium">CLI authorized.</p>
          <p className="text-zinc-400 text-sm mt-2">
            Switch back to your terminal — the install will continue automatically.
          </p>
        </div>
      )}

      {status === "error" && (
        <div className="rounded border border-red-700/50 bg-red-900/30 p-4">
          <p className="text-red-200 font-medium">Authorization failed.</p>
          {errorMsg && <p className="text-zinc-400 text-sm mt-2">{errorMsg}</p>}
        </div>
      )}
    </main>
  );
}
