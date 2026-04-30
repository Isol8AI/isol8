import Link from "next/link";

export const metadata = {
  title: "Connect MCP — marketplace.isol8.co",
  description: "Wire purchased SKILL.md skills into Claude Desktop, Cursor, or any MCP-supporting client.",
};

export default function McpSetup() {
  const claudeDesktopConfig = JSON.stringify(
    {
      mcpServers: {
        "isol8-marketplace": {
          url: "https://marketplace.isol8.co/mcp/<your-listing-id>/sse",
          transport: "sse",
          headers: { Authorization: "Bearer iml_<your-license-key>" },
        },
      },
    },
    null,
    2,
  );

  return (
    <main className="max-w-3xl mx-auto px-6 py-12">
      <h1 className="text-4xl font-bold mb-6">Connect MCP to your AI client</h1>

      <p className="text-zinc-300 mb-8">
        Once you&apos;ve purchased a SKILL.md skill, you can serve it via MCP to any client
        that supports the Model Context Protocol — Claude Desktop, Cursor with MCP, Codex CLI.
      </p>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-3">Claude Desktop</h2>
        <p className="text-zinc-400 mb-3 text-sm">
          Add to <code>~/Library/Application Support/Claude/claude_desktop_config.json</code> on macOS,
          or <code>%APPDATA%\Claude\claude_desktop_config.json</code> on Windows:
        </p>
        <pre className="bg-zinc-900 px-4 py-3 rounded overflow-x-auto text-sm">
          <code>{claudeDesktopConfig}</code>
        </pre>
      </section>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-3">Cursor with MCP</h2>
        <p className="text-zinc-300">
          Open <strong>Settings → MCP → Add Server</strong>. URL is the same as above; configure
          the Authorization header per Cursor&apos;s MCP UI.
        </p>
      </section>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-3">Where do I find my license key?</h2>
        <p className="text-zinc-300">
          After purchase, your license key is shown on the success page and in{" "}
          <Link href="/buyer" className="text-zinc-100 underline">your purchase history</Link>.
          Keys are formatted <code>iml_</code> followed by 32 base32 characters.
        </p>
      </section>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-3">Limitations (v1)</h2>
        <ul className="list-disc pl-6 text-zinc-300 space-y-1">
          <li>Only SKILL.md format listings can be served via MCP. OpenClaw agents must use the CLI installer or Isol8 direct deploy.</li>
          <li>Companion scripts run in a sandbox: no network, read-only filesystem, 30s wall-clock cap, 256 MB memory.</li>
          <li>Install rate limit is 10 unique source IPs per 24h per license key.</li>
        </ul>
      </section>

      <p className="text-sm text-zinc-500">
        Trouble? Email <a className="underline" href="mailto:support@isol8.co">support@isol8.co</a>.
      </p>
    </main>
  );
}
