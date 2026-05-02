"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ZipUploader } from "@/components/Sell/ZipUploader";
import { AgentPicker } from "@/components/Sell/AgentPicker";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";

type Format = "openclaw" | "skillmd";
type Delivery = "cli" | "mcp" | "both";

interface Eligibility {
  tier: string;
  can_sell_skillmd: boolean;
  can_sell_openclaw: boolean;
  reason: string | null;
}

export default function Sell() {
  const { getToken } = useAuth();
  const [eligibility, setEligibility] = useState<Eligibility | null>(null);
  const [step, setStep] = useState<"metadata" | "artifact" | "submit">("metadata");
  const [listingId, setListingId] = useState<string | null>(null);
  const [submitStatus, setSubmitStatus] = useState<string | null>(null);

  const [form, setForm] = useState({
    slug: "",
    name: "",
    description_md: "",
    format: "skillmd" as Format,
    delivery_method: "cli" as Delivery,
    price_cents: 0,
    tags: "",
  });
  const [createStatus, setCreateStatus] = useState<string | null>(null);

  // Load eligibility on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const jwt = await getToken();
      if (!jwt || cancelled) return;
      const resp = await fetch(`${API}/api/v1/marketplace/seller-eligibility`, {
        headers: { Authorization: `Bearer ${jwt}` },
      });
      if (resp.ok && !cancelled) {
        setEligibility((await resp.json()) as Eligibility);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  // If user picked "Agent" but isn't paid, snap them back to skillmd.
  useEffect(() => {
    if (
      eligibility &&
      !eligibility.can_sell_openclaw &&
      form.format === "openclaw"
    ) {
      setForm((f) => ({ ...f, format: "skillmd", delivery_method: "cli" }));
    }
  }, [eligibility, form.format]);

  async function createDraft(e: React.FormEvent) {
    e.preventDefault();
    setCreateStatus("Creating draft…");
    const jwt = await getToken();
    const resp = await fetch(`${API}/api/v1/marketplace/listings`, {
      method: "POST",
      headers: { "content-type": "application/json", Authorization: `Bearer ${jwt}` },
      body: JSON.stringify({
        ...form,
        tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
      }),
    });
    if (resp.ok) {
      const body = await resp.json();
      setListingId(body.listing_id);
      setCreateStatus(`Draft saved: ${body.slug}`);
      setStep("artifact");
    } else {
      const text = await resp.text();
      setCreateStatus(`Error: ${resp.status} — ${text.slice(0, 200)}`);
    }
  }

  async function submitForReview() {
    if (!listingId) return;
    setSubmitStatus("Submitting…");
    const jwt = await getToken();
    const resp = await fetch(
      `${API}/api/v1/marketplace/listings/${encodeURIComponent(listingId)}/submit`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${jwt}` },
      },
    );
    if (resp.ok) {
      setSubmitStatus("Submitted! An admin will review your listing shortly.");
      setStep("submit");
    } else {
      const text = await resp.text();
      setSubmitStatus(`Submit failed (${resp.status}): ${text.slice(0, 200)}`);
    }
  }

  return (
    <main className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold mb-6">Publish a listing</h1>

      <Stepper step={step} />

      {step === "metadata" && (
        <form onSubmit={createDraft} className="space-y-4">
          <input
            className="w-full bg-zinc-900 px-4 py-2 rounded"
            placeholder="slug (lowercase-kebab)"
            value={form.slug}
            onChange={(e) => setForm({ ...form, slug: e.target.value })}
            required
          />
          <input
            className="w-full bg-zinc-900 px-4 py-2 rounded"
            placeholder="Name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
          <textarea
            className="w-full bg-zinc-900 px-4 py-2 rounded"
            rows={5}
            placeholder="Description (markdown)"
            value={form.description_md}
            onChange={(e) => setForm({ ...form, description_md: e.target.value })}
            required
          />
          <div className="flex gap-3">
            <select
              className="bg-zinc-900 px-3 py-2 rounded"
              value={form.format}
              onChange={(e) =>
                setForm({ ...form, format: e.target.value as Format })
              }
            >
              <option value="skillmd">Skill (SKILL.md)</option>
              <option
                value="openclaw"
                disabled={eligibility ? !eligibility.can_sell_openclaw : false}
              >
                Agent (OpenClaw)
                {eligibility && !eligibility.can_sell_openclaw ? " — paid only" : ""}
              </option>
            </select>
            <select
              className="bg-zinc-900 px-3 py-2 rounded"
              value={form.delivery_method}
              onChange={(e) =>
                setForm({ ...form, delivery_method: e.target.value as Delivery })
              }
            >
              <option value="cli">CLI install</option>
              <option value="mcp">MCP server (SKILL.md only)</option>
              <option value="both">Both</option>
            </select>
            <input
              className="bg-zinc-900 px-3 py-2 rounded w-32"
              type="number"
              placeholder="Price (¢)"
              value={form.price_cents}
              onChange={(e) =>
                setForm({ ...form, price_cents: Number(e.target.value) })
              }
              min={0}
              max={2000}
            />
          </div>
          <input
            className="w-full bg-zinc-900 px-4 py-2 rounded"
            placeholder="tags (comma-separated, max 5)"
            value={form.tags}
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
          />

          {eligibility && !eligibility.can_sell_openclaw && (
            <div className="rounded border border-amber-700/50 bg-amber-900/20 p-3 text-sm">
              <p className="text-amber-200">
                Publishing OpenClaw agents requires an Isol8 paid subscription.{" "}
                <Link href="https://isol8.co/pricing" className="underline">
                  See plans →
                </Link>
              </p>
              <p className="text-zinc-400 mt-1">
                You can still publish SKILL.md skills on any account.
              </p>
            </div>
          )}

          <button
            className="px-6 py-2 bg-zinc-100 text-zinc-950 rounded font-semibold"
            type="submit"
          >
            Save draft &amp; continue
          </button>
          {createStatus && <p className="text-sm text-zinc-400">{createStatus}</p>}
        </form>
      )}

      {step === "artifact" && listingId && (
        <div className="space-y-6">
          <p className="text-zinc-400 text-sm">
            Draft <code>{listingId}</code> created. Now upload the actual
            content.
          </p>
          {form.format === "skillmd" ? (
            <ZipUploader listingId={listingId} />
          ) : (
            <AgentPicker listingId={listingId} />
          )}
          <button
            type="button"
            onClick={submitForReview}
            className="px-6 py-2 bg-zinc-100 text-zinc-950 rounded font-semibold"
          >
            Submit for review
          </button>
          {submitStatus && <p className="text-sm text-zinc-300">{submitStatus}</p>}
        </div>
      )}

      {step === "submit" && (
        <div className="rounded border border-emerald-700/50 bg-emerald-900/20 p-4">
          <p className="text-emerald-200 font-medium">Listing submitted for review.</p>
          <p className="text-zinc-400 text-sm mt-2">
            We&apos;ll email you when it&apos;s approved or if anything needs changes.
          </p>
        </div>
      )}
    </main>
  );
}

function Stepper({ step }: { step: "metadata" | "artifact" | "submit" }) {
  const steps = [
    { id: "metadata", label: "1. Metadata" },
    { id: "artifact", label: "2. Upload content" },
    { id: "submit", label: "3. Submitted" },
  ] as const;
  return (
    <ol className="flex items-center gap-3 mb-8 text-sm">
      {steps.map((s) => (
        <li
          key={s.id}
          className={
            s.id === step
              ? "px-3 py-1 rounded bg-zinc-100 text-zinc-950 font-semibold"
              : "px-3 py-1 rounded bg-zinc-900 text-zinc-400"
          }
        >
          {s.label}
        </li>
      ))}
    </ol>
  );
}
