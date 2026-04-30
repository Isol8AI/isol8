"use client";
import { useState } from "react";
import { useAuth } from "@clerk/nextjs";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";

export default function Sell() {
  const { getToken } = useAuth();
  const [form, setForm] = useState({
    slug: "",
    name: "",
    description_md: "",
    format: "openclaw" as "openclaw" | "skillmd",
    delivery_method: "cli" as "cli" | "mcp" | "both",
    price_cents: 0,
    tags: "",
  });
  const [status, setStatus] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("uploading…");
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
      setStatus(`Draft saved: ${body.slug}`);
    } else {
      const text = await resp.text();
      setStatus(`Error: ${resp.status} — ${text.slice(0, 120)}`);
    }
  }

  return (
    <main className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold mb-6">Publish a listing</h1>
      <form onSubmit={submit} className="space-y-4">
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
              setForm({ ...form, format: e.target.value as "openclaw" | "skillmd" })
            }
          >
            <option value="openclaw">Agent (OpenClaw)</option>
            <option value="skillmd">Skill (SKILL.md)</option>
          </select>
          <select
            className="bg-zinc-900 px-3 py-2 rounded"
            value={form.delivery_method}
            onChange={(e) =>
              setForm({ ...form, delivery_method: e.target.value as "cli" | "mcp" | "both" })
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
            onChange={(e) => setForm({ ...form, price_cents: Number(e.target.value) })}
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
        <button
          className="px-6 py-2 bg-zinc-100 text-zinc-950 rounded font-semibold"
          type="submit"
        >
          Save draft
        </button>
        {status && <p className="text-sm text-zinc-400">{status}</p>}
      </form>
    </main>
  );
}
