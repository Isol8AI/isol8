"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CreateOrganization,
  useAuth,
  useOrganization,
  useOrganizationList,
  useUser,
} from "@clerk/nextjs";
import { useApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { User, Users } from "lucide-react";

export default function OnboardingPage() {
  const router = useRouter();
  const { isLoaded } = useAuth();
  const { user } = useUser();
  const { organization, isLoaded: orgLoaded } = useOrganization();
  const { userMemberships, isLoaded: orgsLoaded, setActive } = useOrganizationList({
    userMemberships: true,
  });
  const api = useApi();
  const [mode, setMode] = useState<"choose" | "personal" | "org">("choose");
  const [loading, setLoading] = useState(false);

  // Two redirect triggers:
  //
  // 1. useOrganization().organization is non-null — Clerk has already set
  //    this org as active (happens automatically after CreateOrganization
  //    finishes or after accepting an invite via the Clerk flows). We can
  //    go straight to /chat because the JWT already has the right org_id.
  //
  // 2. userMemberships has entries but no org is active — the user accepted
  //    an invite but Clerk didn't auto-activate. Call setActive() first,
  //    then redirect once the JWT is settled.
  //
  // In BOTH paths we also write `unsafeMetadata.onboarded = true`, matching
  // the personal-flow behavior below. The flag is the durable, user-scoped
  // source of truth for "has this user completed onboarding" — Clerk's
  // active-org state is session-scoped and doesn't persist across fresh
  // logins, so without the flag a user would bounce to /onboarding every
  // time they log in on a new browser.
  //
  // IMPORTANT: skip when mode === "org" — the user is actively inside
  // Clerk's CreateOrganization component (which includes the invitation
  // screen). Clerk sets `organization` the instant the org is created,
  // BEFORE the invitation step. If we redirect on that signal, the
  // invitation screen never shows.
  useEffect(() => {
    if (!isLoaded || !orgLoaded || !orgsLoaded) return;
    if (mode === "org") return; // let CreateOrganization handle its flow

    const markOnboardedAndRedirect = async () => {
      try {
        await user?.update({ unsafeMetadata: { onboarded: true } });
      } catch {
        // Best-effort — failure to write the flag shouldn't block the
        // redirect; ChatLayout's auto-activate fallback will still get the
        // user into /chat on subsequent loads.
      }
      router.push("/chat");
    };

    // Path 1: org already active
    if (organization) {
      markOnboardedAndRedirect();
      return;
    }
    // Path 2: has memberships but no active org
    const memberships = userMemberships?.data;
    if (memberships && memberships.length > 0 && setActive) {
      setActive({ organization: memberships[0].organization.id }).then(
        markOnboardedAndRedirect,
      );
    }
  }, [isLoaded, orgLoaded, orgsLoaded, organization, userMemberships, setActive, router, mode, user]);

  if (!isLoaded || !orgsLoaded || !orgLoaded) return null;

  // If user has an active org or memberships, we're redirecting — show nothing
  // (but only when not in the org-creation flow)
  if (mode !== "org" && organization) return null;
  if (mode !== "org" && userMemberships?.data && userMemberships.data.length > 0) return null;

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
          // Round-trip back through /onboarding (NOT /chat). The effect at
          // the top of this file will then detect the freshly-created org
          // in userMemberships.data, call setActive() so the JWT has the
          // right org_id, await it, and redirect to /chat with a fully-
          // settled session. If we redirected straight to /chat, ChatLayout
          // could mount ProvisioningStepper while the JWT is still mid-
          // switch between personal and org context — causing the double-
          // provision bug where the same human ends up with two containers.
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
