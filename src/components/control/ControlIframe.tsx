"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Loader2 } from "lucide-react";
import { BACKEND_URL } from "@/lib/api";

const TOKEN_REFRESH_MS = 50_000; // Refresh before Clerk's ~60s expiry

function getWsUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  // Derive from API URL, same logic as useGateway.tsx
  const apiUrl =
    process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
  return apiUrl
    .replace(/^https:\/\//, "wss://")
    .replace(/^http:\/\//, "ws://")
    .replace("api-", "ws-")
    .replace(/\/api\/v1$/, "");
}

const WS_URL = getWsUrl();

export function ControlIframe() {
  const { getToken } = useAuth();
  const [src, setSrc] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function refreshSrc() {
      try {
        const token = await getToken();
        if (cancelled || !token) return;
        const params = new URLSearchParams();
        params.set("token", token);
        if (WS_URL) params.set("ws_url", WS_URL);
        setSrc(`${BACKEND_URL}/control-ui/?${params.toString()}`);
      } catch {
        // Token fetch failed — keep existing src (iframe will use cached page)
      }
    }

    refreshSrc();
    intervalRef.current = setInterval(refreshSrc, TOKEN_REFRESH_MS);

    return () => {
      cancelled = true;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [getToken]);

  if (!src) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        Loading control panel...
      </div>
    );
  }

  return (
    <iframe
      src={src}
      className="w-full flex-1 min-h-0 border-0"
      title="OpenClaw Control Panel"
      allow="clipboard-write"
    />
  );
}
