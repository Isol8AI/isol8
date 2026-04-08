"""EFS config patcher — file-locked, atomic, deep-merge patching of openclaw.json."""

import asyncio
import copy
import fcntl
import json
import logging
import os
import shutil
import tempfile
from typing import Any, Callable

from core.config import settings

logger = logging.getLogger(__name__)

_efs_mount_path = settings.EFS_MOUNT_PATH


class ConfigPatchError(Exception):
    pass


def _deep_merge(base: dict, patch: dict) -> dict:
    """Deep-merge patch into base. Dicts are merged recursively. Non-dict values are replaced."""
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


async def patch_openclaw_config(owner_id: str, patch: dict) -> None:
    """Patch openclaw.json on EFS with file locking and atomic write.

    1. Acquire file lock (prevents concurrent patches)
    2. Read current config
    3. Back up to .bak
    4. Deep-merge patch
    5. Write atomically (temp file + rename)
    6. Release lock
    """
    config_dir = os.path.join(_efs_mount_path, owner_id)
    config_path = os.path.join(config_dir, "openclaw.json")
    backup_path = os.path.join(config_dir, "openclaw.json.bak")

    if not os.path.exists(config_path):
        raise ConfigPatchError(f"Config not found for owner {owner_id}")

    def _do_patch():
        lock_fd = None
        try:
            lock_fd = open(config_path, "r+")
            fcntl.lockf(lock_fd, fcntl.LOCK_EX)

            with open(config_path, "r") as f:
                current = json.load(f)

            shutil.copy2(config_path, backup_path)

            merged = _deep_merge(current, patch)
            json.dumps(merged)  # validate serializable

            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(merged, f, indent=2)
                # Match OpenClaw container ownership (node uid=1000 gid=1000).
                # Only chown if running as root (backend container runs as root,
                # but tests run as the local user).
                if os.getuid() == 0:
                    os.chown(tmp_path, 1000, 1000)
                os.rename(tmp_path, config_path)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info("Patched openclaw.json for owner %s: %s", owner_id, list(patch.keys()))

        finally:
            if lock_fd:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    await asyncio.to_thread(_do_patch)


async def append_to_openclaw_config_list(
    owner_id: str,
    path: list[str],
    value,
) -> None:
    """Append `value` to the list at `path` in the owner's openclaw.json.

    Semantics:
    - If `path` doesn't exist, create nested dicts as needed and initialize the
      list with `[value]`.
    - If the list already contains `value`, this is a no-op (dedup).
    - Acquires the same fcntl.lockf exclusive lock on openclaw.json as
      `patch_openclaw_config` to serialize concurrent writes.
    """
    if not path:
        raise ConfigPatchError("path must not be empty")

    config_dir = os.path.join(_efs_mount_path, owner_id)
    config_path = os.path.join(config_dir, "openclaw.json")
    backup_path = os.path.join(config_dir, "openclaw.json.bak")

    if not os.path.exists(config_path):
        raise ConfigPatchError(f"Config not found for owner {owner_id}")

    def _do_append():
        lock_fd = None
        try:
            lock_fd = open(config_path, "r+")
            fcntl.lockf(lock_fd, fcntl.LOCK_EX)

            with open(config_path, "r") as f:
                current = json.load(f)

            shutil.copy2(config_path, backup_path)

            # Walk/create the nested path, stopping one short of the leaf
            cursor = current
            for segment in path[:-1]:
                if segment not in cursor or not isinstance(cursor[segment], dict):
                    cursor[segment] = {}
                cursor = cursor[segment]

            leaf_key = path[-1]
            existing = cursor.get(leaf_key)
            if not isinstance(existing, list):
                cursor[leaf_key] = [value]
            elif value not in existing:
                existing.append(value)
            # else: already present, no-op

            json.dumps(current)  # validate serializable

            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(current, f, indent=2)
                if os.getuid() == 0:
                    os.chown(tmp_path, 1000, 1000)
                os.rename(tmp_path, config_path)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info(
                "Appended to openclaw.json list for owner %s: path=%s value=%r",
                owner_id,
                path,
                value,
            )
        finally:
            if lock_fd:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    await asyncio.to_thread(_do_append)


async def remove_from_openclaw_config_list(
    owner_id: str,
    path: list[str],
    predicate: Callable[[Any], bool],
) -> None:
    """Remove entries from the list at `path` where `predicate(entry)` returns True.

    Semantics:
    - If `path` doesn't exist or isn't a list, no-op (no error).
    - Predicate-match approach supports both string matching (e.g. allowFrom)
      and structural matching (e.g. bindings dict entries).
    - Acquires the same fcntl.lockf exclusive lock as append_to_openclaw_config_list.
    """
    if not path:
        raise ConfigPatchError("path must not be empty")

    config_dir = os.path.join(_efs_mount_path, owner_id)
    config_path = os.path.join(config_dir, "openclaw.json")
    backup_path = os.path.join(config_dir, "openclaw.json.bak")

    if not os.path.exists(config_path):
        raise ConfigPatchError(f"Config not found for owner {owner_id}")

    def _do_remove():
        lock_fd = None
        try:
            lock_fd = open(config_path, "r+")
            fcntl.lockf(lock_fd, fcntl.LOCK_EX)

            with open(config_path, "r") as f:
                current = json.load(f)

            # Walk to the leaf
            cursor = current
            for segment in path[:-1]:
                if segment not in cursor or not isinstance(cursor[segment], dict):
                    return  # missing path, no-op
                cursor = cursor[segment]

            leaf_key = path[-1]
            existing = cursor.get(leaf_key)
            if not isinstance(existing, list):
                return  # not a list or missing, no-op

            filtered = [item for item in existing if not predicate(item)]
            if len(filtered) == len(existing):
                return  # nothing removed, skip the write

            cursor[leaf_key] = filtered

            shutil.copy2(config_path, backup_path)
            json.dumps(current)  # validate serializable

            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(current, f, indent=2)
                if os.getuid() == 0:
                    os.chown(tmp_path, 1000, 1000)
                os.rename(tmp_path, config_path)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info(
                "Removed from openclaw.json list for owner %s: path=%s removed=%d",
                owner_id,
                path,
                len(existing) - len(filtered),
            )
        finally:
            if lock_fd:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    await asyncio.to_thread(_do_remove)
