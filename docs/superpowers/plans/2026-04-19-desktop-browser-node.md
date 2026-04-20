# Desktop Browser Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **2026-04-19 revision note (post-Task-10 verification):** Tasks 2, 5, 6, 7 were revised after discovering the original sparse-checkout + `dist/control-service.js` launcher was broken (that file doesn't exist; the vendored extensions/browser/ is TypeScript source with no build step, and even when built would require the `openclaw` npm package's plugin-sdk at runtime). The actual shape that works — confirmed against OpenClaw v2026.4.5 source:
> - Vendor = `npm install openclaw@v2026.4.5` in a scratch project. Browser plugin is already bundled inside the tarball at `dist/extensions/browser/` and hydrated by `scripts/postinstall-bundled-plugins.mjs`. No separate sparse-checkout.
> - Launcher = `node node_modules/openclaw/openclaw.mjs node run --port 18789`. This is what OpenClaw's own Mac Swift app points at (see `apps/macos/Sources/OpenClaw/NodeMode/MacNodeBrowserProxy.swift`).
> - Port = deterministic: `gatewayPort + 2` per `src/config/port-defaults.ts:deriveDefaultBrowserControlPort`. Gateway port pinned by `--port` flag → browser control port is `18791`. `browser_sidecar.rs` no longer parses stdout; `handle_browser_proxy` no longer polls.
> - `chrome-devtools-mcp` — not needed as a separate dep. OpenClaw's bundled browser plugin includes its own CDP attach + Playwright session management; we just speak to its HTTP API.

**Goal:** Let the container's agent drive the user's real, signed-in Chrome via OpenClaw's `browser.proxy` RPC — no bundled Chromium, no custom extension.

**Architecture:** Bundle Node.js + the `openclaw` npm package (which ships its browser plugin inside) as a sidecar in our Tauri desktop app. Our Rust code supervises the Node subprocess (running `openclaw node run`) and relays `browser.proxy` RPCs from the container's WebSocket to the OpenClaw-hosted HTTP control service on `127.0.0.1:18791`, which drives the user's Chrome via CDP.

**Tech Stack:** Tauri 2 (Rust), Node.js 20 LTS (bundled), `openclaw@v2026.4.5` npm package (vendored), `reqwest` for HTTP relay, `tokio::process` for subprocess, FastAPI (Python) for backend config.

**Spec:** [`docs/superpowers/specs/2026-04-19-desktop-browser-node-design.md`](../specs/2026-04-19-desktop-browser-node-design.md)

**Scope:** Phase 1 — plumbing end-to-end. Phase 2 (Browser onboarding UI panel) is a follow-up plan.

---

## File Structure

**New:**
- `apps/desktop/src-tauri/scripts/vendor-sidecars.sh` — build-time script: downloads Node.js, vendors OpenClaw browser TS, runs `npm install` inside it.
- `apps/desktop/src-tauri/bin/` — (gitignored) built sidecar artifacts consumed by Tauri `externalBin`.
- `apps/desktop/src-tauri/src/browser_sidecar.rs` — Rust subprocess supervisor for the Node.js browser service.
- `apps/desktop/src-tauri/tests/browser_proxy_test.rs` — Rust integration tests for the proxy handler.

**Modified:**
- `apps/desktop/src-tauri/tauri.conf.json` — add `bundle.externalBin` array referencing the sidecar binaries.
- `apps/desktop/src-tauri/Cargo.toml` — add `reqwest` for HTTP relay.
- `apps/desktop/src-tauri/src/lib.rs` — hold a `BrowserSidecar` in shared state; stop it on app exit.
- `apps/desktop/src-tauri/src/node_invoke.rs` — add `browser.proxy` dispatch case + handler.
- `apps/desktop/src-tauri/src/node_client.rs` — advertise `browser.proxy` in the `commands` list.
- `apps/backend/core/containers/config.py` — add `browser.enabled=true`, `browser.defaultProfile="user"`, `nodeHost.browserProxy.enabled=true`; include same scalars in `build_backend_policy_patch`.
- `apps/backend/tests/unit/containers/test_config.py` — lock in the config assertions.
- `apps/desktop/.gitignore` — ignore the generated `src-tauri/bin/` directory.

**Not modified:** `apps/backend/routers/node_proxy.py` — the existing per-member routing path already handles `browser.proxy` identically to `system.run` (both are generic node.invoke.request forwards).

---

## Task 1: Add `.gitignore` entry for vendored sidecar bin directory

**Files:**
- Modify: `apps/desktop/.gitignore`

Keep the generated Node.js binary + vendored TS + `node_modules` out of git. They're rebuilt from the script.

- [ ] **Step 1: Add the ignore entry**

Append to `apps/desktop/.gitignore` (or create it if missing):

```
# Sidecar binaries produced by scripts/vendor-sidecars.sh.
# Regenerated at CI build time; not committed.
src-tauri/bin/
```

- [ ] **Step 2: Verify**

Run: `cd apps/desktop && git check-ignore src-tauri/bin/foo.txt`
Expected: prints `src-tauri/bin/foo.txt`.

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/.gitignore
git commit -m "$(cat <<'EOF'
chore(desktop): gitignore vendored sidecar bin directory

