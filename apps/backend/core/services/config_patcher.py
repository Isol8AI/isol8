"""EFS config patcher — file-locked, atomic, deep-merge patching of openclaw.json."""

import asyncio
import copy
import fcntl
import json
import logging
import os
import shutil
import tempfile

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
            lock_fd = open(config_path, "r")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            with open(config_path, "r") as f:
                current = json.load(f)

            shutil.copy2(config_path, backup_path)

            merged = _deep_merge(current, patch)
            json.dumps(merged)  # validate serializable

            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(merged, f, indent=2)
                os.rename(tmp_path, config_path)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info("Patched openclaw.json for owner %s: %s", owner_id, list(patch.keys()))

        finally:
            if lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    await asyncio.to_thread(_do_patch)
