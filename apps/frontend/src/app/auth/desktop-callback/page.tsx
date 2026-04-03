"use client";

import { useAuth, SignIn } from "@clerk/nextjs";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://api-dev.isol8.co/api/v1";

export default function DesktopCallback() {
  const { isSignedIn, isLoaded, getToken } = useAuth();
  const [status, setStatus] = useState("Signing in...");
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;

    async function getSignInToken() {
      try {
        const jwt = await getToken();
        if (!jwt) return;

        setStatus("Preparing desktop sign-in...");

        const resp = await fetch(`${API_URL}/auth/desktop/sign-in-token`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${jwt}`,
            "Content-Type": "application/json",
          },
        });

        if (!resp.ok) {
          const text = await resp.text();
          console.error("Sign-in token failed:", resp.status, text);
          setStatus("Failed to create sign-in token.");
          setError(true);
          return;
        }

        const data = await resp.json();

        setStatus("Opening Isol8 desktop app...");
        window.location.href = `isol8://auth?ticket=${encodeURIComponent(data.token)}`;
      } catch (err) {
        console.error("Desktop callback error:", err);
        setStatus("Something went wrong.");
        setError(true);
      }
    }

    getSignInToken();
  }, [isLoaded, isSignedIn, getToken]);

  // If not signed in, show the Clerk sign-in component.
  // After sign-in, Clerk sets isSignedIn=true and the useEffect fires.
  if (isLoaded && !isSignedIn) {
    return (
      <div className="flex justify-center items-center h-screen">
        <SignIn
          forceRedirectUrl="/auth/desktop-callback"
          appearance={{
            elements: { rootBox: "mx-auto" },
          }}
        />
      </div>
    );
  }

  return (
    <div className="flex justify-center items-center h-screen">
      <div className="text-center">
        <h1 className="text-xl font-semibold mb-2">{status}</h1>
        <p className="text-sm text-muted-foreground">
          {error
            ? "Please close this tab and try again from the desktop app."
            : "You can close this tab after the app opens."}
        </p>
      </div>
    </div>
  );
}