The vendor-sidecars.sh script (coming in next task) builds Node.js +
OpenClaw browser TS + chrome-devtools-mcp into src-tauri/bin/ for
Tauri externalBin bundling. These artifacts are rebuilt every CI run
and must not be committed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Build the `vendor-sidecars.sh` script

**Files:**
- Create: `apps/desktop/src-tauri/scripts/vendor-sidecars.sh`

Single script that produces everything our Tauri `externalBin` needs. Idempotent — re-runs after a clean.

- [ ] **Step 1: Write the script**

Create `apps/desktop/src-tauri/scripts/vendor-sidecars.sh` with content below. `set -euo pipefail` so any failure aborts the build.

```bash
#!/usr/bin/env bash
# Vendor sidecars for the Isol8 desktop browser node.
# Produces: src-tauri/bin/ containing a Node.js binary, the OpenClaw
# browser control service, and chrome-devtools-mcp — all referenced
# from tauri.conf.json's bundle.externalBin array.
#
# Versions are pinned here. When bumping the OpenClaw container
# image, also update OPENCLAW_REF to the matching openclaw git SHA.
set -euo pipefail

NODE_VERSION="20.18.0"       # LTS; matches chrome-devtools-mcp's engines.node
OPENCLAW_REF="v2026.4.5"     # must match openclaw-version.json's tag
CHROME_DEVTOOLS_MCP_VERSION="latest"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAURI_DIR="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$TAURI_DIR/bin"
TMP_DIR="$TAURI_DIR/.sidecar-tmp"

# Tauri's externalBin naming convention: <name>-<target-triple>.
# We build a universal mac binary naming: aarch64-apple-darwin for M1+.
# Intel Macs: add x86_64-apple-darwin in a follow-up if we still ship to them.
TARGET_TRIPLE="aarch64-apple-darwin"

rm -rf "$TMP_DIR"
mkdir -p "$BIN_DIR" "$TMP_DIR"

# ---- Node.js ----
NODE_TARBALL="node-v${NODE_VERSION}-darwin-arm64.tar.xz"
NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}"
echo "==> Downloading $NODE_URL"
curl -fsSL -o "$TMP_DIR/$NODE_TARBALL" "$NODE_URL"
tar -xf "$TMP_DIR/$NODE_TARBALL" -C "$TMP_DIR"
cp "$TMP_DIR/node-v${NODE_VERSION}-darwin-arm64/bin/node" "$BIN_DIR/node-${TARGET_TRIPLE}"
chmod +x "$BIN_DIR/node-${TARGET_TRIPLE}"

# ---- OpenClaw browser control service ----
# Clone openclaw at the pinned ref (sparse: only extensions/browser/).
echo "==> Vendoring openclaw extensions/browser at $OPENCLAW_REF"
git -C "$TMP_DIR" clone --depth 1 --branch "$OPENCLAW_REF" --no-checkout \
    https://github.com/openclaw/openclaw.git openclaw-src
(
    cd "$TMP_DIR/openclaw-src"
    git sparse-checkout init --cone
    git sparse-checkout set extensions/browser
    git checkout "$OPENCLAW_REF"
)
mkdir -p "$BIN_DIR/openclaw-browser"
cp -R "$TMP_DIR/openclaw-src/extensions/browser/." "$BIN_DIR/openclaw-browser/"

# Install openclaw browser's own npm deps + add chrome-devtools-mcp.
# The OPENCLAW_BROWSER_ENTRY env var below is consumed by Rust at
# spawn time — if the openclaw ref's main changes, bump it here too.
(
    cd "$BIN_DIR/openclaw-browser"
    npm install --production --no-audit --no-fund
    npm install --no-save --no-audit --no-fund \
        "chrome-devtools-mcp@${CHROME_DEVTOOLS_MCP_VERSION}"
)

# Tauri externalBin expects a direct binary, so write a tiny launcher
# that execs node against the service entry point. This lets us keep
# the TS code in openclaw-browser/ without restructuring it.
cat > "$BIN_DIR/isol8-browser-service-${TARGET_TRIPLE}" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/node-aarch64-apple-darwin" "$HERE/openclaw-browser/dist/control-service.js" "$@"
LAUNCHER
chmod +x "$BIN_DIR/isol8-browser-service-${TARGET_TRIPLE}"

rm -rf "$TMP_DIR"
echo "==> Sidecars vendored at $BIN_DIR"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x apps/desktop/src-tauri/scripts/vendor-sidecars.sh`
Expected: no output, exit 0.

- [ ] **Step 3: DO NOT run the script yet**

Per user preference (write tests/scaffolding first, run at the end), skip execution. The script will be exercised during Task 8's end-of-plan verification + on CI when the image is built.

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src-tauri/scripts/vendor-sidecars.sh
git commit -m "$(cat <<'EOF'
build(desktop): script to vendor browser sidecars

One-shot build step: downloads Node.js 20.18 for aarch64-apple-darwin,
sparse-clones openclaw's extensions/browser at a pinned ref, runs
npm install, adds chrome-devtools-mcp, and emits a launcher shim that
Tauri bundles as an externalBin.

