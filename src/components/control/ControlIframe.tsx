"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Loader2 } from "lucide-react";
import { BACKEND_URL } from "@/lib/api";

const TOKEN_REFRESH_MS = 50_000; // Refresh before Clerk's ~60s expiry

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
        setSrc(`${BACKEND_URL}/control-ui/?token=${encodeURIComponent(token)}`);
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
      className="w-full h-full border-0"
      title="OpenClaw Control Panel"
      allow="clipboard-write"
    />
  );
}
