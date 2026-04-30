# Extended OpenClaw image — bundles Linux skill binaries so they're available
# at runtime without paying install cost on every container cold-start.
#
# Multi-stage build:
#   builder -> compiles all Go binaries (Go toolchain + build-essential live here)
#   final   -> upstream openclaw + runtime-only apt packages + copied binaries
#
# Splitting the stages keeps the ~600 MB Go toolchain and ~500 MB build-essential
# out of the final image. Targets ~2-3 GB instead of ~8.6 GB so the image fits
# within Fargate's default 20 GiB ephemeral storage with room to spare.
#
# Bump UPSTREAM = `openclaw-version.json#upstream` field. Keep the FROM lines
# below in sync with that field manually until automation lands.

# =============================================================================
# Stage 1: builder — compiles every Go binary, produces /out/bin
# =============================================================================
FROM debian:bookworm-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      build-essential ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

# Pin Go from go.dev — Debian 12's apt golang-go is 1.19, but several
# steipete/* tools have go.mod directives requiring Go ≥1.24.
RUN GO_VER=1.24.2 && \
    curl -sL https://go.dev/dl/go${GO_VER}.linux-amd64.tar.gz \
      | tar -xz -C /usr/local

ENV PATH=/usr/local/go/bin:$PATH \
    GOPATH=/opt/go \
    GOBIN=/out/bin \
    CGO_ENABLED=0

RUN mkdir -p /out/bin

# Steipete + community Go tools — `go install` writes binaries into GOBIN (=/out/bin).
RUN go install github.com/steipete/eightctl/cmd/eightctl@latest && \
    go install github.com/Hyaxia/blogwatcher/cmd/blogwatcher@latest && \
    go install github.com/steipete/ordercli/cmd/ordercli@latest && \
    go install github.com/steipete/sonoscli/cmd/sonos@latest && \
    go install github.com/steipete/wacli/cmd/wacli@latest && \
    go install github.com/steipete/gifgrep/cmd/gifgrep@latest && \
    go install github.com/steipete/blucli/cmd/blu@latest && \
    go install github.com/steipete/songsee/cmd/songsee@latest && \
    go install github.com/steipete/gogcli/cmd/gog@latest && \
    go install github.com/steipete/goplaces/cmd/goplaces@latest && \
    go install github.com/steipete/spogo/cmd/spogo@latest

# notesmd-cli (formerly obsidian-cli) — `go build` from a cloned repo.
RUN git clone --depth=1 https://github.com/Yakitrak/notesmd-cli.git /tmp/notesmd && \
    cd /tmp/notesmd && go build -o /out/bin/notesmd-cli .

# openhue — `go build` from repo root (skipping `make build`/GoReleaser).
RUN git clone --depth=1 https://github.com/openhue/openhue-cli.git /tmp/openhue && \
    cd /tmp/openhue && go build -o /out/bin/openhue .

# =============================================================================
# Stage 2: final — runtime-only image
# =============================================================================
FROM alpine/openclaw:2026.4.23-slim

USER root