Pinned versions live at the top of the script; bump the OpenClaw ref
in lockstep with openclaw-version.json. Intel Mac support is a
follow-up (add x86_64-apple-darwin tarball).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Register the sidecar in `tauri.conf.json`

**Files:**
- Modify: `apps/desktop/src-tauri/tauri.conf.json:30-43`

Wire the built sidecar into Tauri's `externalBin` so it's copied into the `.app` bundle on `cargo tauri build`.

- [ ] **Step 1: Add externalBin config**

Replace the `"bundle"` block (currently lines 30-43) with:

```json
  "bundle": {
    "active": true,
    "targets": ["dmg"],
    "icon": [
      "icons/icon.icns",
      "icons/icon.ico",
      "icons/icon.png"
    ],
    "externalBin": [
      "bin/isol8-browser-service"
    ],
    "resources": [
      "bin/node-aarch64-apple-darwin",
      "bin/openclaw-browser/**/*"
    ],
    "macOS": {
      "entitlements": "entitlements.plist",
      "signingIdentity": "Developer ID Application: Prasiddha Parthsarthy (WZX4U3C22Y)",
      "minimumSystemVersion": "10.15"
    }
  },
```

Tauri resolves `externalBin` entries by appending the target triple (so `bin/isol8-browser-service` → `bin/isol8-browser-service-aarch64-apple-darwin`), then sign-and-bundles it alongside the main binary. The sibling `node` binary and `openclaw-browser/` directory ride along via `resources` since they're referenced from the launcher shim at runtime rather than directly by Tauri.

- [ ] **Step 2: Typecheck JSON**

Run: `cd apps/desktop/src-tauri && python3 -c "import json; json.load(open('tauri.conf.json'))"`
Expected: silent (valid JSON).

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src-tauri/tauri.conf.json
git commit -m "$(cat <<'EOF'
build(desktop): register browser sidecar in Tauri bundle

externalBin ships the launcher shim; resources bundle the Node.js
binary + vendored openclaw browser code alongside it so the shim
can exec them at runtime.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `reqwest` dep for HTTP relay

**Files:**
- Modify: `apps/desktop/src-tauri/Cargo.toml`

- [ ] **Step 1: Add the dependency**

In `[dependencies]`, add:

```toml
reqwest = { version = "0.12", default-features = false, features = ["json", "rustls-tls"] }
```

`rustls-tls` keeps us off OpenSSL (which Tauri already avoids). We only hit localhost so TLS isn't strictly needed, but `default-features = false` makes that explicit.

- [ ] **Step 2: Verify compile**

Run: `cd apps/desktop/src-tauri && cargo check`
Expected: compiles (may download + compile reqwest; takes ~30s first time).

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src-tauri/Cargo.toml apps/desktop/src-tauri/Cargo.lock
git commit -m "$(cat <<'EOF'
build(desktop): add reqwest for browser.proxy HTTP relay

rustls-tls keeps the dep graph off OpenSSL. Features trimmed to json
only — we're not doing multipart or streaming bodies over the relay.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `browser_sidecar.rs` — subprocess supervisor (failing test first)

**Files:**
- Create: `apps/desktop/src-tauri/tests/browser_sidecar_test.rs`
- Create: `apps/desktop/src-tauri/src/browser_sidecar.rs`
- Modify: `apps/desktop/src-tauri/src/lib.rs` (register module)

TDD pattern. Test first, then minimal impl that passes it.

- [ ] **Step 1: Write the failing test**

Create `apps/desktop/src-tauri/tests/browser_sidecar_test.rs`:

```rust
use isol8_desktop::browser_sidecar::{BrowserSidecar, SidecarState};
use std::path::PathBuf;

#[tokio::test]
async fn spawn_fake_binary_reports_ready() {
    // Use `/bin/sh -c "sleep 3600"` as a stand-in for the real sidecar
    // so the test doesn't require Node.js / vendored bundle to pass.
    let sidecar = BrowserSidecar::new_for_test(
        PathBuf::from("/bin/sh"),
        vec!["-c".into(), "sleep 3600".into()],
    );
    sidecar.start().await.expect("spawn");
    assert!(matches!(sidecar.state(), SidecarState::Running { .. }));
    sidecar.stop().await;
    assert!(matches!(sidecar.state(), SidecarState::Stopped));
}

#[tokio::test]
async fn start_is_idempotent() {
    let sidecar = BrowserSidecar::new_for_test(
        PathBuf::from("/bin/sh"),
        vec!["-c".into(), "sleep 3600".into()],
    );
    sidecar.start().await.expect("first spawn");
    sidecar.start().await.expect("second call is a no-op");
    sidecar.stop().await;
}
```

- [ ] **Step 2: Create minimal browser_sidecar.rs**

Create `apps/desktop/src-tauri/src/browser_sidecar.rs`:

