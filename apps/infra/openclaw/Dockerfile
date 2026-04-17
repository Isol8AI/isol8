# Extended OpenClaw image — bundles Linux skill binaries so they're available
# at runtime without paying install cost on every container cold-start.
#
# Bump UPSTREAM = `openclaw-version.json#upstream` field. Keep this FROM line in
# sync with that field manually until automation lands.
FROM alpine/openclaw:2026.4.5

USER root

# ---- Layer 1: apt packages (rarely change) ----
# Note: Debian 12's golang-go is 1.19 but modern Steipete tools require
# Go ≥1.24. Go is installed separately below from go.dev in Layer 1b.
RUN apt-get update -qq && apt-get install -y -qq \
      ffmpeg jq ripgrep tmux poppler-utils \
      socat python3-pip sqlite3 build-essential python3 \
      curl wget ca-certificates gnupg make git \
    && rm -rf /var/lib/apt/lists/*

# ---- Layer 1b: Go toolchain (from go.dev, not apt) ----
# Some steipete/* tools have go.mod directives requiring Go ≥1.24, which
# Debian's apt golang-go doesn't satisfy. Pin the latest stable tarball here.
RUN GO_VER=1.24.2 && \
    curl -sL https://go.dev/dl/go${GO_VER}.linux-amd64.tar.gz \
      | tar -xz -C /usr/local && \
    ln -s /usr/local/go/bin/go /usr/local/bin/go && \
    ln -s /usr/local/go/bin/gofmt /usr/local/bin/gofmt

# ---- Layer 2: 1Password CLI (apt repo) ----
RUN curl -sS https://downloads.1password.com/linux/keys/1password.asc \
      | gpg --dearmor -o /usr/share/keyrings/1password-archive-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/amd64 stable main" \
      > /etc/apt/sources.list.d/1password.list && \
    apt-get update -qq && apt-get install -y 1password-cli && \
    rm -rf /var/lib/apt/lists/*

# ---- Layer 3: GitHub CLI ----
RUN GH_VER=2.65.0 && \
    curl -sL https://github.com/cli/cli/releases/download/v${GH_VER}/gh_${GH_VER}_linux_amd64.tar.gz \
      | tar xz -C /tmp && \
    install -m 755 /tmp/gh_${GH_VER}_linux_amd64/bin/gh /usr/local/bin/gh && \
    rm -rf /tmp/gh_${GH_VER}_linux_amd64

# ---- Layer 4: uv (Python package manager) ----
RUN curl -sSL https://astral.sh/uv/install.sh | HOME=/tmp sh && \
    install -m 755 /tmp/.local/bin/uv /usr/local/bin/uv

# ---- Layer 5: pip packages ----
# nano-pdf moved here from a uv-tool layer — uv tool install doesn't accept
# --bin-dir, and pip puts entry points on PATH (/usr/local/bin via system
# Python). One less flag, one less layer.
RUN pip install --break-system-packages openai-whisper websockets nano-pdf

# ---- Layer 7: Go-installed skills ----
ENV GOPATH=/opt/go GOBIN=/usr/local/bin
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
    go install github.com/steipete/spogo/cmd/spogo@latest && \
    rm -rf /opt/go/pkg /opt/go/src /root/.cache/go-build

# ---- Layer 8a: notesmd-cli (formerly obsidian-cli) ----
# Upstream renamed; OpenClaw's `obsidian` SKILL.md still requires bin "obsidian-cli".
# Build under the new name, symlink to the old name to satisfy eligibility.
RUN git clone --depth=1 https://github.com/Yakitrak/notesmd-cli.git /tmp/notesmd && \
    cd /tmp/notesmd && go build -o /usr/local/bin/notesmd-cli . && \
    ln -s /usr/local/bin/notesmd-cli /usr/local/bin/obsidian-cli && \
    rm -rf /tmp/notesmd /root/.cache/go-build

# ---- Layer 8b: openhue ----
# `make build` requires GoReleaser, which is overkill (it builds release
# artifacts for multiple platforms). For a single linux/amd64 binary,
# `go build` from the repo root works directly.
RUN git clone --depth=1 https://github.com/openhue/openhue-cli.git /tmp/openhue && \
    cd /tmp/openhue && go build -o /usr/local/bin/openhue . && \
    rm -rf /tmp/openhue /root/.cache/go-build

# ---- Layer 9: himalaya (pre-built binary via install.sh) ----
RUN curl -sSL https://raw.githubusercontent.com/pimalaya/himalaya/master/install.sh | sh

# ---- Layer 10: Node packages ----
ENV NPM_CONFIG_PREFIX=/usr/local
RUN npm i -g --ignore-scripts \
      mcporter clawhub openai @tobilu/qmd \
      @steipete/oracle @steipete/summarize \
      @anthropic-ai/claude-code @google/gemini-cli \
      @xdevplatform/xurl

# ---- Restore runtime context ----
USER node
WORKDIR /home/node
