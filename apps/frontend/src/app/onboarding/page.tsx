"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CreateOrganization, useAuth, useUser } from "@clerk/nextjs";
import { useApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { User, Users } from "lucide-react";

export default function OnboardingPage() {
  const router = useRouter();
  const { isLoaded } = useAuth();
  const { user } = useUser();
  const api = useApi();
  const [mode, setMode] = useState<"choose" | "personal" | "org">("choose");
  const [loading, setLoading] = useState(false);

  if (!isLoaded) return null;

  async function handlePersonal() {
    setLoading(true);
    try {
      // Mark onboarding complete and sync user
      await user?.update({ unsafeMetadata: { onboarded: true } });
      await api.syncUser();
      router.push("/chat");
    } catch {
      setLoading(false);
    }
  }

  if (mode === "org") {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-6 bg-background">
        <div className="text-center mb-4">
          <h1 className="text-2xl font-bold">Create your organization</h1>
          <p className="text-muted-foreground mt-2">
            Your team will share agents, workspace, and billing.
          </p>
        </div>
        <CreateOrganization
          afterCreateOrganizationUrl="/chat"
          skipInvitationScreen={false}
        />
        <Button variant="ghost" onClick={() => setMode("choose")}>
          Back
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-8 bg-background">
      <div className="text-center">
        <h1 className="text-3xl font-bold">Welcome to Isol8</h1>
        <p className="text-muted-foreground mt-2">
          How would you like to use Isol8?
        </p>
      </div>

      <div className="flex gap-4">
        <button
          onClick={handlePersonal}
          disabled={loading}
          className="flex flex-col items-center gap-3 p-6 rounded-lg border border-border hover:border-primary/50 hover:bg-accent transition-colors w-56"
        >
          <User className="h-8 w-8" />
          <span className="font-semibold">Personal</span>
          <span className="text-sm text-muted-foreground text-center">
            Your own private AI agent workspace
          </span>
        </button>

        <button
          onClick={() => setMode("org")}
          disabled={loading}
          className="flex flex-col items-center gap-3 p-6 rounded-lg border border-border hover:border-primary/50 hover:bg-accent transition-colors w-56"
        >
          <Users className="h-8 w-8" />
          <span className="font-semibold">Organization</span>
          <span className="text-sm text-muted-foreground text-center">
            Share agents and billing with your team
          </span>
        </button>
      </div>
    </div>
  );
}