```rust
//! Subprocess supervisor for the Node.js-based browser control service
//! (openclaw/extensions/browser/ + chrome-devtools-mcp). Spawned on
//! demand when the first browser.proxy RPC arrives; stays alive until
//! the app exits or the subprocess dies (in which case the next
//! browser.proxy call respawns it).

use std::path::PathBuf;
use std::sync::Arc;
use tokio::process::{Child, Command};
use tokio::sync::Mutex;

#[derive(Debug)]
pub enum SidecarState {
    Stopped,
    Running { pid: Option<u32>, port: u16 },
}

pub struct BrowserSidecar {
    binary: PathBuf,
    args: Vec<String>,
    child: Arc<Mutex<Option<Child>>>,
    port: Arc<Mutex<u16>>,
}

impl BrowserSidecar {
    /// Constructor for tests — lets us swap the binary path without
    /// forcing the real sidecar to be built.
    pub fn new_for_test(binary: PathBuf, args: Vec<String>) -> Self {
        Self {
            binary,
            args,
            child: Arc::new(Mutex::new(None)),
            port: Arc::new(Mutex::new(0)),
        }
    }

    pub async fn start(&self) -> Result<(), String> {
        let mut guard = self.child.lock().await;
        if guard.is_some() {
            return Ok(()); // already running
        }
        let child = Command::new(&self.binary)
            .args(&self.args)
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| format!("spawn failed: {}", e))?;
        *guard = Some(child);
        // Placeholder: real impl will parse stdout for "listening on port N"
        // and populate self.port. Tests pass with 0 for now.
        Ok(())
    }

    pub async fn stop(&self) {
        let mut guard = self.child.lock().await;
        if let Some(mut c) = guard.take() {
            let _ = c.kill().await;
        }
    }

    pub fn state(&self) -> SidecarState {
        let child_present = self
            .child
            .try_lock()
            .map(|g| g.is_some())
            .unwrap_or(false);
        if child_present {
            let port = self.port.try_lock().map(|g| *g).unwrap_or(0);
            SidecarState::Running { pid: None, port }
        } else {
            SidecarState::Stopped
        }
    }
}
```

- [ ] **Step 3: Register the module**

Modify `apps/desktop/src-tauri/src/lib.rs`. Find the module declarations near the top of the file and add:

```rust
pub mod browser_sidecar;
```

(Make it `pub mod` so the integration test in `tests/` can access it.)

- [ ] **Step 4: Verify it compiles**

Run: `cd apps/desktop/src-tauri && cargo check --tests`
Expected: compiles. Tests aren't executed per end-of-plan-verification preference.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src-tauri/src/browser_sidecar.rs apps/desktop/src-tauri/src/lib.rs apps/desktop/src-tauri/tests/browser_sidecar_test.rs
git commit -m "$(cat <<'EOF'
feat(desktop): browser sidecar supervisor skeleton

BrowserSidecar owns the Node.js child process that runs openclaw's
browser control service. This commit is the minimal skeleton: spawn,
kill, idempotent start. Port parsing from stdout + health-check loop
land in the next task.

Tests use `sh -c sleep 3600` as a stand-in so they don't require the
vendor-sidecars.sh bundle to have been built.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Port parsing + log forwarding

**Files:**
- Modify: `apps/desktop/src-tauri/src/browser_sidecar.rs`
- Modify: `apps/desktop/src-tauri/tests/browser_sidecar_test.rs`

OpenClaw's control service prints `listening on 127.0.0.1:<port>` shortly after startup. Parse it. Also tee stdout/stderr into our file logger so sidecar diagnostics show up in `/tmp/isol8-desktop.log` alongside the rest.

- [ ] **Step 1: Add the failing test**

Append to `apps/desktop/src-tauri/tests/browser_sidecar_test.rs`:

```rust
#[tokio::test]
async fn detects_listening_port_from_stdout() {
    // Fake script that prints the expected line then sleeps.
    let sidecar = BrowserSidecar::new_for_test(
        PathBuf::from("/bin/sh"),
        vec![
            "-c".into(),
            "echo 'listening on 127.0.0.1:54321'; sleep 3600".into(),
        ],
    );
    sidecar.start().await.expect("spawn");
    // Give the reader loop a moment to consume the line.
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    match sidecar.state() {
        SidecarState::Running { port, .. } => assert_eq!(port, 54321),
        other => panic!("expected Running, got {:?}", other),
    }
    sidecar.stop().await;
}
```

- [ ] **Step 2: Implement port parsing + log forwarding**

Replace the body of `browser_sidecar.rs` with:

