"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Plus, Trash2, CheckCircle2, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useApi } from "@/lib/api";
import { type Provider, PROVIDERS, PROVIDER_LABELS, formatBotHandle } from "@/lib/channels";
import { BotSetupWizard } from "@/components/channels/BotSetupWizard";
import { RestartForChannelsDialog } from "@/components/channels/RestartForChannelsDialog";
import { useBilling } from "@/hooks/useBilling";
import { useContainerStatus } from "@/hooks/useContainerStatus";

interface BotEntry {
  agent_id: string;
  bot_username: string;
  linked: boolean;
}

interface LinksMeResponse {
  telegram: BotEntry[];
  discord: BotEntry[];
  slack: BotEntry[];
  can_create_bots: boolean;
}

interface AgentChannelsSectionProps {
  agentId: string;
}

export function AgentChannelsSection({ agentId }: AgentChannelsSectionProps) {
  const api = useApi();
  const { isSubscribed } = useBilling();
  const { container } = useContainerStatus();
  // Defaults to true (i.e. don't gate) when the field is missing — old
  // backends without the field shouldn't see new dialogs they can't act on.
  const channelsAtBoot = container?.channels_at_boot !== false;
  const { data, mutate } = useSWR<LinksMeResponse>(
    "/channels/links/me",
    () => api.get("/channels/links/me") as Promise<LinksMeResponse>,
  );
  const [wizardFor, setWizardFor] = useState<{ provider: Provider; mode: "create" | "link-only" } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Provider | null>(null);
  const [deleting, setDeleting] = useState(false);
  // When channelsAtBoot=false and the user clicks a channel-action button,
  // we stash the intent and pop the restart dialog instead of opening the
  // wizard. Cleared when the user cancels.
  const [restartDialogOpen, setRestartDialogOpen] = useState(false);

  // Gate channel-creating / linking actions on whether channels are loaded
  // in the container. If not, intercept with the restart dialog rather
  // than letting the wizard's RPC calls fail.
  const tryOpenWizard = (intent: { provider: Provider; mode: "create" | "link-only" }) => {
    if (!channelsAtBoot) {
      setRestartDialogOpen(true);
      return;
    }
    setWizardFor(intent);
  };

  useEffect(() => {
    if (!wizardFor && !deleteTarget) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setWizardFor(null);
        setDeleteTarget(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [wizardFor, deleteTarget]);

  if (!data) {
    return <div className="p-4 text-sm text-[#8a8578]">Loading channels…</div>;
  }

  const performDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.del(`/channels/${deleteTarget}/${agentId}`);
      setDeleteTarget(null);
      await mutate();
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-4 p-4">
      <h3 className="text-sm font-semibold">Channels</h3>
      {/* Container-wide channels-off banner — same guardrail as the
          settings page. Without this the user clicks Add bot, the dialog
          opens, they back out, and never realize *every* channel button
          on this panel is gated by the same restart. */}
      {!channelsAtBoot && isSubscribed && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 flex items-start gap-2">
          <AlertCircle className="h-4 w-4 text-amber-600 mt-0.5 flex-shrink-0" />
          <div className="flex-1 text-xs text-amber-900">
            <p className="font-medium mb-1">Channels are turned off</p>
            <p className="leading-relaxed mb-2">
              Enable them to add bots — restarts your container (~6 min).
            </p>
            <Button size="sm" onClick={() => setRestartDialogOpen(true)}>
              Enable channels
            </Button>
          </div>
        </div>
      )}
      {PROVIDERS.map((provider) => {
        const bots = data[provider].filter((b) => b.agent_id === agentId);
        return (
          <div key={provider} className="rounded-md border border-[#e0dbd0] p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-[#8a8578]">
                {PROVIDER_LABELS[provider]}
              </span>
            </div>
            {!isSubscribed ? (
              <p className="text-xs text-[#8a8578]">
                Channels require an active subscription. Sign up to connect {PROVIDER_LABELS[provider]}.
              </p>
            ) : bots.length === 0 ? (
              <p className="text-xs text-[#8a8578]">No bot configured</p>
            ) : (
              bots.map((bot) => (
                <div key={bot.agent_id} className="flex items-center gap-2 text-sm">
                  {bot.linked ? (
                    <CheckCircle2 className="h-4 w-4 text-[#2d8a4e]" />
                  ) : (
                    <AlertCircle className="h-4 w-4 text-amber-500" />
                  )}
                  <span className="font-mono">{formatBotHandle(provider, bot.bot_username)}</span>
                  <div className="flex-1" />
                  {!bot.linked && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => tryOpenWizard({ provider, mode: "link-only" })}
                      aria-label={`Link your ${PROVIDER_LABELS[provider]} to ${bot.bot_username}`}
                    >
                      Link
                    </Button>
                  )}
                  {data.can_create_bots && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setDeleteTarget(provider)}
                      aria-label={`Delete ${provider} bot`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              ))
            )}
            {isSubscribed && data.can_create_bots && bots.length === 0 && (
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => tryOpenWizard({ provider, mode: "create" })}
              >
                <Plus className="h-3 w-3 mr-1" />
                Add {PROVIDER_LABELS[provider]} bot
              </Button>
            )}
          </div>
        );
      })}

      {wizardFor && (
        <div
          className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
          role="dialog"
          aria-modal="true"
          onClick={() => setWizardFor(null)}
        >
          <div
            className="bg-white rounded-lg shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <BotSetupWizard
              mode={wizardFor.mode}
              provider={wizardFor.provider}
              agentId={agentId}
              onComplete={() => {
                setWizardFor(null);
                mutate();
              }}
              onCancel={() => setWizardFor(null)}
            />
          </div>
        </div>
      )}

      <RestartForChannelsDialog
        open={restartDialogOpen}
        onOpenChange={setRestartDialogOpen}
        onConfirmed={() => {
          // The user will navigate back to /chat (which mounts the
          // ProvisioningStepper) automatically once the container
          // regresses out of "ready" — they don't need a destination
          // here. SWR will pick up channels_at_boot=true on the next
          // status poll, so re-clicking "Add bot" after the restart
          // will skip this dialog and open the wizard directly.
        }}
      />
      <AlertDialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this bot?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget && (
                <>
                  This removes the {PROVIDER_LABELS[deleteTarget]} bot from the
                  <span className="font-mono"> {agentId} </span>
                  agent and unlinks every member who paired with it. This cannot be undone.
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={performDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete bot"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
