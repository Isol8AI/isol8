import Link from "next/link";

export function Tabs({ current }: { current: "agents" | "skills" }) {
  return (
    <div className="flex gap-6 border-b border-zinc-800 mb-8">
      <Link
        href="/agents"
        className={`pb-3 ${current === "agents" ? "border-b-2 border-zinc-100 font-semibold" : "text-zinc-400"}`}
      >
        Agents
      </Link>
      <Link
        href="/skills"
        className={`pb-3 ${current === "skills" ? "border-b-2 border-zinc-100 font-semibold" : "text-zinc-400"}`}
      >
        Skills
      </Link>
    </div>
  );
}
