"""Direct EFS access for per-user OpenClaw workspaces.

Each user's workspace is stored at:
    {mount_path}/{user_id}/

Agent workspaces live under:
    {mount_path}/{user_id}/agents/{agent_name}/

This module handles filesystem CRUD for agent workspaces on EFS.
No S3 or Docker involved -- plain file operations on a mounted volume.
"""

import base64
import logging
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)

# System files/dirs to hide from directory listings.
_EXCLUDED_NAMES: set[str] = {
    "openclaw.json",
    ".openclaw",
    "node_modules",
    "__pycache__",
    ".mcporter",
    ".git",
}

# File extensions treated as plain text (returned as UTF-8 strings).
_TEXT_EXTENSIONS: set[str] = {
    ".md",
    ".txt",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sh",
    ".bash",
    ".css",
    ".html",
    ".xml",
    ".csv",
    ".sql",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".r",
    ".lua",
    ".env",
    ".cfg",
    ".ini",
    ".conf",
    ".log",
}

# POSIX UID/GID for per-user EFS access points.
# OpenClaw containers run as node (uid 1000) via the access point.
_EFS_USER_UID = 1000
_EFS_USER_GID = 1000

_workspace: Optional["Workspace"] = None


def get_workspace() -> "Workspace":
    """Get the EFS workspace singleton."""
    global _workspace
    if _workspace is None:
        _workspace = Workspace(mount_path=settings.EFS_MOUNT_PATH)
    return _workspace


class WorkspaceError(Exception):
    """Raised when workspace filesystem operations fail."""

    def __init__(self, message: str, user_id: str = ""):
        super().__init__(message)
        self.user_id = user_id


