#!/bin/sh
# Migrate one EFS user directory from the pre-normalization layout
# (main agent's files at workspaces/*) to the normalized layout
# (main agent's files at workspaces/main/*).
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

echo "== migrate-agent-workspace =="
echo "  user_dir: $USER_DIR"
echo "  apply:    $APPLY"
echo

if [ ! -d "$WS" ]; then
  echo "  workspaces/ doesn't exist — nothing to migrate"
  exit 0
fi

# Items to move from workspaces/ into workspaces/main/.
# Explicit lists prevent accidentally touching custom-agent subdirs that
# already exist at workspaces/{id}/ (these inherit the default and are
# already correctly placed).
CONFIG_FILES="SOUL.md MEMORY.md TOOLS.md IDENTITY.md USER.md HEARTBEAT.md AGENTS.md"
WORKING_DIRS="memory state skills canvas identity uploads"
HIDDEN_DIRS=".openclaw .clawhub"

mkdir_main() {
  if [ -d "$MAIN" ]; then
    return 0
  fi
  if [ "$APPLY" -eq 1 ]; then
    mkdir -p "$MAIN"
    echo "  mkdir: $MAIN"
  else
    echo "  would mkdir: $MAIN"
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

echo "== preview changes =="
mkdir_main
for f in $CONFIG_FILES; do
  move_item "$WS/$f" "$MAIN/$f"
done
for d in $WORKING_DIRS; do
  move_item "$WS/$d" "$MAIN/$d"
done
for d in $HIDDEN_DIRS; do
  move_item "$WS/$d" "$MAIN/$d"
done

echo
if [ "$APPLY" -eq 0 ]; then
  echo "dry run complete. Re-run with --apply to perform moves."
else
  echo "migration complete."
  echo
  echo "Remaining in $WS/ (should be only custom-agent subdirs + main/):"
  ls -la "$WS/"
fi
