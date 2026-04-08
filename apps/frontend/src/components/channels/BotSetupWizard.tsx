"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";
import { useGatewayRpcMutation } from "@/hooks/useGatewayRpc";

type Provider = "telegram" | "discord" | "slack";
type Mode = "create" | "link-only";

export interface BotSetupWizardProps {
  mode: Mode;
  provider: Provider;
  agentId: string;
  onComplete: (result: { peer_id: string }) => void;
  onCancel: () => void;
}

type Step = "token" | "waiting" | "pair" | "done";

const PROVIDER_LABELS: Record<Provider, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
};

export function BotSetupWizard({
  mode,
  provider,
  agentId,
  onComplete,
  onCancel,
}: BotSetupWizardProps) {
  const api = useApi();
  const callRpc = useGatewayRpcMutation();

  const [step, setStep] = useState<Step>(mode === "create" ? "token" : "pair");
  const [token, setToken] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const label = PROVIDER_LABELS[provider];

  const handleTokenSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      const patch: Record<string, unknown> = {
        channels: {
          [provider]: {
            enabled: true,
            accounts: {
              [agentId]: {
                botToken: token.trim(),
                dmPolicy: "pairing",
              },
            },
          },
        },
      };
      await api.patchConfig(patch);
      setStep("waiting");
      // Poll channels.status until the account reports connected
      const deadline = Date.now() + 30_000;
      while (Date.now() < deadline) {
        try {
          const status = (await callRpc("channels.status", { probe: false })) as {
            channelAccounts?: Record<string, { connected?: boolean }[]>;
          };
          const accounts = status?.channelAccounts?.[provider] ?? [];
          if (accounts.some((a) => a.connected)) {
            setStep("pair");
            return;
          }
        } catch {
          // fall through to retry
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
      setError("Container took too long to start the bot. Check the agent's channel status.");
      setStep("token");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStep("token");
    } finally {
      setBusy(false);
    }
  };

  const handleCodeSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = (await api.post(`/channels/link/${provider}/complete`, {
        agent_id: agentId,
        code: code.trim(),
      })) as { status: string; peer_id: string };
      setStep("done");
      onComplete({ peer_id: result.peer_id });
    } catch (e) {
      const err = e as { status?: number; message?: string };
      if (err.status === 404) {
        setError("Code expired or not found. DM the bot again and try a new code.");
      } else if (err.status === 409) {
        setError("This account is already linked to another member.");
      } else {
        setError(err.message || String(e));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 space-y-4 max-w-md">
      <h3 className="text-lg font-semibold">
        {mode === "create" ? `Set up ${label} bot` : `Link your ${label} identity`}
      </h3>

      {step === "token" && (
        <div className="space-y-3">
          <label className="block text-sm font-medium">
            {label} bot token
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={provider === "telegram" ? "123456:ABC-DEF..." : "token..."}
              className="mt-1 w-full rounded-md border border-[#e0dbd0] bg-white px-3 py-2 text-sm font-mono"
              aria-label={`${label} bot token`}
            />
          </label>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex gap-2">
            <Button variant="outline" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={handleTokenSubmit} disabled={busy || !token.trim()}>
              {busy && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
              Next
            </Button>
          </div>
        </div>
      )}

      {step === "waiting" && (
        <div className="flex items-center gap-2 text-sm text-[#8a8578]">
          <Loader2 className="h-4 w-4 animate-spin" />
          Starting your bot...
        </div>
      )}

      {step === "pair" && (
        <div className="space-y-3">
          <p className="text-sm">
            DM your {label} bot from your phone. It will reply with an 8-character code.
            Paste it below within 1 hour.
          </p>
          <label className="block text-sm font-medium">
            Pairing code
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="ABC12345"
              className="mt-1 w-full rounded-md border border-[#e0dbd0] bg-white px-3 py-2 text-sm font-mono"
              aria-label="Pairing code"
            />
          </label>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex gap-2">
            <Button variant="outline" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={handleCodeSubmit} disabled={busy || code.length < 4}>
              {busy && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
              Link
            </Button>
          </div>
        </div>
      )}

      {step === "done" && (
        <p className="text-sm text-[#2d8a4e]">Linked.</p>
      )}
    </div>
  );
}
