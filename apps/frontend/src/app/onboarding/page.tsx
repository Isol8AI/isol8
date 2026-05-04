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
import { usePostHog } from "posthog-js/react";
import { Button } from "@/components/ui/button";
import { User, Users, Mail } from "lucide-react";
import { InviteTeammatesStep } from "@/components/onboarding/InviteTeammatesStep";

export default function OnboardingPage() {
  const router = useRouter();
  const { isLoaded, orgId: authOrgId } = useAuth();
  const { user } = useUser();
  const { organization, isLoaded: orgLoaded } = useOrganization();
  const { userMemberships, userInvitations, isLoaded: orgsLoaded, setActive } = useOrganizationList({
    userMemberships: true,
    userInvitations: true,
  });
  const api = useApi();
  const posthog = usePostHog();
  const [loading, setLoading] = useState(false);
  const [acceptingId, setAcceptingId] = useState<string | null>(null);

  const pendingInvitations = userInvitations?.data ?? [];

  // Tenancy invariant: when the user has pending invitations, force the
  // invitations screen — no escape hatch into personal onboarding because
  // a user can't have personal tenancy AND a pending org invite.
  const [explicitMode, setExplicitMode] = useState<"choose" | "personal" | "org" | "invitations" | null>(null);
  const forcedInvitations = isLoaded && orgsLoaded && pendingInvitations.length > 0;
  const mode = forcedInvitations ? "invitations" : (explicitMode ?? "choose");
  const setMode = setExplicitMode;

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
  // Clerk's CreateOrganization component (now mounted with
  // skipInvitationScreen={true}), and our <InviteTeammatesStep> takes
  // over once `organization` resolves. If we redirected on the
  // organization signal, we'd never render the custom invite step.
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

  async function handleAcceptInvitation(invitationId: string) {
    setAcceptingId(invitationId);
    try {
      posthog?.capture("org_invitation_accepted", { org_id: invitationId });
      const inv = pendingInvitations.find((i) => i.id === invitationId);
      if (inv && typeof (inv as unknown as { accept?: () => Promise<void> }).accept === "function") {
        await (inv as unknown as { accept: () => Promise<void> }).accept();
      }
      // Don't redirect or mark onboarded here — the useEffect at the top
      // watches userMemberships and handles setActive + onboarded + redirect
      // once Clerk propagates the membership. This avoids racing with Clerk's
      // eventual consistency.
      await userInvitations?.revalidate?.();
      await userMemberships?.revalidate?.();
    } catch (err) {
      console.error("Failed to accept invitation:", err);
      setAcceptingId(null);
    }
  }

  async function handlePersonal() {
    setLoading(true);
    posthog?.capture("workspace_type_selected", { type: "personal" });
    try {
      // Mark onboarding complete and sync user
      await user?.update({ unsafeMetadata: { onboarded: true } });
      await api.syncUser();
      router.push("/chat");
    } catch {
      setLoading(false);
    }
  }

  if (mode === "invitations") {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-6 bg-background">
        <div className="text-center mb-4">
          <Mail className="h-10 w-10 mx-auto mb-3 text-primary" />
          <h1 className="text-2xl font-bold">You have been invited</h1>
          <p className="text-muted-foreground mt-2">
            Accept an invitation to join an organization on Isol8.
          </p>
        </div>

        <div className="flex flex-col gap-3 w-full max-w-md px-4">
          {pendingInvitations.map((invitation) => (
            <div
              key={invitation.id}
              className="flex items-center justify-between p-4 rounded-lg border border-border bg-card"
            >
              <div className="flex items-center gap-3">
                <Users className="h-5 w-5 text-muted-foreground" />
                <div>
                  <div className="font-medium">
                    {(invitation as unknown as { publicOrganizationData?: { name?: string } }).publicOrganizationData?.name || "Organization"}
                  </div>
                  <div className="text-sm text-muted-foreground">Pending invitation</div>
                </div>
              </div>
              <Button
                onClick={() => handleAcceptInvitation(invitation.id)}
                disabled={acceptingId !== null}
                size="sm"
              >
                {acceptingId === invitation.id ? "Accepting..." : "Accept"}
              </Button>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (mode === "org") {
    // Two-stage gate after Clerk's <CreateOrganization> finishes:
    //
    //   Stage A: `organization` is non-null but the JWT hasn't picked up
    //   the new org yet (Clerk's setActive → JWT refresh is async). Show
    //   a transient "Activating…" message so the user knows we're working
    //   on it. Without this gate, the first invite POST hits Gate A's
    //   auth.org_id == org_id check on the backend with a pre-org JWT and
    //   returns 403 "Cannot invite to a different org" — flaky right
    //   after org creation.
    //
    //   Stage B: JWT now carries the new org. Mount InviteTeammatesStep
    //   so all invites flow through our backend's Gate A (rejecting
    //   personal-subscriber emails) instead of Clerk's built-in invite
    //   UI which calls Clerk directly.
    if (organization && authOrgId === organization.id) {
      return (
        <InviteTeammatesStep
          orgId={organization.id}
          onComplete={async () => {
            try {
              await user?.update({ unsafeMetadata: { onboarded: true } });
            } catch {
              // best-effort; ChatLayout's auto-activate fallback covers this
            }
            router.push("/chat");
          }}
        />
      );
    }
    if (organization && authOrgId !== organization.id) {
      return (
        <div className="flex flex-col items-center justify-center min-h-screen gap-4 bg-background">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground/20 border-t-primary" />
          <p className="text-sm text-muted-foreground">Activating your organization…</p>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-6 bg-background">
        <div className="text-center mb-4">
          <h1 className="text-2xl font-bold">Create your organization</h1>
          <p className="text-muted-foreground mt-2">
            Your team will share agents, workspace, and billing.
          </p>
        </div>
        <CreateOrganization
          // skipInvitationScreen={true} → Clerk creates the org and stops.
          // <InviteTeammatesStep> takes over above (rendered when
          // `organization` resolves) so all invites route through our
          // backend's Gate A.
          afterCreateOrganizationUrl="/onboarding"
          skipInvitationScreen={true}
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
          onClick={() => { posthog?.capture("workspace_type_selected", { type: "org" }); setMode("org"); }}
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
