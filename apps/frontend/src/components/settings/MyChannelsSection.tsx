"use client";

import { useState } from "react";
import useSWR from "swr";
import { CheckCircle2, AlertCircle } from "lucide-react";

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

const PROVIDERS: Provider[] = ["telegram", "discord", "slack"];
const PROVIDER_LABELS: Record<Provider, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
};

export function MyChannelsSection() {
  const api = useApi();
  const { data, mutate } = useSWR<LinksMeResponse>(
    "/channels/links/me",
    () => api.get("/channels/links/me") as Promise<LinksMeResponse>,
  );
  const [wizard, setWizard] = useState<{ provider: Provider; agentId: string } | null>(null);

  if (!data) {
    return <div className="p-4 text-sm text-[#8a8578]">Loading…</div>;
  }

  const handleUnlink = async (provider: Provider, agentId: string) => {
    if (!confirm(`Unlink your ${PROVIDER_LABELS[provider]} from this bot?`)) return;
    await api.del(`/channels/link/${provider}/${agentId}`);
    mutate();
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">My Channels</h2>
        <p className="text-xs text-[#8a8578]">
          Link your Telegram, Discord, and Slack identities to your organization&apos;s bots.
        </p>
      </div>

      {PROVIDERS.map((provider) => {
        const bots = data[provider];
        return (
          <div key={provider} className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-[#8a8578]">
              {PROVIDER_LABELS[provider]}
            </h3>
            {bots.length === 0 ? (
              <div className="rounded-md border border-[#e0dbd0] p-3 text-xs text-[#8a8578]">
                No {PROVIDER_LABELS[provider]} bots set up in this container.
                {data.can_create_bots && " Set one up from your agent's Channels tab."}
              </div>
            ) : (
              <div className="space-y-2">
                {bots.map((bot) => (
                  <div
                    key={bot.agent_id}
                    className="flex items-center gap-3 rounded-md border border-[#e0dbd0] p-3"
                  >
                    {bot.linked ? (
                      <CheckCircle2 className="h-4 w-4 text-[#2d8a4e]" />
                    ) : (
                      <AlertCircle className="h-4 w-4 text-amber-500" />
                    )}
                    <div className="flex-1">
                      <p className="text-sm font-mono">@{bot.bot_username}</p>
                      <p className="text-xs text-[#8a8578]">{bot.agent_id} agent</p>
                    </div>
                    {bot.linked ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleUnlink(provider, bot.agent_id)}
                      >
                        Unlink
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => setWizard({ provider, agentId: bot.agent_id })}
                      >
                        Link
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {wizard && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl">
            <BotSetupWizard
              mode="link-only"
              provider={wizard.provider}
              agentId={wizard.agentId}
              onComplete={() => {
                setWizard(null);
                mutate();
              }}
              onCancel={() => setWizard(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