# ---- Layer 1: runtime apt packages ----
# Dropped from upstream extended image: build-essential, make (build-only).
# Keeps git/curl/wget/gnupg — runtime tools (skills shell out, clawhub uses git).
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      ffmpeg jq ripgrep tmux poppler-utils \
      socat python3-pip sqlite3 python3 \
      curl wget ca-certificates gnupg git \
    && rm -rf /var/lib/apt/lists/*

# ---- Layer 2: 1Password CLI (apt repo) ----
RUN curl -sS https://downloads.1password.com/linux/keys/1password.asc \
      | gpg --dearmor -o /usr/share/keyrings/1password-archive-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/amd64 stable main" \
      > /etc/apt/sources.list.d/1password.list && \
    apt-get update -qq && apt-get install -y --no-install-recommends 1password-cli && \
    rm -rf /var/lib/apt/lists/*

# ---- Layer 3: GitHub CLI (apt repo) ----
# Was previously a `curl … | tar xz` pipe of the GitHub release tarball,
# which broke on the bookworm-slim base when the gh tarball download went
# through GitHub's release-assets redirect. The apt-repo path matches the
# 1Password setup just above and is what GitHub officially recommends.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update -qq && apt-get install -y --no-install-recommends gh && \
    rm -rf /var/lib/apt/lists/*

# ---- Layer 4: uv (Python package manager) ----
RUN curl -sSL https://astral.sh/uv/install.sh | HOME=/tmp sh && \
    install -m 755 /tmp/.local/bin/uv /usr/local/bin/uv

# ---- Layer 5: pip packages (no cache, pre-built wheels only) ----
# nano-pdf entry points land on PATH via system python (/usr/local/bin).
RUN pip install --no-cache-dir --break-system-packages \
      openai-whisper websockets nano-pdf

# ---- Layer 6: Go-built skills (copied from builder) ----
# 13 binaries built in the builder stage — Go toolchain itself stays out
# of the final image, saving ~600 MB.
COPY --from=builder /out/bin/ /usr/local/bin/

# OpenClaw's `obsidian` SKILL.md still requires bin "obsidian-cli", so
# alias to the renamed `notesmd-cli` to keep eligibility.
RUN ln -s /usr/local/bin/notesmd-cli /usr/local/bin/obsidian-cli

# ---- Layer 7: himalaya (pre-built binary via install.sh) ----
RUN curl -sSL https://raw.githubusercontent.com/pimalaya/himalaya/master/install.sh | sh

# ---- Layer 8: Node packages ----
ENV NPM_CONFIG_PREFIX=/usr/local
RUN npm i -g --ignore-scripts \
      mcporter clawhub openai @tobilu/qmd \
      @steipete/oracle @steipete/summarize \
      @anthropic-ai/claude-code @google/gemini-cli \
      @xdevplatform/xurl

# ---- Layer 8b: qmd at openclaw's hardcoded lookup path ----
# OpenClaw's memory subsystem hardcodes /home/node/.npm-global/bin/qmd
# (see runtime log: "qmd binary unavailable (...); falling back to builtin").
# Layer 8 puts qmd at /usr/local/bin/qmd via NPM_CONFIG_PREFIX=/usr/local;
# this layer symlinks the expected path so the built-in fallback never fires.
RUN mkdir -p /home/node/.npm-global/bin && \
    ln -sf /usr/local/bin/qmd /home/node/.npm-global/bin/qmd && \
    chown -R node:node /home/node/.npm-global

# ---- Layer 8c: pre-bake openclaw plugin runtime deps ----
# Plugins declare bundledRuntimeDeps in their package.json's `openclaw` config.
# At first start, openclaw npm-installs each plugin's deps into
# /app/dist/extensions/<plugin>/node_modules/ unless they already exist with a
# matching semver. Pre-installing in the image eliminates ~5min of cold-start
# (browser plugin's Playwright install dominates).
#
# Detection logic (upstream src/plugins/bundled-runtime-deps.ts):
#   readInstalledDependencyVersion() reads <root>/node_modules/<dep>/package.json
#   and semver-checks against the requested range. Match → skip install.
#
# Spec list extracted from the runtime install log:
#   [plugins] browser installed bundled runtime deps:
#     @modelcontextprotocol/sdk@1.29.0, commander@^14.0.3, express@^5.2.1,
#     playwright-core@1.59.1, typebox@1.1.28, undici@8.1.0, ws@^8.20.0
#   [plugins] deepgram installed bundled runtime deps: ws@^8.20.0
#   [plugins] elevenlabs installed bundled runtime deps: ws@^8.20.0
#   [plugins] microsoft installed bundled runtime deps: node-edge-tts@^1.2.10
#
# We use a shared `--prefix` for each plugin dir so npm scopes to the plugin's
# own node_modules without complaining about a missing package.json.
RUN cd /app/dist/extensions/browser && \
    npm install --no-save --no-audit --no-fund --no-package-lock --omit=dev \
      @modelcontextprotocol/sdk@1.29.0 \
      commander@^14.0.3 \
      express@^5.2.1 \
      playwright-core@1.59.1 \
      typebox@1.1.28 \
      undici@8.1.0 \
      ws@^8.20.0 && \
    cd /app/dist/extensions/deepgram && \
    npm install --no-save --no-audit --no-fund --no-package-lock --omit=dev ws@^8.20.0 && \
    cd /app/dist/extensions/elevenlabs && \
    npm install --no-save --no-audit --no-fund --no-package-lock --omit=dev ws@^8.20.0 && \
    cd /app/dist/extensions/microsoft && \
    npm install --no-save --no-audit --no-fund --no-package-lock --omit=dev node-edge-tts@^1.2.10 && \
    chown -R node:node /app/dist/extensions

# ---- Restore runtime context ----
USER node
WORKDIR /home/node