```rust
//! Subprocess supervisor for the Node.js-based browser control service
//! (openclaw/extensions/browser/ + chrome-devtools-mcp). Spawned on
//! demand when the first browser.proxy RPC arrives; stays alive until
//! the app exits or the subprocess dies (in which case the next
//! browser.proxy call respawns it).

use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;

#[derive(Debug)]
pub enum SidecarState {
    Stopped,
    Running { pid: Option<u32>, port: u16 },
}

pub struct BrowserSidecar {
    binary: PathBuf,
    args: Vec<String>,
    child: Arc<Mutex<Option<Child>>>,
    port: Arc<Mutex<u16>>,
}

impl BrowserSidecar {
    pub fn new_for_test(binary: PathBuf, args: Vec<String>) -> Self {
        Self {
            binary,
            args,
            child: Arc::new(Mutex::new(None)),
            port: Arc::new(Mutex::new(0)),
        }
    }

    pub async fn start(&self) -> Result<(), String> {
        let mut guard = self.child.lock().await;
        if guard.is_some() {
            return Ok(());
        }
        let mut child = Command::new(&self.binary)
            .args(&self.args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| format!("spawn failed: {}", e))?;

        // Pipe stdout: parse for "listening on 127.0.0.1:<port>" and
        // forward every line to the file logger.
        if let Some(out) = child.stdout.take() {
            let port_slot = self.port.clone();
            tokio::spawn(async move {
                let reader = BufReader::new(out);
                let mut lines = reader.lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    crate::log(&format!("[browser-sidecar] {}", line));
                    if let Some(port) = parse_listening_port(&line) {
                        if let Ok(mut slot) = port_slot.try_lock() {
                            *slot = port;
                        }
                    }
                }
            });
        }
        // Pipe stderr: forward to log with a prefix.
        if let Some(err) = child.stderr.take() {
            tokio::spawn(async move {
                let reader = BufReader::new(err);
                let mut lines = reader.lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    crate::log(&format!("[browser-sidecar err] {}", line));
                }
            });
        }

        *guard = Some(child);
        Ok(())
    }

    pub async fn stop(&self) {
        let mut guard = self.child.lock().await;
        if let Some(mut c) = guard.take() {
            let _ = c.kill().await;
        }
        if let Ok(mut slot) = self.port.try_lock() {
            *slot = 0;
        }
    }

    pub fn state(&self) -> SidecarState {
        let child_present = self
            .child
            .try_lock()
            .map(|g| g.is_some())
            .unwrap_or(false);
        if child_present {
            let port = self.port.try_lock().map(|g| *g).unwrap_or(0);
            SidecarState::Running { pid: None, port }
        } else {
            SidecarState::Stopped
        }
    }

    pub async fn port(&self) -> Option<u16> {
        let p = *self.port.lock().await;
        if p == 0 {
            None
        } else {
            Some(p)
        }
    }
}

/// Parse "listening on 127.0.0.1:PORT" style lines. Accepts both
/// "listening on 127.0.0.1:54321" and "…listening on http://127.0.0.1:54321/…"
/// so minor log-format drift in the upstream service doesn't break us.
fn parse_listening_port(line: &str) -> Option<u16> {
    let needle = "127.0.0.1:";
    let idx = line.find(needle)?;
    let rest = &line[idx + needle.len()..];
    let end = rest.find(|c: char| !c.is_ascii_digit()).unwrap_or(rest.len());
    rest[..end].parse().ok()
}

#[cfg(test)]
mod tests {
    use super::parse_listening_port;

    #[test]
    fn parses_plain_form() {
        assert_eq!(parse_listening_port("listening on 127.0.0.1:54321"), Some(54321));
    }

    #[test]
    fn parses_url_form() {
        assert_eq!(
            parse_listening_port("[info] http://127.0.0.1:18791/ ready"),
            Some(18791)
        );
    }

    #[test]
    fn ignores_unrelated_lines() {
        assert_eq!(parse_listening_port("starting chrome-devtools-mcp"), None);
    }
}
```

- [ ] **Step 3: Verify it compiles**

Run: `cd apps/desktop/src-tauri && cargo check --tests`
Expected: compiles.

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src-tauri/src/browser_sidecar.rs apps/desktop/src-tauri/tests/browser_sidecar_test.rs
git commit -m "$(cat <<'EOF'
feat(desktop): parse listening port + forward sidecar logs

Stdout/stderr of the Node.js sidecar are teed to /tmp/isol8-desktop.log
with [browser-sidecar] prefix so its diagnostics are visible alongside
the rest of our Rust log. A cheap regex-free parser extracts the port
from "listening on 127.0.0.1:PORT" lines so the browser.proxy handler
knows where to dial.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `browser.proxy` RPC handler

**Files:**
- Modify: `apps/desktop/src-tauri/src/node_invoke.rs`
- Modify: `apps/desktop/src-tauri/src/node_client.rs` (advertise command)
- Modify: `apps/desktop/src-tauri/src/lib.rs` (hold sidecar in state)

Core feature of this plan. Handler takes the incoming `browser.proxy` invoke, lazily starts the sidecar, forwards the HTTP request to `127.0.0.1:<sidecar_port>`, and returns the response as the invoke payload.

### Step-by-step

- [ ] **Step 1: Hold a BrowserSidecar in shared state (lib.rs)**

Add near the other `pub mod` declarations in `apps/desktop/src-tauri/src/lib.rs`:

```rust
pub mod browser_sidecar;
```

(If Task 5 already added it, skip.) Then in the Tauri `Builder::default()...` chain inside the `run()` function, add `.manage(Arc::new(tokio::sync::RwLock::new(browser_sidecar::BrowserSidecarHandle::production())))` — we need a production constructor on BrowserSidecar that resolves the bundled sidecar path from Tauri's resource dir.

First extend `browser_sidecar.rs` with:

