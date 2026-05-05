"use client";

import { useOrganization, useUser } from "@clerk/nextjs";

import { InboxPage } from "@/components/teams/inbox/InboxPage";

/**
 * Teams Inbox panel — thin shim that resolves Clerk identity (companyId =
 * organization id when present, else the user id; currentUserId = the signed-in
 * Clerk user) and delegates rendering to <InboxPage />. The Teams BFF resolves
 * the actual workspace/owner from the Clerk JWT, so these ids are used purely
 * client-side for localStorage namespacing + the assignee-filter "Assigned to
 * me" preset.
 *
 * While Clerk is loading, render nothing — TeamsLayout already shows a global
 * loading state for `useTeamsWorkspaceStatus.kind === "loading"`, so the brief
 * gap here is invisible to users.
 */
export function InboxPanel() {
  const { organization, isLoaded: orgLoaded } = useOrganization();
  const { user, isLoaded: userLoaded } = useUser();

  if (!orgLoaded || !userLoaded || !user) return null;

  // Owner-id convention: org membership uses the org id, personal accounts
  // use the user id. Matches how the BFF keys per-owner workspaces.
  const companyId = organization?.id ?? user.id;
  const currentUserId = user.id;

  return <InboxPage companyId={companyId} currentUserId={currentUserId} />;
}
