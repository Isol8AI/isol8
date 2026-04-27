"use client";

import { useState } from "react";
import useSWR from "swr";
import { useApi } from "@/lib/api";
import { useChatGPTOAuth } from "@/hooks/useChatGPTOAuth";

// NOTE: this panel reads the user's persisted provider_choice from
// GET /users/me. That endpoint does not yet exist in the backend
// (only POST /users/sync, which doesn't echo back provider_choice).
// Until the GET is wired up, the SWR fetch will 404 and the panel
// will sit on the "Loading…" placeholder. This is intentional — the
// rest of Plan 3 Task 13 is in place; the missing endpoint is a
// known follow-up.
type UserData = {
  provider_choice?: "chatgpt_oauth" | "byo_key" | "bedrock_claude";
  byo_provider?: "openai" | "anthropic";
};

export function LLMPanel() {
  const api = useApi();
  const { data: user, mutate } = useSWR<UserData | null>(
    "/users/me",
    (p: string) => api.get(p) as Promise<UserData | null>,
  );
  const { disconnect } = useChatGPTOAuth();

  const onDisconnectOAuth = async () => {
    await disconnect();
    await mutate();
  };

  if (!user) return <div className="p-6 text-sm">Loading…</div>;

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-xl font-semibold">LLM Provider</h2>

      {user.provider_choice === "chatgpt_oauth" && (
        <section className="space-y-3">
          <div className="text-sm">
            <strong>Sign in with ChatGPT</strong> · Connected
          </div>
          <button
            onClick={onDisconnectOAuth}
            className="rounded-md bg-secondary px-3 py-1.5 text-sm"
          >
            Disconnect
          </button>
        </section>
      )}

      {user.provider_choice === "byo_key" && (
        <section className="space-y-3">
          <div className="text-sm">
            <strong>Bring your own key</strong> ·{" "}
            {user.byo_provider === "openai" ? "OpenAI" : "Anthropic"}
          </div>
          <p className="text-xs text-muted-foreground">
            Your key is stored encrypted in AWS Secrets Manager. To rotate
            it, paste a new key below.
          </p>
          {user.byo_provider && (
            <ReplaceKeyForm
              currentProvider={user.byo_provider}
              onReplaced={() => mutate()}
            />
          )}
        </section>
      )}

      {user.provider_choice === "bedrock_claude" && (
        <section className="space-y-3">
          <div className="text-sm">
            <strong>Powered by Claude</strong> · We provide the LLM
          </div>
          <p className="text-xs text-muted-foreground">
            Manage credits in the Credits panel.
          </p>
        </section>
      )}

      {!user.provider_choice && (
        <p className="text-sm text-muted-foreground">
          No provider selected yet. Re-onboard to pick one.
        </p>
      )}
    </div>
  );
}

function ReplaceKeyForm({
  currentProvider,
  onReplaced,
}: {
  currentProvider: "openai" | "anthropic";
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
      // Surface the failure and let the user retry — without this catch,
      // submitting stayed true forever and the form was un-retryable.
      // Codex P2 on PR #393.
      setError(err instanceof Error ? err.message : "Couldn't save key");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <form onSubmit={submit} className="flex gap-2">
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={
            currentProvider === "openai" ? "sk-proj-…" : "sk-ant-…"
          }
          className="flex-1 rounded-md border border-input px-3 py-2 font-mono text-sm"
        />
        <button
          type="submit"
          disabled={submitting || !apiKey}
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
        >
          Save
        </button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
