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


async def _locked_rmw(
    owner_id: str,
    mutate_fn: Callable[[dict], bool],
    log_context: str,
) -> None:
    """Locked read-modify-write skeleton for openclaw.json on EFS.

    Resolves the owner's config path, raises ConfigPatchError if missing,
    acquires an exclusive fcntl.lockf on openclaw.json, reads + parses JSON,
    invokes ``mutate_fn(current)`` to apply per-call mutation logic in place.

    ``mutate_fn`` returns True if the config was modified and a write is
    needed, or False to signal a no-op (skip backup + write entirely).

    On a write, takes a .bak backup, validates serializability, atomically
    renames a tempfile into place, and chowns to uid/gid 1000 if running
    as root. Releases the lock in a finally block. Logs success with
    ``log_context``.
    """
    config_dir = os.path.join(_efs_mount_path, owner_id)
    config_path = os.path.join(config_dir, "openclaw.json")
    backup_path = os.path.join(config_dir, "openclaw.json.bak")

    if not os.path.exists(config_path):
        raise ConfigPatchError(f"Config not found for owner {owner_id}")

    def _do_rmw():
        lock_fd = None
        try:
            lock_fd = open(config_path, "r+")
            fcntl.lockf(lock_fd, fcntl.LOCK_EX)

            with open(config_path, "r") as f:
                current = json.load(f)

            changed = mutate_fn(current)
            if not changed:
                return  # no-op: skip backup + write

            shutil.copy2(config_path, backup_path)
            json.dumps(current)  # validate serializable

            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(current, f, indent=2)
                # Match OpenClaw container ownership (node uid=1000 gid=1000).
                # Only chown if running as root (backend container runs as root,
                # but tests run as the local user).
                if os.getuid() == 0:
                    os.chown(tmp_path, 1000, 1000)
                os.rename(tmp_path, config_path)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info("openclaw.json %s for owner %s", log_context, owner_id)
        finally:
            if lock_fd:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    await asyncio.to_thread(_do_rmw)


async def patch_openclaw_config(owner_id: str, patch: dict) -> None:
    """Patch openclaw.json on EFS with file locking and atomic write.

    Deep-merges the patch into the existing config and writes the result
    atomically. Raises ConfigPatchError if the config file doesn't exist.
    Always writes (even for empty patches) to preserve historical behavior.
    """

    def _mutate(current: dict) -> bool:
        merged = _deep_merge(current, patch)
        current.clear()
        current.update(merged)
        return True  # always write, even for empty patches

    await _locked_rmw(owner_id, _mutate, f"patch keys={list(patch.keys())}")


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

    def _mutate(current: dict) -> bool:
        cursor = current
        for segment in path[:-1]:
            if segment not in cursor or not isinstance(cursor[segment], dict):
                cursor[segment] = {}
            cursor = cursor[segment]

        leaf_key = path[-1]
        existing = cursor.get(leaf_key)
        if not isinstance(existing, list):
            cursor[leaf_key] = [value]
            return True
        if value in existing:
            return False  # dedup no-op
        existing.append(value)
        return True

    await _locked_rmw(owner_id, _mutate, f"append path={path} value={value!r}")


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

    def _mutate(current: dict) -> bool:
        cursor = current
        for segment in path[:-1]:
            if segment not in cursor or not isinstance(cursor[segment], dict):
                return False  # missing path, no-op
            cursor = cursor[segment]

        leaf_key = path[-1]
        existing = cursor.get(leaf_key)
        if not isinstance(existing, list):
            return False  # not a list or missing, no-op

        filtered = [item for item in existing if not predicate(item)]
        if len(filtered) == len(existing):
            return False  # nothing removed, skip the write

        cursor[leaf_key] = filtered
        return True

    await _locked_rmw(owner_id, _mutate, f"remove path={path}")


async def delete_openclaw_config_path(
    owner_id: str,
    path: list[str],
) -> None:
    """Remove the key at `path` from the owner's openclaw.json entirely.

    Semantics:
    - If any intermediate path segment is missing, no-op (no error).
    - If the leaf key doesn't exist, no-op.
    - If the parent dict is empty after removal, it is left as `{}` rather
      than being pruned recursively. OpenClaw treats empty dicts the same
      as missing keys for `channels.*.accounts`.
    - Acquires the same fcntl.lockf exclusive lock as the other helpers.
    """
    if not path:
        raise ConfigPatchError("path must not be empty")

    def _mutate(current: dict) -> bool:
        cursor = current
        for segment in path[:-1]:
            if segment not in cursor or not isinstance(cursor[segment], dict):
                return False  # missing intermediate, no-op
            cursor = cursor[segment]

        leaf_key = path[-1]
        if leaf_key not in cursor:
            return False  # already absent, no-op

        del cursor[leaf_key]
        return True

    await _locked_rmw(owner_id, _mutate, f"delete path={path}")
