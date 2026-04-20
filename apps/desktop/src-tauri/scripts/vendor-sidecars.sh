#!/usr/bin/env bash
# Vendor sidecars for the Isol8 desktop browser node.
# Produces: src-tauri/bin/ containing Node.js binaries AND pinned
# installs of the `openclaw` npm package for BOTH macOS architectures
# (aarch64 + x86_64), so universal-apple-darwin bundles resolve a
# target-triple-specific launcher at runtime.
#
# Per-arch installs are required because openclaw ships many
# arch-specific native addons via npm optionalDependencies (node-pty,
# clipboard, sharp, canvas, koffi, sqlite-vec). Sharing one
# node_modules across architectures misresolves these.
#
# Mirrors OpenClaw's own macOS Swift integration: a native host
# spawns the CLI (`openclaw node run`) and hits it over loopback.
set -euo pipefail

NODE_VERSION="20.18.0"
OPENCLAW_VERSION="2026.4.5"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAURI_DIR="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$TAURI_DIR/bin"
TMP_DIR="$TAURI_DIR/.sidecar-tmp"

rm -rf "$TMP_DIR"
mkdir -p "$BIN_DIR" "$TMP_DIR"

vendor_arch() {
    local TRIPLE="$1"     # aarch64-apple-darwin | x86_64-apple-darwin
    local NODE_ARCH="$2"  # arm64 | x64
    local NPM_CPU="$3"    # arm64 | x64

    echo "==> Vendoring $TRIPLE (node-$NODE_ARCH, npm --cpu=$NPM_CPU)"

    # Node.js for this arch.
    local NODE_TARBALL="node-v${NODE_VERSION}-darwin-${NODE_ARCH}.tar.xz"
    local NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}"
    curl -fsSL -o "$TMP_DIR/$NODE_TARBALL" "$NODE_URL"
    tar -xf "$TMP_DIR/$NODE_TARBALL" -C "$TMP_DIR"
    cp "$TMP_DIR/node-v${NODE_VERSION}-darwin-${NODE_ARCH}/bin/node" \
       "$BIN_DIR/node-${TRIPLE}"
    chmod +x "$BIN_DIR/node-${TRIPLE}"

    # Arch-specific openclaw install. --cpu/--os/--libc force npm to
    # resolve optional deps for the target arch, regardless of the
    # host the vendor script runs on.
    local HOST_DIR="$BIN_DIR/openclaw-host-${TRIPLE}"
    mkdir -p "$HOST_DIR"
    cat > "$HOST_DIR/package.json" <<EOF
{
  "name": "isol8-openclaw-host-${TRIPLE}",
  "private": true,
  "version": "0.0.0",
  "dependencies": {
    "openclaw": "${OPENCLAW_VERSION}"
  }
}
EOF
    (
        cd "$HOST_DIR"
        # Use the arch-matching node for the install pass. npm uses
        # its own runtime's arch for platform-dep resolution unless
        # overridden, so set explicitly.
        PATH="$BIN_DIR:$PATH" \
        npm install \
            --production \
            --no-audit \
            --no-fund \
            --cpu="${NPM_CPU}" \
            --os=darwin
    )

    # Tauri externalBin expects a concrete file per target triple.
    cat > "$BIN_DIR/isol8-browser-service-${TRIPLE}" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
HERE="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$HERE/node-${TRIPLE}" \\
    "\$HERE/openclaw-host-${TRIPLE}/node_modules/openclaw/openclaw.mjs" \\
    node run --host 127.0.0.1 --port 18789 "\$@"
LAUNCHER
    chmod +x "$BIN_DIR/isol8-browser-service-${TRIPLE}"
}

vendor_arch "aarch64-apple-darwin" "arm64" "arm64"
vendor_arch "x86_64-apple-darwin"  "x64"   "x64"

rm -rf "$TMP_DIR"
echo "==> Sidecars vendored at $BIN_DIR"
ls -1 "$BIN_DIR"
