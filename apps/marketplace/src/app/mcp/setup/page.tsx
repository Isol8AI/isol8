import Link from "next/link";

export const metadata = {
  title: "MCP server — coming in v1.1 | marketplace.isol8.co",
  description:
    "Live MCP server is on the v1.1 roadmap. Install marketplace skills today via the npx CLI.",
};

export default function McpSetup() {
  return (
    <main className="max-w-3xl mx-auto px-6 py-12">
      <h1 className="text-4xl font-bold mb-6">MCP server — coming in v1.1</h1>

      <p className="text-zinc-300 mb-6">
        We&apos;re building a hosted MCP server so you can connect Claude Desktop,
        Cursor, or any MCP-supporting client to a purchased SKILL.md skill and run
        it live on Isol8&apos;s infrastructure. That feature ships in <strong>v1.1</strong>.
      </p>

      <p className="text-zinc-300 mb-10">
        For now, every marketplace skill installs directly into your AI tool with a
        single command — no MCP server required.
      </p>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-3">Use the CLI installer</h2>
        <pre className="bg-zinc-900 px-4 py-3 rounded overflow-x-auto text-sm">
          <code>npx @isol8/marketplace install &lt;listing-slug&gt;</code>
        </pre>
        <p className="text-zinc-400 text-sm mt-3">
          Auto-detects Claude Desktop, Cursor, OpenClaw, and Copilot CLI; drops
          the skill into the right directory for each. Paid listings prompt for a
          one-time browser sign-in to confirm your license.
        </p>
      </section>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-3">License keys</h2>
        <p className="text-zinc-300">
          After purchase, your license key shows up in your{" "}
          <Link href="/buyer" className="text-zinc-100 underline">
            purchase history
          </Link>
          . Keys are formatted <code>iml_</code> followed by 32 base32 characters.
        </p>
      </section>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-3">v1 limits worth knowing</h2>
        <ul className="list-disc pl-6 text-zinc-300 space-y-1">
          <li>Install rate limit: 10 unique source IPs per 24h per license key.</li>
          <li>OpenClaw agents are CLI-install only. SKILL.md skills will gain MCP support in v1.1.</li>
          <li>Stripe Connect (seller payouts) is US-only in v1.</li>
        </ul>
      </section>

      <p className="text-sm text-zinc-500">
        Trouble? Email <a className="underline" href="mailto:support@isol8.co">support@isol8.co</a>.
      </p>
    </main>
  );
}
