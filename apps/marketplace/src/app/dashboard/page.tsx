"use client";
import { useAuth } from "@clerk/nextjs";
import useSWR from "swr";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";

export default function Dashboard() {
  const { getToken } = useAuth();
  const { data } = useSWR(
    `${API}/api/v1/marketplace/payouts/dashboard`,
    async (url) => {
      const jwt = await getToken();
      const resp = await fetch(url, { headers: { Authorization: `Bearer ${jwt}` } });
      if (!resp.ok) return null;
      return resp.json();
    }
  );
  if (!data) return <p className="p-8">Loading…</p>;
  return (
    <main className="max-w-3xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold mb-8">Creator dashboard</h1>
      <div className="grid grid-cols-2 gap-4 mb-8">
        <Stat label="Held balance" value={`$${((data.balance_held_cents ?? 0) / 100).toFixed(2)}`} />
        <Stat
          label="Lifetime earned"
          value={`$${((data.lifetime_earned_cents ?? 0) / 100).toFixed(2)}`}
        />
      </div>
      {data.dashboard_url ? (
        <a href={data.dashboard_url} className="text-zinc-100 underline">
          Open Stripe dashboard →
        </a>
      ) : (
        <a
          href={`${API}/api/v1/marketplace/payouts/onboard`}
          className="px-4 py-2 bg-zinc-100 text-zinc-950 rounded"
        >
          Onboard for payouts
        </a>
      )}
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 p-4">
      <p className="text-sm text-zinc-400">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
    </div>
  );
}