class Workspace:
    """Direct EFS access for per-user OpenClaw workspaces."""

    def __init__(self, mount_path: str):
        self._mount = Path(mount_path)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def user_path(self, user_id: str) -> Path:
        """Return the root directory for a user's workspace."""
        if not user_id or "/" in user_id or ".." in user_id:
            raise WorkspaceError(f"Invalid user_id: {user_id!r}", user_id=user_id)
        return self._mount / user_id

    def _resolve_user_file(self, user_id: str, path: str) -> Path:
        """Resolve a user-relative path and validate it stays within bounds.

        Raises:
            WorkspaceError: If the resolved path escapes the user directory
                (path traversal attack).
        """
        user_dir = self.user_path(user_id).resolve()
        resolved = (user_dir / path).resolve()
        if resolved != user_dir and not str(resolved).startswith(str(user_dir) + "/"):
            raise WorkspaceError(
                f"Path traversal denied: {path!r}",
                user_id=user_id,
            )
        return resolved

    # ------------------------------------------------------------------
    # Directory operations
    # ------------------------------------------------------------------

    def ensure_user_dir(self, user_id: str) -> Path:
        """Create the user workspace directory if it does not exist.

        Also writes default config files (e.g. mcporter.json) if they
        are not already present.

        Returns:
            The Path to the user's workspace directory.

        Raises:
            WorkspaceError: On filesystem errors.
        """
        p = self.user_path(user_id)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Failed to create user directory for %s: %s", user_id, exc)
            raise WorkspaceError(
                f"Failed to create user directory for {user_id}: {exc}",
                user_id=user_id,
            ) from exc

        # Write default mcporter config if not already present
        mcporter_path = p / ".mcporter" / "mcporter.json"
        if not mcporter_path.exists():
            try:
                mcporter_path.parent.mkdir(parents=True, exist_ok=True)
                mcporter_path.write_text('{\n  "servers": {}\n}\n', encoding="utf-8")
            except OSError as exc:
                logger.warning("Failed to write default mcporter.json for %s: %s", user_id, exc)

        return p

    def wipe_user_dir(self, user_id: str) -> bool:
        """Recursively delete a user's entire EFS workspace directory.

        Intended for dev clean-slate resets — wipes `openclaw.json`,
        agent workspaces, pairing files, device keys, everything under
        `{mount_path}/{user_id}/`. Idempotent: returns False if the
        directory did not exist.

        Returns:
            True if a directory was removed, False if it was already absent.

        Raises:
            WorkspaceError: On filesystem errors.
        """
        p = self.user_path(user_id)
        if not p.exists():
            return False
        try:
            shutil.rmtree(p)
        except OSError as exc:
            logger.error("Failed to wipe user dir for %s: %s", user_id, exc)
            raise WorkspaceError(
                f"Failed to wipe user dir for {user_id}: {exc}",
                user_id=user_id,
            ) from exc
        logger.info("Wiped EFS user dir for %s", user_id)
        return True

    def list_agents(self, user_id: str) -> list[str]:
        """List agent names (subdirectories) under a user's agents/ dir.

        Returns:
            Sorted list of agent directory names, or empty list if the
            agents/ directory does not exist.
        """
        agents_dir = self.user_path(user_id) / "agents"
        if not agents_dir.exists():
            return []
        return sorted(d.name for d in agents_dir.iterdir() if d.is_dir())

    def list_directory(self, user_id: str, path: str) -> list[dict]:
        """List the contents of a directory in a user's workspace.

        Hidden entries (starting with '.') and system files/dirs defined in
        ``_EXCLUDED_NAMES`` are omitted from the results.

        Args:
            user_id: The user whose workspace to inspect.
            path: Relative path within the user's workspace directory.

        Returns:
            List of entry dicts sorted dirs-first then alphabetically::

                {
                    "name": str,
                    "path": str,        # relative to user root
                    "type": "file"|"dir",
                    "size": int|None,   # None for directories
                    "modified_at": float,
                }

        Raises:
            WorkspaceError: If the path escapes the user directory, does not
                exist, or is not a directory.
        """
        resolved = self._resolve_user_file(user_id, path)
        if not resolved.exists() or not resolved.is_dir():
            raise WorkspaceError(
                f"Directory not found: {path!r}",
                user_id=user_id,
            )

        user_root = self.user_path(user_id).resolve()
        entries: list[dict] = []

        try:
            for entry in resolved.iterdir():
                name = entry.name
                # Skip hidden entries and excluded system names.
                if name.startswith(".") or name in _EXCLUDED_NAMES:
                    continue

                stat = entry.stat()
                is_dir = entry.is_dir()
                rel_path = str(entry.resolve().relative_to(user_root))

                entries.append(
                    {
                        "name": name,
                        "path": rel_path,
                        "type": "dir" if is_dir else "file",
                        "size": None if is_dir else stat.st_size,
                        "modified_at": stat.st_mtime,
                    }
                )
        except OSError as exc:
            logger.error("Failed to list directory %r for %s: %s", path, user_id, exc)
            raise WorkspaceError(
                f"Failed to list directory {path!r} for {user_id}: {exc}",
                user_id=user_id,
            ) from exc

        # Dirs first, then alphabetically by name (case-insensitive).
        entries.sort(key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))
        return entries

    def read_file_info(self, user_id: str, path: str) -> dict:
        """Return metadata and optionally content for a file.

        Text files are returned as a UTF-8 string. Images are returned as a
        base64-encoded string. All other binary files have ``content=None``.

        Args:
            user_id: The user whose workspace to read from.
            path: Relative path within the user's workspace directory.

        Returns:
            Dict with the following fields::

                {
                    "name": str,
                    "path": str,          # relative to user root
                    "size": int,
                    "modified_at": float,
                    "mime_type": str|None,
                    "binary": bool,
                    "content": str|None,  # text, base64, or None
                }

        Raises:
            WorkspaceError: If the path escapes the user directory, does not
                exist, or is not a file.
        """
        resolved = self._resolve_user_file(user_id, path)
        if not resolved.exists() or not resolved.is_file():
            raise WorkspaceError(
                f"File not found: {path!r}",
                user_id=user_id,
            )

        user_root = self.user_path(user_id).resolve()
        stat = resolved.stat()
        rel_path = str(resolved.resolve().relative_to(user_root))
        mime_type, _ = mimetypes.guess_type(resolved.name)
        mime_type = mime_type or "application/octet-stream"
        suffix = resolved.suffix.lower()

        if suffix in _TEXT_EXTENSIONS:
            try:
                content = resolved.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # File has a text extension but contains non-UTF-8 bytes —
                # treat it as an opaque binary file.
                logger.warning(
                    "File %r for %s has text extension but is not valid UTF-8",
                    path,
                    user_id,
                )
            except OSError as exc:
                logger.error("Failed to read text file %r for %s: %s", path, user_id, exc)
                raise WorkspaceError(
                    f"Failed to read {path!r} for {user_id}: {exc}",
                    user_id=user_id,
                ) from exc
            else:
                return {
                    "name": resolved.name,
                    "path": rel_path,
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "mime_type": mime_type,
                    "binary": False,
                    "content": content,
                }

        if mime_type.startswith("image/"):
            try:
                raw = resolved.read_bytes()
                content = base64.b64encode(raw).decode("ascii")
            except OSError as exc:
                logger.error("Failed to read image %r for %s: %s", path, user_id, exc)
                raise WorkspaceError(
                    f"Failed to read {path!r} for {user_id}: {exc}",
                    user_id=user_id,
                ) from exc
            return {
                "name": resolved.name,
                "path": rel_path,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
                "mime_type": mime_type,
                "binary": True,
                "content": content,
            }

        # Other binary file — return metadata only.
        return {
            "name": resolved.name,
            "path": rel_path,
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
            "mime_type": mime_type,
            "binary": True,
            "content": None,
        }

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def read_file(self, user_id: str, path: str) -> str:
        """Read a text file from a user's workspace.

        Args:
            user_id: The user whose workspace to read from.
            path: Relative path within the user's workspace directory.

        Returns:
            File contents as a string.

        Raises:
            WorkspaceError: If the file does not exist, the path escapes
                the user directory, or a filesystem error occurs.
        """
        resolved = self._resolve_user_file(user_id, path)
        if not resolved.exists():
            raise WorkspaceError(
                f"File not found: {path!r}",
                user_id=user_id,
            )
        try:
            return resolved.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to read %r for %s: %s", path, user_id, exc)
            raise WorkspaceError(
                f"Failed to read {path!r} for {user_id}: {exc}",
                user_id=user_id,
            ) from exc

    def _chown_for_access_point(self, file_path: Path, user_id: str) -> None:
        """Set ownership to match per-user EFS access point POSIX user.

        Chowns the file and all parent directories up to the user root
        so the OpenClaw container (uid 1000 via access point) can read/write.
        Each user's access point is isolated — chowning to 1000:1000 does
        not grant cross-user access.
        """
        if settings.ENVIRONMENT == "local":
            return

        user_root = self.user_path(user_id).resolve()
        try:
            os.chown(file_path, _EFS_USER_UID, _EFS_USER_GID)
            parent = file_path.parent
            while parent >= user_root:
                os.chown(parent, _EFS_USER_UID, _EFS_USER_GID)
                if parent == user_root:
                    break
                parent = parent.parent
        except OSError as exc:
            logger.error("Failed to chown %s for user %s: %s", file_path, user_id, exc)
            raise WorkspaceError(
                f"Failed to set ownership on {file_path} for {user_id}: {exc}",
                user_id=user_id,
            ) from exc

    def write_file(self, user_id: str, path: str, content: str) -> None:
        """Write a text file into a user's workspace.

        Creates parent directories as needed. Sets ownership to 1000:1000
        so per-user EFS access points can read/write.

        Args:
            user_id: The user whose workspace to write into.
            path: Relative path within the user's workspace directory.
            content: Text content to write.

        Raises:
            WorkspaceError: If the path escapes the user directory or a
                filesystem error occurs.
        """
        resolved = self._resolve_user_file(user_id, path)
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            self._chown_for_access_point(resolved, user_id)
        except OSError as exc:
            logger.error("Failed to write %r for %s: %s", path, user_id, exc)
            raise WorkspaceError(
                f"Failed to write {path!r} for {user_id}: {exc}",
                user_id=user_id,
            ) from exc

    def write_bytes(self, user_id: str, path: str, data: bytes) -> None:
        """Write binary data into a user's workspace.

        Creates parent directories as needed.

        Args:
            user_id: The user whose workspace to write into.
            path: Relative path within the user's workspace directory.
            data: Binary content to write.

        Raises:
            WorkspaceError: If the path escapes the user directory or a
                filesystem error occurs.
        """
        resolved = self._resolve_user_file(user_id, path)
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_bytes(data)
            self._chown_for_access_point(resolved, user_id)
        except OSError as exc:
            logger.error("Failed to write %r for %s: %s", path, user_id, exc)
            raise WorkspaceError(
                f"Failed to write {path!r} for {user_id}: {exc}",
                user_id=user_id,
            ) from exc

    def delete_file(self, user_id: str, path: str) -> None:
        """Delete a file from a user's workspace.

        Idempotent: does not raise if the file is already absent.

        Args:
            user_id: The user whose workspace to delete from.
            path: Relative path within the user's workspace directory.

        Raises:
            WorkspaceError: If the path escapes the user directory or a
                filesystem error occurs.
        """
        resolved = self._resolve_user_file(user_id, path)
        if not resolved.exists():
            return
        try:
            resolved.unlink()
        except OSError as exc:
            logger.error("Failed to delete %r for %s: %s", path, user_id, exc)
            raise WorkspaceError(
                f"Failed to delete {path!r} for {user_id}: {exc}",
                user_id=user_id,
            ) from exc
