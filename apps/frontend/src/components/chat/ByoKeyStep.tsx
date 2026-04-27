"use client";
import { useState } from "react";
import { useApi } from "@/lib/api";

type Provider = "openai" | "anthropic";
type Props = { onComplete: () => void };

export function ByoKeyStep({ onComplete }: Props) {
  const api = useApi();
  const [provider, setProvider] = useState<Provider>("openai");
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      // Backend route: PUT /settings/keys/{tool_id} with {api_key}
      // (See routers/settings_keys.py.)
      await api.put(`/settings/keys/${provider}`, { api_key: apiKey });
      onComplete();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save key");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-4 py-8 max-w-md mx-auto"
    >
      <h3 className="text-xl font-semibold">Bring your own API key</h3>
      <p className="text-sm text-muted-foreground">
        Use your own OpenAI or Anthropic account. We never see your key
        after you save it &mdash; it&apos;s stored encrypted in AWS Secrets
        Manager and injected into your container at runtime.
      </p>

      <fieldset className="flex gap-3">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="provider"
            value="openai"
            checked={provider === "openai"}
            onChange={() => setProvider("openai")}
          />
          <span>OpenAI</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="provider"
            value="anthropic"
            checked={provider === "anthropic"}
            onChange={() => setProvider("anthropic")}
          />
          <span>Anthropic</span>
        </label>
      </fieldset>

      <input
        type="password"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        placeholder={
          provider === "openai" ? "sk-proj-..." : "sk-ant-..."
        }
        required
        autoComplete="off"
        spellCheck={false}
        className="rounded-md border border-input bg-background px-3 py-2 font-mono text-sm"
      />

      {error && <p className="text-sm text-destructive">{error}</p>}

      <button
        type="submit"
        disabled={submitting || !apiKey}
        className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "Validating…" : "Save key"}
      </button>
    </form>
  );
}