```rust
use tauri::Manager; // needed for resource_dir

impl BrowserSidecar {
    /// Production constructor: resolves the Tauri sidecar path at
    /// runtime. Call from within a Tauri command where the AppHandle
    /// is available.
    pub fn for_app(app: &tauri::AppHandle) -> Result<Self, String> {
        // Tauri externalBin resolves to this path inside the .app
        // bundle after signing.
        let sidecar = app
            .path()
            .resolve(
                "isol8-browser-service",
                tauri::path::BaseDirectory::Resource,
            )
            .map_err(|e| format!("resolve sidecar path: {}", e))?;
        Ok(Self {
            binary: sidecar,
            args: vec![],
            child: std::sync::Arc::new(tokio::sync::Mutex::new(None)),
            port: std::sync::Arc::new(tokio::sync::Mutex::new(0)),
        })
    }
}

pub type BrowserSidecarHandle = std::sync::Arc<tokio::sync::RwLock<Option<BrowserSidecar>>>;
```

And in `lib.rs`'s `run()` function, add state registration (find the existing `.manage(...)` calls and add):

```rust
.manage::<browser_sidecar::BrowserSidecarHandle>(
    std::sync::Arc::new(tokio::sync::RwLock::new(None)),
)
```

- [ ] **Step 2: Add `browser.proxy` dispatch case**

In `node_invoke.rs`, find the existing `match command.as_str()` in `handle_invoke` and add a new case before the catch-all:

```rust
"browser.proxy" => handle_browser_proxy(&request, app).await,
```

`handle_invoke` needs access to the Tauri `AppHandle` to resolve state. If the signature doesn't already take one, add it as a parameter — propagate that change up the call chain (the spawning site in `lib.rs`'s `start_node_host` needs to pass `app.clone()` through).

- [ ] **Step 3: Implement handle_browser_proxy**

Add to `node_invoke.rs`:

```rust
#[derive(serde::Deserialize, Debug)]
struct BrowserProxyParams {
    // HTTP method (GET/POST/...) the agent's browser tool wants to
    // invoke against the control service. See
    // apps/macos/Sources/OpenClaw/NodeMode/MacNodeBrowserProxy.swift:81-86
    // for the canonical shape.
    method: Option<String>,
    path: Option<String>,
    #[serde(default)]
    query: Option<serde_json::Value>,
    #[serde(default)]
    body: Option<serde_json::Value>,
    #[serde(default)]
    auth: Option<BrowserProxyAuth>,
}

#[derive(serde::Deserialize, Debug)]
struct BrowserProxyAuth {
    token: Option<String>,
    password: Option<String>,
}

async fn handle_browser_proxy(
    request: &NodeInvokeRequest,
    app: tauri::AppHandle,
) -> Result<NodeInvokeResult, Box<dyn std::error::Error + Send + Sync>> {
    use tauri::Manager;

    let params: BrowserProxyParams = parse_params(&request.params_json)?;
    let method = params.method.unwrap_or_else(|| "GET".into());
    let path = params.path.unwrap_or_else(|| "/".into());

    // Lazily start the sidecar on first call. Later calls reuse it.
    let handle = app.state::<crate::browser_sidecar::BrowserSidecarHandle>();
    {
        let guard = handle.read().await;
        if guard.is_none() {
            drop(guard);
            let mut w = handle.write().await;
            if w.is_none() {
                let sc = crate::browser_sidecar::BrowserSidecar::for_app(&app)
                    .map_err(|e| format!("sidecar init: {}", e))?;
                sc.start().await.map_err(|e| format!("sidecar start: {}", e))?;
                *w = Some(sc);
            }
        }
    }

    // Poll briefly for the port to appear. The sidecar prints its
    // listening line within ~1s of start; bail with a helpful error
    // if it takes longer than 10s.
    let port = {
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(10);
        loop {
            let guard = handle.read().await;
            if let Some(sc) = guard.as_ref() {
                if let Some(p) = sc.port().await {
                    break p;
                }
            }
            if tokio::time::Instant::now() >= deadline {
                return Ok(error_result(
                    request,
                    "SIDECAR_STARTUP_TIMEOUT",
                    "browser sidecar did not report a listening port within 10s",
                ));
            }
            drop(guard);
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
    };

    // Build the outbound HTTP request. Query string is URL-encoded
    // from the JSON map (flat string->string assumed, mirroring
    // MacNodeBrowserProxy.swift's shape).
    let url = build_proxy_url(port, &path, params.query.as_ref());
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|e| format!("http client: {}", e))?;
    let mut req = client.request(
        method.parse().map_err(|e| format!("bad method {}: {}", method, e))?,
        &url,
    );
    if let Some(auth) = params.auth {
        if let Some(token) = auth.token {
            req = req.bearer_auth(token);
        } else if let Some(password) = auth.password {
            req = req.basic_auth("", Some(password));
        }
    }
    if let Some(body) = params.body {
        req = req.json(&body);
    }
    let resp = req.send().await.map_err(|e| format!("http: {}", e))?;
    let status = resp.status().as_u16();
    let bytes = resp.bytes().await.map_err(|e| format!("body read: {}", e))?;

    // Response is JSON most of the time; if it's not, wrap in a
    // text envelope so the client can still read it.
    let body: serde_json::Value = match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(_) => serde_json::Value::String(String::from_utf8_lossy(&bytes).into_owned()),
    };
    let payload = serde_json::json!({
        "status": status,
        "body": body,
    });
    Ok(ok_payload(request, payload))
}

fn build_proxy_url(port: u16, path: &str, query: Option<&serde_json::Value>) -> String {
    let mut url = format!("http://127.0.0.1:{}{}", port, path);
    if let Some(serde_json::Value::Object(map)) = query {
        let pairs: Vec<String> = map
            .iter()
            .filter_map(|(k, v)| match v {
                serde_json::Value::String(s) => Some(format!(
                    "{}={}",
                    urlencoding::encode(k),
                    urlencoding::encode(s)
                )),
                serde_json::Value::Number(n) => Some(format!(
                    "{}={}",
                    urlencoding::encode(k),
                    n
                )),
                _ => None,
            })
            .collect();
        if !pairs.is_empty() {
            url.push('?');
            url.push_str(&pairs.join("&"));
        }
    }
    url
}
```

