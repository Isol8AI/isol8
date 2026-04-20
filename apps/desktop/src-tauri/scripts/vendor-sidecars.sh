#!/usr/bin/env bash
# Vendor sidecars for the Isol8 desktop browser node.
# Produces: src-tauri/bin/ containing a Node.js binary + a pinned
# install of the `openclaw` npm package, launched via the `openclaw
# node run` subcommand. The browser plugin ships inside the `openclaw`
# tarball (dist/extensions/browser/...) and is loaded automatically
# by node-host mode — no separate plugin install needed.
#
# Mirrors OpenClaw's own macOS app pattern: a native host spawns the
# CLI as a node daemon and hits it over loopback.
set -euo pipefail

NODE_VERSION="20.18.0"    # LTS; matches openclaw's engines.node
OPENCLAW_VERSION="2026.4.5"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAURI_DIR="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$TAURI_DIR/bin"
TMP_DIR="$TAURI_DIR/.sidecar-tmp"

# Tauri externalBin naming: <name>-<target-triple>. aarch64-apple-darwin
# covers M1+; add x86_64-apple-darwin in a follow-up if needed.
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

# ---- OpenClaw runtime ----
# One npm install in a scratch project pulls openclaw + its bundled
# plugins (including extensions/browser). Postinstall hydrates each
# plugin's runtime deps into the root node_modules.
echo "==> Installing openclaw@${OPENCLAW_VERSION}"
OPENCLAW_DIR="$BIN_DIR/openclaw-host"
mkdir -p "$OPENCLAW_DIR"
cat > "$OPENCLAW_DIR/package.json" <<EOF
{
  "name": "isol8-openclaw-host",
  "private": true,
  "version": "0.0.0",
  "dependencies": {
    "openclaw": "${OPENCLAW_VERSION}"
  }
}
EOF
(
    cd "$OPENCLAW_DIR"
    # Use the bundled node for the install to pin the runtime the
    # package expects at install time.
    PATH="$BIN_DIR:$PATH" npm install --production --no-audit --no-fund
)

# Tauri externalBin expects a concrete binary file, so write a tiny
# launcher that execs our bundled node against the openclaw CLI.
# Port is pinned to 18789; browser control port derives to 18791.
cat > "$BIN_DIR/isol8-browser-service-${TARGET_TRIPLE}" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/node-aarch64-apple-darwin" \
    "$HERE/openclaw-host/node_modules/openclaw/openclaw.mjs" \
    node run --host 127.0.0.1 --port 18789 "$@"
LAUNCHER
chmod +x "$BIN_DIR/isol8-browser-service-${TARGET_TRIPLE}"

rm -rf "$TMP_DIR"
echo "==> Sidecars vendored at $BIN_DIR"
