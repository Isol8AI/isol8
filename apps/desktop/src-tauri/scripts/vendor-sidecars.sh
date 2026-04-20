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
