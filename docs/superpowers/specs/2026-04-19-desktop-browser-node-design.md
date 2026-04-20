# Desktop Browser Node — Design

**Status:** Draft
**Author:** Prasiddha (with Claude)
**Date:** 2026-04-19

## Problem

Isol8 agents run inside a per-user Fargate container. Chrome runs on the user's Mac. Today the two can't see each other: `tools.browser.enabled=false` in our generated `openclaw.json`, and even if we flipped it on, Chrome isn't reachable from the container — CDP is a loopback-only protocol.

We want agents to drive the user's **real, signed-in Chrome** (cookies, logged-in sessions, open tabs, real extensions) without bundling a second browser in the container or shipping a custom Chrome extension.

## Goals

1. Agent in the container can call `browser.navigate`, `browser.snapshot`, `browser.act`, etc. against the user's real Chrome.
2. No Chrome extension required — use Chrome's DevTools Protocol (CDP) via Google's `chrome-devtools-mcp` npm package.
3. No image-size hit on the container. The browser automation stack lives on the user's Mac, colocated with Chrome.
4. Reuse OpenClaw's existing TypeScript browser code (`extensions/browser/`) rather than re-implementing it in Rust. Inherit their updates.
5. Per-user isolation: Alice's agent drives Alice's Chrome; Bob's agent drives Bob's. Enforced by the existing per-member node routing.

## Non-goals

- Container-hosted Chromium (isolated browsing) — a separate future PR; useful for "headless automation while user is away" but not this design.
- Canvas tool (WKWebView on the node) — orthogonal; deferred.
- Custom Chrome extension — `chrome-devtools-mcp` uses CDP; no extension needed.
- Driving Firefox/Safari — Chromium-family only, mirroring OpenClaw's scope.

## Design

### Architecture

```
┌──────────────────────────────┐        ┌──────────────────────────────────┐
│ Container (Fargate gateway)  │        │ User's Mac                       │
│                              │        │                                  │
│   OpenClaw agent             │        │   Isol8 Desktop (Tauri)          │
│        │                     │        │        │                         │
│        ▼                     │        │        │ manages subprocesses    │
│   tools.browser              │        │        ▼                         │
│        │ (profile: user)     │        │   [Node.js sidecar]              │
│        ▼                     │        │   OpenClaw browser control       │
│   browser.proxy RPC ─────────┼────────┼──► HTTP service (127.0.0.1:P)    │
│     over node WS             │        │        │                         │
└──────────────────────────────┘        │        ▼                         │
                                        │   [Node.js sidecar]              │
                                        │   chrome-devtools-mcp            │
                                        │        │ (stdio MCP + CDP)       │
                                        │        ▼                         │
                                        │   ──────────────                 │
                                        │   User's Chrome 144+             │
                                        │   (real profile, real cookies)   │
                                        └──────────────────────────────────┘
```

Flow on an agent `browser.navigate` call:

1. Agent in container calls its built-in `browser` tool.
2. OpenClaw sees `nodeHost.browserProxy.enabled=true` + a browser-capable node connected. It emits a `browser.proxy` RPC targeting the user's nodeId.
3. Backend's existing node routing (`routers/node_proxy.py` + `connection_pool.py`) forwards the RPC to the user's Tauri node over the WebSocket we already use for `system.run`.
4. Tauri node's new Rust shim receives the `browser.proxy` invoke, forwards the HTTP payload to the local OpenClaw browser control service (running as a Node.js sidecar on `127.0.0.1:P`).
5. That service drives `chrome-devtools-mcp` (spawned by it, or as a separate sidecar) over stdio.
6. `chrome-devtools-mcp` speaks CDP to the user's real Chrome.
7. Response unwinds the same path.

### Component inventory

| Piece | Language | Where it runs | Who ships it |
|---|---|---|---|
| Tauri Rust app (existing) | Rust | User's Mac | Us |
| Node.js runtime | binary | User's Mac (bundled with our app via Tauri `externalBin`) | Us (vendored from nodejs.org) |
| OpenClaw `extensions/browser/` TS code | TypeScript | Runs on Node.js sidecar | Vendored from OpenClaw repo, version-pinned to match our container's OpenClaw |
| `chrome-devtools-mcp` | npm package | Runs on Node.js sidecar | Google, resolved via `npx` at install time |
| Chrome 144+ | native | User's Mac | User (prereq) |
| Container `openclaw.json` config | JSON | EFS | Us — `config.py` writes it |
| Backend `browser.proxy` routing | existing | Container | Already works via OpenClaw's `nodeHost.browserProxy.enabled=true` |

