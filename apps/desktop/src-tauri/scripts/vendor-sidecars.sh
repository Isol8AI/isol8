#!/usr/bin/env bash
# Vendor sidecars for the Isol8 desktop browser node.
# Produces: src-tauri/bin/ containing
#   - node-<triple>                               (per-arch Mach-O binary)
#   - openclaw-host-<triple>/                     (per-arch npm install)
#   - isol8-browser-service-universal-apple-darwin (single dispatch shim)
#
# Tauri's --target universal-apple-darwin bundler looks for exactly one
# externalBin file named `<base>-universal-apple-darwin`. Bash shims
# can't be lipo'd into a fat Mach-O, so we ship ONE shim that detects
# $(uname -m) at runtime and execs the matching node + openclaw-host.
#
# Per-arch npm installs are required because openclaw ships many
# arch-specific native addons via npm optionalDependencies (node-pty,
# clipboard, sharp, canvas, koffi, sqlite-vec). Sharing one
# node_modules across architectures misresolves these.
#
# Mirrors OpenClaw's own macOS Swift integration: a native host
# spawns the CLI (`openclaw node run`) and hits it over loopback.
set -euo pipefail

# openclaw@2026.4.x requires Node >=22.14 (see its package.json
# engines). Node 22 is the current LTS line.
NODE_VERSION="22.14.0"
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
}

vendor_arch "aarch64-apple-darwin" "arm64" "arm64"
vendor_arch "x86_64-apple-darwin"  "x64"   "x64"

# Universal dispatch shim. Named `-universal-apple-darwin` so
# tauri-bundler's externalBin resolver finds it under
# `--target universal-apple-darwin`. Locates its own node + openclaw-host
# at runtime: prod builds land in Contents/Resources; dev builds leave
# siblings next to the shim in target/debug/.
LAUNCHER="$BIN_DIR/isol8-browser-service-universal-apple-darwin"
cat > "$LAUNCHER" <<'LAUNCHER_EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$(uname -m)" in
    arm64)  TRIPLE="aarch64-apple-darwin" ;;
    x86_64) TRIPLE="x86_64-apple-darwin"  ;;
    *) echo "isol8-browser-service: unsupported arch $(uname -m)" >&2; exit 1 ;;
esac

if [ -f "$HERE/../Resources/node-$TRIPLE" ]; then
    ASSETS="$HERE/../Resources"
else
    ASSETS="$HERE"
fi

exec "$ASSETS/node-$TRIPLE" \
    "$ASSETS/openclaw-host-$TRIPLE/node_modules/openclaw/openclaw.mjs" \
    node run --host 127.0.0.1 --port 18789 "$@"
LAUNCHER_EOF
chmod +x "$LAUNCHER"

rm -rf "$TMP_DIR"
echo "==> Sidecars vendored at $BIN_DIR"
ls -1 "$BIN_DIR"
