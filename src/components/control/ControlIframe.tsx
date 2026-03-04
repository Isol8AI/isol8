"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Loader2 } from "lucide-react";
import { BACKEND_URL } from "@/lib/api";

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

  // Load once — the SPA manages its own WebSocket reconnection.
  // Reloading the iframe kills the WS connection and creates a new session.
  useEffect(() => {
    let cancelled = false;

    async function loadOnce() {
      try {
        const token = await getToken();
        if (cancelled || !token) return;
        const params = new URLSearchParams();
        params.set("token", token);
        if (WS_URL) params.set("ws_url", WS_URL);
        setSrc(`${BACKEND_URL}/control-ui/?${params.toString()}`);
      } catch {
        // Token fetch failed — will retry on next render
      }
    }

    loadOnce();

    return () => {
      cancelled = true;
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
