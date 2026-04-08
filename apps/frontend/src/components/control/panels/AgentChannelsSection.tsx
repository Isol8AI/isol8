"use client";

import { useState } from "react";
import useSWR from "swr";
import { Plus, Trash2, CheckCircle2, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";
import { BotSetupWizard } from "@/components/channels/BotSetupWizard";

type Provider = "telegram" | "discord" | "slack";

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

const PROVIDERS: Provider[] = ["telegram", "discord", "slack"];
const PROVIDER_LABELS: Record<Provider, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
};

export function AgentChannelsSection({ agentId }: AgentChannelsSectionProps) {
  const api = useApi();
  const { data, mutate } = useSWR<LinksMeResponse>(
    "/channels/links/me",
    () => api.get("/channels/links/me") as Promise<LinksMeResponse>,
  );
  const [wizardFor, setWizardFor] = useState<Provider | null>(null);

  if (!data) {
    return <div className="p-4 text-sm text-[#8a8578]">Loading channels…</div>;
  }

  const handleDelete = async (provider: Provider) => {
    if (
      !confirm(
        `Delete the ${PROVIDER_LABELS[provider]} bot for this agent? This cannot be undone.`,
      )
    ) {
      return;
    }
    await api.del(`/channels/${provider}/${agentId}`);
    mutate();
  };

  return (
    <div className="space-y-4 p-4">
      <h3 className="text-sm font-semibold">Channels</h3>
      {PROVIDERS.map((provider) => {
        const bots = data[provider].filter((b) => b.agent_id === agentId);
        return (
          <div key={provider} className="rounded-md border border-[#e0dbd0] p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-[#8a8578]">
                {PROVIDER_LABELS[provider]}
              </span>
            </div>
            {bots.length === 0 ? (
              <p className="text-xs text-[#8a8578]">No bot configured</p>
            ) : (
              bots.map((bot) => (
                <div key={bot.agent_id} className="flex items-center gap-2 text-sm">
                  {bot.linked ? (
                    <CheckCircle2 className="h-4 w-4 text-[#2d8a4e]" />
                  ) : (
                    <AlertCircle className="h-4 w-4 text-amber-500" />
                  )}
                  <span className="font-mono">@{bot.bot_username}</span>
                  <div className="flex-1" />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDelete(provider)}
                    aria-label={`Delete ${provider} bot`}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              ))
            )}
            {data.can_create_bots && bots.length === 0 && (
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => setWizardFor(provider)}
              >
                <Plus className="h-3 w-3 mr-1" />
                Add {PROVIDER_LABELS[provider]} bot
              </Button>
            )}
          </div>
        );
      })}

      {wizardFor && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl">
            <BotSetupWizard
              mode="create"
              provider={wizardFor}
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
    </div>
  );
}
