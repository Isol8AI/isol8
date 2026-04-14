#!/bin/sh
# Migrate one EFS user directory from the pre-normalization layout
# to the normalized layout, where EVERY agent's workspace lives at
# workspaces/{agent_id}/.
#
# Pre-migration:
#   workspaces/                ← bare main-agent workspace (all of main's files)
#   agents/{id}/               ← custom-agent workspace + OpenClaw runtime metadata
#     agent/, sessions/, plus any user workspace content (SOUL.md etc.)
#
# Post-migration:
#   workspaces/main/           ← main-agent workspace (everything from the old bare root)
#   workspaces/{id}/           ← custom-agent workspace (user content only)
#   agents/{id}/               ← UNTOUCHED — OpenClaw still owns agent/ and sessions/ here
#
# Usage:
#   migrate-agent-workspace.sh /mnt/efs/users/<user_id>            # dry run
#   migrate-agent-workspace.sh --apply /mnt/efs/users/<user_id>    # execute
#
# Run inside the backend ECS task:
#   aws ecs execute-command --cluster <cluster> --task <task_id> \
#     --container backend --interactive \
#     --command "/bin/sh /app/scripts/migrate-agent-workspace.sh /mnt/efs/users/<uid>"
#
# The user's OpenClaw service should be stopped (desired count = 0) before
# running with --apply, to avoid races with a running agent writing into
# workspaces/ while we're moving files.

set -eu

APPLY=0
if [ "${1:-}" = "--apply" ]; then
  APPLY=1
  shift
fi

USER_DIR="${1:-}"
if [ -z "$USER_DIR" ]; then
  echo "usage: $0 [--apply] /mnt/efs/users/<user_id>" >&2
  exit 2
fi

if [ ! -d "$USER_DIR" ]; then
  echo "error: $USER_DIR is not a directory" >&2
  exit 2
fi

WS="$USER_DIR/workspaces"
MAIN="$WS/main"
AGENTS="$USER_DIR/agents"

# OpenClaw subdirectories inside agents/{id}/ that must NOT be moved — they hold
# runtime state (chat history, model config) which OpenClaw keeps owning.
OPENCLAW_RUNTIME_SUBDIRS="agent sessions"

echo "== migrate-agent-workspace =="
echo "  user_dir: $USER_DIR"
echo "  apply:    $APPLY"
echo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

mkdir_p() {
  dir="$1"
  if [ -d "$dir" ]; then
    return 0
  fi
  if [ "$APPLY" -eq 1 ]; then
    mkdir -p "$dir"
    echo "  mkdir: $dir"
  else
    echo "  would mkdir: $dir"
  fi
}

move_item() {
  src="$1"
  dst="$2"
  if [ ! -e "$src" ] && [ ! -L "$src" ]; then
    return 0
  fi
  # Use -e OR -L so a broken symlink at the destination still trips the skip.
  # Without -L, `mv` would overwrite the symlink target instead of bailing.
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    echo "  SKIP (exists): $dst"
    return 0
  fi
  if [ "$APPLY" -eq 1 ]; then
    mv "$src" "$dst"
    echo "  moved: $src -> $dst"
  else
    echo "  would move: $src -> $dst"
  fi
}

# ---------------------------------------------------------------------------
# Step 1: main agent — migrate workspaces/* into workspaces/main/
# ---------------------------------------------------------------------------
#
# The old layout placed ALL of main's workspace content at the bare workspaces/
# root — the 7 OpenClaw seed files, any user-created files, uploads, plus
# runtime subdirs (memory/, state/, etc.). We move EVERYTHING into workspaces/main/
# so nothing is stranded. The only thing we skip is workspaces/main/ itself
# (in case a partial run already created it).
#
# No custom agents have ever landed at workspaces/{id}/ in the legacy layout
# (they were all forced to agents/{id}/ by the frontend override), so every
# entry at workspaces/ root belongs to main.

if [ ! -d "$WS" ]; then
  echo "  workspaces/ doesn't exist — nothing to migrate for main"
else
  echo "== main agent: workspaces/* -> workspaces/main/ =="
  mkdir_p "$MAIN"

  # Iterate every entry at workspaces/ root, including hidden files. Using a
  # find invocation rather than globs so we don't miss dotfiles.
  find "$WS" -mindepth 1 -maxdepth 1 -print | while IFS= read -r entry; do
    name="$(basename "$entry")"
    if [ "$name" = "main" ]; then
      # Either the target dir we just created, OR (unusual) a pre-existing
      # subdir. Either way, do not recurse into ourselves.
      continue
    fi
    move_item "$entry" "$MAIN/$name"
  done

  echo
fi

# ---------------------------------------------------------------------------
# Step 2: custom agents — move user workspace content out of agents/{id}/
# ---------------------------------------------------------------------------
#
# The old layout placed custom-agent workspace files at agents/{id}/, co-mingled
# with OpenClaw's runtime state at agents/{id}/agent/ and agents/{id}/sessions/.
# After the code change, reads/writes for custom agents go to workspaces/{id}/,
# so we relocate anything in agents/{id}/ that isn't OpenClaw runtime state.
#
# `agent/` and `sessions/` stay in agents/{id}/ — OpenClaw still writes there.
#
# Note: we intentionally include `agents/main` in this pass. In the legacy
# layout OpenClaw still created agents/main/sessions/ and agents/main/agent/
# (runtime), but NEVER user workspace files (those went to workspaces/ root
# per Step 1). So the loop is a no-op for main in practice — but if any leftover
# user file IS found there, we migrate it to workspaces/main/ rather than
# strand it.

if [ ! -d "$AGENTS" ]; then
  echo "  agents/ doesn't exist — no custom-agent migration needed"
else
  echo "== custom agents: agents/{id}/* -> workspaces/{id}/* (excl runtime) =="

  find "$AGENTS" -mindepth 1 -maxdepth 1 -type d -print | while IFS= read -r agent_dir; do
    agent_id="$(basename "$agent_dir")"
    target_ws="$WS/$agent_id"
    has_user_content=0

    # Check if there is any non-runtime content in agents/{id}/
    find "$agent_dir" -mindepth 1 -maxdepth 1 -print | while IFS= read -r entry; do
      name="$(basename "$entry")"
      is_runtime=0
      for runtime in $OPENCLAW_RUNTIME_SUBDIRS; do
        if [ "$name" = "$runtime" ]; then
          is_runtime=1
          break
        fi
      done
      if [ "$is_runtime" -eq 1 ]; then
        continue
      fi

      # Non-runtime entry — move to workspaces/{id}/
      if [ "$has_user_content" -eq 0 ]; then
        mkdir_p "$target_ws"
        has_user_content=1
      fi
      move_item "$entry" "$target_ws/$name"
    done
  done

  echo
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

if [ "$APPLY" -eq 0 ]; then
  echo "dry run complete. Re-run with --apply to perform moves."
else
  echo "migration complete."
  echo
  if [ -d "$WS" ]; then
    echo "Remaining in $WS/ (should be main/ + any custom-agent subdirs):"
    ls -la "$WS/"
  fi
  if [ -d "$AGENTS" ]; then
    echo
    echo "Remaining in $AGENTS/ (each agent should have only agent/ and sessions/):"
    ls -la "$AGENTS/"
  fi
fi