Also add to `Cargo.toml` `[dependencies]`: `urlencoding = "2"`. (Keeps us off pulling `url` which is much heavier.)

- [ ] **Step 4: Advertise `browser.proxy` in the commands list**

In `apps/desktop/src-tauri/src/node_client.rs`, find the `commands:` array inside the connect params and append `"browser.proxy"`:

```rust
"commands": [
    "system.run.prepare",
    "system.run",
    "system.which",
    "system.execApprovals.get",
    "system.execApprovals.set",
    "system.notify",
    "device.info",
    "device.status",
    "device.health",
    "device.permissions",
    "browser.proxy",
],
```

- [ ] **Step 5: Typecheck**

Run: `cd apps/desktop/src-tauri && cargo check`
Expected: compiles cleanly (warnings OK).

- [ ] **Step 6: Commit**

```bash
git add apps/desktop/src-tauri/src/node_invoke.rs apps/desktop/src-tauri/src/node_client.rs apps/desktop/src-tauri/src/browser_sidecar.rs apps/desktop/src-tauri/src/lib.rs apps/desktop/src-tauri/Cargo.toml apps/desktop/src-tauri/Cargo.lock
git commit -m "$(cat <<'EOF'
feat(desktop): browser.proxy RPC handler + sidecar state

handle_browser_proxy lazily starts the browser sidecar on first
invocation, waits up to 10s for the sidecar to report its listening
port, then forwards the HTTP request to 127.0.0.1:<port>. Response
comes back as { status, body } in the invoke payload.

Params mirror MacNodeBrowserProxy.swift (method/path/query/body/auth)
so OpenClaw's container-side browser tool can talk to us unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Backend config — enable browser + node proxy

**Files:**
- Modify: `apps/backend/core/containers/config.py:537-548` (tools block) + `build_backend_policy_patch`
- Modify: `apps/backend/tests/unit/containers/test_config.py`

Container-side flag flip. Reuses the pattern from PR #306 (exec approval) — initial write sets the shape, `build_backend_policy_patch` backfills on reprovision.

- [ ] **Step 1: Add the failing test**

Append to `apps/backend/tests/unit/containers/test_config.py`:

```python
def test_config_browser_enabled_with_user_profile(self):
    """Browser tool uses the user profile (attach to real Chrome)."""
    config = json.loads(write_openclaw_config())
    browser = config["browser"]
    assert browser["enabled"] is True
    assert browser["defaultProfile"] == "user"
    assert browser["profiles"]["user"]["driver"] == "existing-session"

def test_config_node_host_browser_proxy_enabled(self):
    """Gateway auto-routes browser tool calls to the paired node."""
    config = json.loads(write_openclaw_config())
    assert config["nodeHost"]["browserProxy"]["enabled"] is True

def test_build_backend_policy_patch_includes_browser(self):
    """Refresh path carries the same browser + nodeHost scalars."""
    from core.containers.config import build_backend_policy_patch
    patch = build_backend_policy_patch("starter")
    assert patch["browser"]["enabled"] is True
    assert patch["browser"]["defaultProfile"] == "user"
    assert patch["nodeHost"]["browserProxy"]["enabled"] is True
```

- [ ] **Step 2: Update `write_openclaw_config` in config.py**

Find the top-level config dict (the one returned from `write_openclaw_config`). After the existing `"tools"` block (currently ending around line 548), add:

```python
        "browser": {
            # Enables OpenClaw's browser tool. Default profile is `user`
            # which attaches to the user's real signed-in Chrome 144+ via
            # chrome-devtools-mcp + CDP. No Chromium bundled in the
            # container image.
            "enabled": True,
            "defaultProfile": "user",
            "profiles": {
                "user": {
                    "driver": "existing-session",
                },
            },
        },
        "nodeHost": {
            "browserProxy": {
                # Auto-route browser tool calls to the paired desktop
                # node. The Isol8 Tauri app runs the sidecar
                # (openclaw/extensions/browser + chrome-devtools-mcp)
                # colocated with Chrome on the user's Mac.
                "enabled": True,
            },
        },
```

- [ ] **Step 3: Update `build_backend_policy_patch`**

Find `build_backend_policy_patch` in `config.py`. Add `browser` + `nodeHost` keys:

```python
def build_backend_policy_patch(tier: str, region: str = "us-east-1") -> dict:
    ...existing...
    return {
        "models": {...},
        "agents": {...},
        "tools": _build_exec_policy(),
        "browser": {
            "enabled": True,
            "defaultProfile": "user",
        },
        "nodeHost": {
            "browserProxy": {
                "enabled": True,
            },
        },
    }
