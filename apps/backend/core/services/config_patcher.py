"""EFS config patcher — file-locked, atomic, deep-merge patching of openclaw.json."""

import asyncio
import copy
import fcntl
import json
import logging
import os
import shutil
import tempfile
import threading
from typing import Any, Callable

from core.config import settings

logger = logging.getLogger(__name__)

_efs_mount_path = settings.EFS_MOUNT_PATH

# POSIX fcntl/lockf locks are per-process: two threads in the same process
# do NOT block each other via fcntl. Since the reconciler and the patch
# endpoint both run in the backend process and dispatch to the default
# thread-pool executor via ``asyncio.to_thread``, we need an in-process
# lock to serialize them. The fcntl lock still matters for cross-process
# serialization (e.g. a fleet cleanup script run alongside the backend).
_owner_locks: dict[str, threading.Lock] = {}
_owner_locks_guard = threading.Lock()


def _get_owner_lock(owner_id: str) -> threading.Lock:
    with _owner_locks_guard:
        lock = _owner_locks.get(owner_id)
        if lock is None:
            lock = threading.Lock()
            _owner_locks[owner_id] = lock
        return lock


class ConfigPatchError(Exception):
    pass


def deep_merge(base: dict, patch: dict) -> dict:
    """Deep-merge patch into base. Dicts are merged recursively. Non-dict values are replaced."""
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


async def locked_rmw(
    owner_id: str,
    mutate_fn: Callable[[dict], bool],
    log_context: str,
) -> None:
    """Locked read-modify-write skeleton for openclaw.json on EFS.

    Lock contract:
      - Resolves the owner's config path; raises ConfigPatchError if the
        file is missing (callers must pre-seed the config before patching).
      - Acquires a per-owner ``threading.Lock`` first to serialize concurrent
        callers within this process (POSIX fcntl locks are per-process and
        do NOT block sibling threads), then an exclusive ``fcntl.lockf``
        on the file descriptor for cross-process coordination.
        ``fcntl.lockf`` (advisory, POSIX) is used instead of ``flock``
        because ``flock`` is broken over NFS/EFS.
      - Defends against the rename/orphan race: if another writer renamed
        a new inode into place while we were acquiring the fcntl lock,
        our fd's inode differs from ``config_path``'s inode — we drop the
        lock, re-open, and re-acquire until the two match.
      - Reads + parses JSON from the same fd to avoid TOCTOU / double-open.
      - Invokes ``mutate_fn(current)`` to apply per-call mutation logic
        in place. ``mutate_fn`` returns True if the config was modified
        and a write is needed, or False to signal a no-op (skip backup +
        write entirely).
      - On a write: takes a .bak backup, validates serializability,
        atomically writes a tempfile in the same directory and renames
        it into place, and chowns to uid/gid 1000 if running as root
        (matches the OpenClaw container's ``node`` user).
      - Releases the fcntl lock in a ``finally`` block, closes the fd,
        and releases the in-process owner lock. Logs success at INFO
        with ``log_context``.
    """
    config_dir = os.path.join(_efs_mount_path, owner_id)
    config_path = os.path.join(config_dir, "openclaw.json")
    backup_path = os.path.join(config_dir, "openclaw.json.bak")

    owner_lock = _get_owner_lock(owner_id)

    def _do_rmw():
        # Serialize within this process first (fcntl is per-process only;
        # two threads in the same process will not block each other on
        # fcntl.lockf). The fcntl lock below still matters for cross-process
        # coordination (e.g. the fleet cleanup script alongside the backend).
        owner_lock.acquire()
        lock_fd = None
        try:
            # Re-open loop: every successful writer atomically renames a new
            # inode into ``config_path``, which orphans any fd a concurrent
            # cross-process waiter already opened. After acquiring the lock,
            # compare our fd's inode to the one currently at ``config_path``
            # — if they differ, a rename happened while we were waiting;
            # drop the lock, reopen, and re-acquire. Loop until stable.
            while True:
                try:
                    candidate = open(config_path, "r+")
                except FileNotFoundError:
                    raise ConfigPatchError(f"Config not found for owner {owner_id}")
                fcntl.lockf(candidate, fcntl.LOCK_EX)
                try:
                    fd_ino = os.fstat(candidate.fileno()).st_ino
                    path_ino = os.stat(config_path).st_ino
                except FileNotFoundError:
                    # Path vanished between lock + stat; retry.
                    fcntl.lockf(candidate, fcntl.LOCK_UN)
                    candidate.close()
                    continue
                if fd_ino == path_ino:
                    lock_fd = candidate
                    break
                # Orphan fd — a writer replaced the inode while we waited.
                fcntl.lockf(candidate, fcntl.LOCK_UN)
                candidate.close()

            # Read from the same fd we hold the lock on (avoid TOCTOU + double-open).
            lock_fd.seek(0)
            current = json.load(lock_fd)

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

            logger.info("openclaw.json for owner %s: %s", owner_id, log_context)
        finally:
            if lock_fd:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            owner_lock.release()

    await asyncio.to_thread(_do_rmw)


async def patch_openclaw_config(owner_id: str, patch: dict) -> None:
    """Patch openclaw.json on EFS with file locking and atomic write.

    Deep-merges the patch into the existing config and writes the result
    atomically. Raises ConfigPatchError if the config file doesn't exist.
    Always writes (even for empty patches) to preserve historical behavior.
    """

    def _mutate(current: dict) -> bool:
        merged = deep_merge(current, patch)
        current.clear()
        current.update(merged)
        return True  # always write, even for empty patches

    await locked_rmw(owner_id, _mutate, f"patch keys={list(patch.keys())}")


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

    await locked_rmw(owner_id, _mutate, f"append path={path} value={value!r}")


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

        try:
            filtered = [item for item in existing if not predicate(item)]
        except Exception as exc:
            raise ConfigPatchError(f"predicate raised while filtering path={path}: {exc}") from exc
        if len(filtered) == len(existing):
            return False  # nothing removed, skip the write

        cursor[leaf_key] = filtered
        return True

    await locked_rmw(owner_id, _mutate, f"remove path={path}")


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

    await locked_rmw(owner_id, _mutate, f"delete path={path}")
