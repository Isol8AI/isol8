"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";

export default function DesktopCallback() {
  const { isSignedIn, getToken } = useAuth();
  const [status, setStatus] = useState("Signing in...");

  useEffect(() => {
    if (!isSignedIn) return;

    getToken().then((token) => {
      if (token) {
        setStatus("Opening Isol8 desktop app...");
        window.location.href = `isol8://auth?token=${encodeURIComponent(token)}`;
      }
    });
  }, [isSignedIn, getToken]);

  return (
    <div className="flex justify-center items-center h-screen">
      <div className="text-center">
        <h1 className="text-xl font-semibold mb-2">{status}</h1>
        <p className="text-sm text-muted-foreground">
          You can close this tab after the app opens.
        </p>
      </div>
    </div>
  );
}
