"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { useApi } from "@/lib/api";
import { useChatGPTOAuth } from "@/hooks/useChatGPTOAuth";
import { OpenAIIcon, AnthropicIcon } from "@/components/chat/ProviderIcons";
import { Input } from "@/components/ui/input";

type ProviderChoice = "chatgpt_oauth" | "byo_key" | "bedrock_claude";
type ByoProvider = "openai" | "anthropic";

type UserData = {
  provider_choice?: ProviderChoice | null;
  byo_provider?: ByoProvider | null;
};

const HERO_TILE = "h-12 w-12 rounded-lg bg-[#f3efe6] flex items-center justify-center flex-shrink-0";
const ACTION_CARD = "rounded-lg border border-[#e0dbd0] bg-white p-4 space-y-3";
const EYEBROW = "text-[10px] uppercase tracking-wider text-[#8a8578]/60";

function StatusChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-[#06402B]/10 text-[#06402B] px-2 py-0.5 text-xs font-medium">
      <span className="h-1.5 w-1.5 rounded-full bg-[#06402B]" />
      {label}
    </span>
  );
}

function HeroCard({
  icon,
  title,
  subtitle,
  status,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  status: string;
}) {
  return (
    <div className="rounded-xl border border-[#e0dbd0] bg-white p-6 flex items-center gap-4">
      <div className={HERO_TILE}>{icon}</div>
      <div className="flex-1 min-w-0">
        <h3 className="font-medium text-[#1a1a1a]">{title}</h3>
        <p className="text-sm text-[#8a8578] truncate">{subtitle}</p>
      </div>
      <StatusChip label={status} />
    </div>
  );
}

function ChatGPTOAuthBlock({ onDisconnected }: { onDisconnected: () => void }) {
  const { disconnect } = useChatGPTOAuth();
  const [busy, setBusy] = useState(false);

  const handleDisconnect = async () => {
    setBusy(true);
    try {
      await disconnect();
      onDisconnected();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <HeroCard
        icon={<OpenAIIcon size={32} />}
        title="Sign in with ChatGPT"
        subtitle="Inference via your ChatGPT account"
        status="Connected"
      />
      <div className={ACTION_CARD}>
        <span className={EYEBROW}>Account</span>
        <p className="text-sm text-[#1a1a1a]">Connected via OAuth</p>
        <button
          onClick={handleDisconnect}
          disabled={busy}
          className="rounded-md border border-[#e0dbd0] text-[#1a1a1a] hover:bg-[#f3efe6] px-3 py-1.5 text-sm disabled:opacity-50"
        >
          {busy ? "Disconnecting…" : "Disconnect"}
        </button>
      </div>
    </>
  );
}

function ByoKeyBlock({
  byoProvider,
  onReplaced,
}: {
  byoProvider: ByoProvider;
  onReplaced: () => void;
}) {
  const isOpenAI = byoProvider === "openai";
  const title = isOpenAI ? "Bring your own OpenAI key" : "Bring your own Anthropic key";
  const icon = isOpenAI ? <OpenAIIcon size={32} /> : <AnthropicIcon size={32} />;

  return (
    <>
      <HeroCard
        icon={icon}
        title={title}
        subtitle="Your key, your billing"
        status="Active"
      />
      <div className={ACTION_CARD}>
        <span className={EYEBROW}>API key</span>
        <p className="text-xs text-[#8a8578]">
          Stored encrypted in AWS Secrets Manager. Paste a new key to rotate.
        </p>
        <ReplaceKeyForm currentProvider={byoProvider} onReplaced={onReplaced} />
      </div>
    </>
  );
}

function BedrockBlock({ onManageCredits }: { onManageCredits: () => void }) {
  return (
    <>
      <HeroCard
        icon={<AnthropicIcon size={32} />}
        title="Powered by Claude"
        subtitle="Anthropic Claude via AWS Bedrock"
        status="Active"
      />
      <div className={ACTION_CARD}>
        <span className={EYEBROW}>Billing</span>
        <p className="text-sm text-[#1a1a1a]">
          Manage your Claude credits and auto-reload settings.
        </p>
        <button
          onClick={onManageCredits}
          className="rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white px-4 py-2 text-sm"
        >
          Manage credits →
        </button>
      </div>
    </>
  );
}

function EmptyStateCard({ message }: { message?: string }) {
  return (
    <div className={ACTION_CARD}>
      <p className="text-sm text-[#1a1a1a]">
        {message ?? "You haven’t picked a provider yet."}
      </p>
      <Link
        href="/onboarding"
        className="inline-flex rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white px-4 py-2 text-sm"
      >
        Re-onboard →
      </Link>
    </div>
  );
}

interface LLMPanelProps {
  onPanelChange?: (panel: string) => void;
}

export function LLMPanel({ onPanelChange }: LLMPanelProps) {
  const api = useApi();
  const { data: user, mutate } = useSWR<UserData | null>(
    "/users/me",
    (p: string) => api.get(p) as Promise<UserData | null>,
  );

  if (!user) return <div className="p-6 text-sm">Loading…</div>;

  const handleManageCredits = () => {
    if (onPanelChange) onPanelChange("credits");
    else if (typeof window !== "undefined") window.location.href = "/chat?panel=credits";
  };

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold">LLM Provider</h2>

      {user.provider_choice === "chatgpt_oauth" && (
        <ChatGPTOAuthBlock onDisconnected={() => mutate()} />
      )}

      {user.provider_choice === "byo_key" && user.byo_provider && (
        <ByoKeyBlock byoProvider={user.byo_provider} onReplaced={() => mutate()} />
      )}

      {/* byo_key without byo_provider — webhook persisted provider_choice but
          backend never wrote byo_provider (see backend memory). Without this
          recovery state the panel renders blank for the affected user. */}
      {user.provider_choice === "byo_key" && !user.byo_provider && (
        <EmptyStateCard message="Your bring-your-own-key configuration is incomplete. Re-onboard to finish setting up." />
      )}

      {user.provider_choice === "bedrock_claude" && (
        <BedrockBlock onManageCredits={handleManageCredits} />
      )}

      {!user.provider_choice && <EmptyStateCard />}
    </div>
  );
}

function ReplaceKeyForm({
  currentProvider,
  onReplaced,
}: {
  currentProvider: ByoProvider;
  onReplaced: () => void;
}) {
  const api = useApi();
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.put(`/settings/keys/${currentProvider}`, { api_key: apiKey });
      setApiKey("");
      onReplaced();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save key");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <form onSubmit={submit} className="flex gap-2">
        <Input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={currentProvider === "openai" ? "sk-proj-…" : "sk-ant-…"}
          className="flex-1 font-mono text-sm"
        />
        <button
          type="submit"
          disabled={submitting || !apiKey}
          className="rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white px-4 py-2 text-sm disabled:opacity-50"
        >
          Save
        </button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
