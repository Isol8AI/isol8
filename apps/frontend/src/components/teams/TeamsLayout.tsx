"use client";

import { useTeamsWorkspaceStatus } from "@/hooks/useTeamsApi";
import { TeamsSidebar } from "./TeamsSidebar";

export function TeamsLayout({ children }: { children: React.ReactNode }) {
  const status = useTeamsWorkspaceStatus();

  return (
    <div className="flex h-screen overflow-hidden">
      <TeamsSidebar />
      <main className="flex-1 overflow-auto">
        {status.kind === "provisioning" ? (
          <ProvisioningOverlay />
        ) : status.kind === "subscribe_required" ? (
          <SubscribeOverlay />
        ) : status.kind === "error" ? (
          <ErrorOverlay error={status.error} />
        ) : (
          children
        )}
      </main>
    </div>
  );
}

function ProvisioningOverlay() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold mb-2">Setting up your Teams workspace…</h1>
      <p className="text-zinc-600">
        This usually takes about 30 seconds. The page will refresh automatically.
      </p>
    </div>
  );
}

function SubscribeOverlay() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold mb-2">Subscribe to enable Teams</h1>
      <p className="text-zinc-600">
        Teams runs on top of your agent container. Start a subscription from the chat
        page first, then come back.
      </p>
    </div>
  );
}

function ErrorOverlay({ error }: { error: Error }) {
  return (
    <div className="p-8 text-red-600">Error: {String(error.message ?? error)}</div>
  );
}