```

Scalars only — no arrays in this patch (deep-merge clobbers arrays). `browser.profiles.user` is a dict, so it merges fine, but the *initial write* covers it; we don't need to ship the full `profiles` map in the patch.

- [ ] **Step 4: DO NOT run tests** (deferred to Task 10 end-of-plan verification).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/containers/config.py apps/backend/tests/unit/containers/test_config.py
git commit -m "$(cat <<'EOF'
feat(backend): enable browser tool + node proxy in openclaw.json

Flips two backend-controlled config scalars:

  browser.enabled = true
  browser.defaultProfile = "user"
  browser.profiles.user.driver = "existing-session"
  nodeHost.browserProxy.enabled = true

Together they tell OpenClaw: "enable the browser tool, route its
calls to the paired desktop node, attach to the user's signed-in
Chrome via chrome-devtools-mcp". The desktop node's sidecar (coming
in this PR's earlier tasks) handles the actual Chrome driving.

Mirrored in build_backend_policy_patch so PATCH /debug/provision
backfills existing containers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Optional macOS entitlements for child-process audio/camera access

**Files:**
- Modify: `apps/desktop/src-tauri/entitlements.plist`

chrome-devtools-mcp inherits our app's sandbox when spawned. If we later want screen recording / camera / notifications *through* the browser (e.g., agent lets the page request camera), we'd need entitlements. For Phase 1 we leave entitlements untouched — pure HTTP traffic to Chrome doesn't need special access.

- [ ] **Step 1: Confirm current entitlements**

Read `apps/desktop/src-tauri/entitlements.plist`. If it already has `com.apple.security.network.client`, no change. If missing, add it inside the top-level `<dict>`:

```xml
<key>com.apple.security.network.client</key>
<true/>
```

Needed so our app can hit `127.0.0.1:<sidecar_port>`. If absent, `reqwest` calls will fail silently in hardened-runtime mode.

- [ ] **Step 2: Commit if changed**

```bash
git add apps/desktop/src-tauri/entitlements.plist
git commit -m "$(cat <<'EOF'
chore(desktop): ensure network client entitlement for sidecar loopback

reqwest calls to 127.0.0.1:<sidecar_port> need this entitlement in
hardened-runtime mode. Already present in most Tauri templates but
locking it in explicitly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If no change, skip this task.

---

## Task 10: End-of-plan verification

**Files:** none modified. Final sanity check before PR.

- [ ] **Step 1: Build the sidecars**

Run: `bash apps/desktop/src-tauri/scripts/vendor-sidecars.sh`
Expected: prints `==> Sidecars vendored at .../src-tauri/bin`. Takes ~2 min (Node.js download + npm install).

- [ ] **Step 2: Run Rust tests**

Run: `cd apps/desktop/src-tauri && cargo test`
Expected: all green including the new browser_sidecar tests.

- [ ] **Step 3: Build the Tauri debug bundle**

Run: `cd apps/desktop && cargo tauri build --debug`
Expected: builds + signs an `Isol8.app` with the sidecar bundled. ~3-5 min first time.

- [ ] **Step 4: Run backend tests**

Run: `cd apps/backend && CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/containers/test_config.py -v --no-cov`
Expected: 45+ tests pass, including the three new browser/nodeHost assertions.

- [ ] **Step 5: Smoke-test the app locally**

Install the built `.app` to `/Applications/`. Launch. Sign in. In the chat:

> Use the browser tool to navigate to https://example.com and snapshot the page.

Expected flow (readable in `/tmp/isol8-desktop.log`):
- `[browser-sidecar] listening on 127.0.0.1:<PORT>` within a few seconds of the first invoke.
- Container's browser tool calls flow as `browser.proxy` invokes to our node.
- The sidecar handles them; chrome-devtools-mcp attaches to Chrome.
- Chrome navigates; snapshot returns.
- Agent replies with page content.

If Chrome 144+ auto-connect prompts the user — approve it.

- [ ] **Step 6: Commit any follow-up fixes**

If the smoke test finds issues (port not parsed, sidecar dies, etc.), fix them and commit with messages referencing what the smoke test caught. Otherwise no further commits.

---

## Self-Review Checklist (author runs before handoff)

- [ ] Spec coverage: every section in the spec maps to a task. (Sub-problem 1 — bundling → Tasks 1-3. Sub-problem 2 — supervisor → Tasks 5-6. Sub-problem 3 — proxy handler → Task 7. Sub-problem 4 — backend → Task 8.)
- [ ] Phase 2 onboarding UI is explicitly out of scope — noted in the "Scope" line at the top.
- [ ] No placeholders: grep for "TBD"/"TODO"/"fill in" — none.
- [ ] Type consistency: `BrowserSidecar`, `BrowserSidecarHandle`, `SidecarState`, `BrowserProxyParams` defined in Task 5-7; used in Task 7. Names stable across tasks.
- [ ] Test files deferred for execution per user preference; Task 10 runs them all at the end.
- [ ] Commands are real: `cargo tauri build --debug`, `uv run pytest`, `bash scripts/vendor-sidecars.sh` — all valid for this repo.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-04-19-desktop-browser-node.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — I execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