### Sub-problem 1 — Sidecar bundling

**Tauri `externalBin` mechanism.** `apps/desktop/src-tauri/tauri.conf.json` grows a `bundle.externalBin` array listing:

- `bin/node` — Node.js 20 LTS for macOS-arm64. Downloaded during our build from official nodejs.org tarball, extracted, placed at `src-tauri/bin/node-aarch64-apple-darwin`.
- `bin/openclaw-browser` — a wrapped launcher script (Node) that runs OpenClaw's `extensions/browser/src/control-service.ts` entry point. Vendored from the OpenClaw repo at a pinned version (matching our container's OpenClaw version so the HTTP protocol stays compatible).
- `bin/chrome-devtools-mcp` — installed via `npm install chrome-devtools-mcp@<pinned>` into our bundle during build.

The CI build step becomes:

```bash
# In the desktop-app build pipeline, before cargo tauri build:
cd apps/desktop/src-tauri
scripts/vendor-sidecars.sh   # fetches node runtime, npm install openclaw browser + chrome-devtools-mcp
```

Rationale for bundling vs. requiring-system-node: avoids a "install Node.js first" onboarding step and avoids version-mismatch support pain. Cost: ~60 MB app bundle increase. Acceptable — we ship a one-time download.

**Pinning:** bump scripts update the vendored TS bundle + `chrome-devtools-mcp` version together whenever we bump the OpenClaw container image. Version drift between the two is the primary failure mode; keeping them in lockstep eliminates it.

### Sub-problem 2 — Subprocess supervisor

New Rust module: `apps/desktop/src-tauri/src/browser_sidecar.rs`.

Responsibilities:

1. **Start on demand** (not at app boot). First `browser.proxy` invoke triggers spawn. Users who never browse pay no RAM.
2. **Spawn `bin/node bin/openclaw-browser` as a child process**, capture its stdout/stderr into our file logger (`crate::log`).
3. **Health-check** the HTTP service by polling `GET /status` every 30s once started. If it 500s or the process exits, mark unhealthy, kill, respawn on next invoke.
4. **Graceful shutdown** on Tauri app exit (SIGTERM → wait 2s → SIGKILL).
5. **Chrome-devtools-mcp lifecycle** is managed by OpenClaw's browser control service itself — it spawns `chrome-devtools-mcp` as its own subprocess per session. We don't need to manage it directly.
6. **Port selection**: Tauri picks a free ephemeral port at spawn time, writes it to a shared struct our `browser.proxy` handler reads.

### Sub-problem 3 — `browser.proxy` RPC handler

Extend `apps/desktop/src-tauri/src/node_invoke.rs`:

1. Add `browser.proxy` to the dispatch match.
2. Handler parses the invoke params — they follow OpenClaw's `browserProxyRequest` shape per `apps/macos/Sources/OpenClaw/NodeMode/MacNodeBrowserProxy.swift:81-86`: `{method, path, query, body, auth: {token|password}}`.
3. Lazily start the sidecar (sub-problem 2) if not running.
4. Proxy the HTTP request to `http://127.0.0.1:{sidecar_port}{path}` with the same method + body + auth headers.
5. If response has file paths referenced (`path`, `imagePath`, `download.path`), base64-encode those files inline — again mirroring `MacNodeBrowserProxy.swift:192-235`. This is how OpenClaw's design returns screenshots/PDFs over an RPC that can't stream binary blobs.
6. Return the full response (JSON + inlined files) as the `node.invoke.result` payload.

Advertise `browser.proxy` in the node's `commands` list (`node_client.rs`) alongside `system.run` so the container knows we support it.

### Sub-problem 4 — Backend + onboarding

**Backend config changes** (`apps/backend/core/containers/config.py`):

```python
"browser": {
    "enabled": True,
    # Default profile binds the agent to the user's real Chrome through
    # chrome-devtools-mcp. "openclaw" profile (isolated Chromium) is
    # disabled because we don't ship Chromium in the container image.
    "defaultProfile": "user",
    "profiles": {
        "user": {
            "driver": "existing-session",
        },
    },
},
"nodeHost": {
    "browserProxy": {
        "enabled": True,
    },
},
```

Backfill the same scalars in the `PATCH /debug/provision` path via `build_backend_policy_patch` — exactly how we backfilled `tools.exec` in PR #306.

**Onboarding UI** (`apps/frontend/src/components/control/panels/BrowserPanel.tsx` — new panel under Control):

A single status panel:

- Row: "Chrome 144+ detected" — probed by running `{browser_bin} --version` on the node via `system.run` (`which google-chrome` or `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`). If missing or too old, link to upgrade.
- Row: "Browser bridge" — shows sidecar status from a new `browser.status` RPC against the node. States: idle / starting / ready / error.
- Button: "Test browser" — sends a canned agent prompt "use your browser to open https://example.com and describe the page" and renders the agent's response inline.
- Row: "Connected Chrome sessions" — count of open Chrome tabs visible to `chrome-devtools-mcp`.

No "install Node.js" step because we bundle it.

### Security model

- CDP is loopback-only; user's Chrome must enable remote debugging. Chrome 144+ auto-accepts the `chrome-devtools-mcp` attach with a user consent prompt on first use.
- Our node does not expose ANY port to the network — the sidecar's HTTP service binds to `127.0.0.1` only.
- The `browser.proxy` invocations cross the already-authenticated node WebSocket; no new attack surface.
- Approval: browser actions do NOT go through `exec.approval.requested` — OpenClaw intentionally does not prompt for each navigate/click (there'd be no usable UX). Users consent once when they first connect Chrome. For sensitive actions (form fills, purchases) we rely on Chrome's own UI remaining visible to the user.

### Per-user isolation

Identical to `system.run`. `_user_nodes[user_id]` in `node_proxy.py` routes each agent session's `browser.proxy` invokes to the correct member's node. Alice's container session talks to Alice's sidecar talks to Alice's Chrome. Bob cannot target Alice's Chrome even within the same org.

### Observability

- Sidecar stdout/stderr → `/tmp/isol8-desktop.log` (our existing file logger) with `[browser-sidecar]` prefix.
- Backend logs `[user_X] browser.proxy method=<path> result=<ok|err>` on each invoke.
- Container's OpenClaw already logs browser tool calls; no changes needed.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Node.js runtime update required for a security patch after we ship | Bundled Node.js is version-pinned; bump via our own release. Automate CVE scanning. |
| OpenClaw's `extensions/browser/` protocol drifts from the version we pin | Lockstep the pinned TS version with our container image version. CI check: on OpenClaw image bump, verify sidecar version bumps too. |
| User's Chrome < 144 | Onboarding panel detects and prompts upgrade. Browser tool invocations fail with a clear `CHROME_TOO_OLD` error — don't time out. |
| Sidecar process crashes mid-session | Supervisor auto-restarts on next invoke. In-flight invoke returns an error; agent retries. |
| macOS blocks child process under App Sandbox | Tauri's `externalBin` sidecars are permitted by the entitlements we already use for `osascript`. No new sandbox requests needed. |
| Bundle size grows from ~40 MB to ~100 MB | Acceptable. First-install download is still a one-time event. Auto-update deltas via Tauri's updater keep future updates small. |

## Testing

**Unit (Rust):**
- `browser_sidecar::spawn` — mock Command, verify stdout capture + healthcheck loop behavior.
- `node_invoke::handle_browser_proxy` — mock the local HTTP service, verify request proxying + file inlining for screenshot responses.

**Integration (on the Tauri app):**
- Spawn sidecar, hit its `/status` endpoint, confirm ready.
- Invoke `browser.proxy` with method=status, verify result matches direct HTTP call.

**E2E (dev env, manual):**
- Install desktop app on a Mac with Chrome 144+.
- Connect browser in onboarding panel.
- Ask agent "navigate to https://example.com and tell me the page title". Expect "Example Domain".
- Ask agent "click the 'More information' link and describe the new page". Expect description of the IANA page.
- Confirm Chrome tab is the user's real Chrome (check cookies, logged-in sites).

## Rollout

- Behind a `tools.browser.enabled` flag already in the openclaw.json. Existing users: flag flips on next `PATCH /debug/provision`. New users: default on from provision.
- Desktop app ships the sidecar bundle in the next `.dmg` update.
- Versioning: openclaw image + desktop sidecar version shipped together.

## Open questions

- Whether to bundle Node.js at all or require user-installed Node. I recommend bundling for zero-setup UX. Decide before implementation starts.
- Whether the first-run "connect Chrome" step should auto-launch Chrome with `--remote-debugging-port` or rely on Chrome 144's new auto-connect. Decide after testing on a real Chrome 144 install.
- Sandbox profile for the TS service — should it run under stricter macOS sandbox profile than our main Tauri app? Trade-off: simpler + broader access vs. smaller blast radius if compromised. Default: inherit the Tauri app's sandbox for now.
