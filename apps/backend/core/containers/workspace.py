"""Direct EFS access for per-user OpenClaw workspaces.

Each user's workspace is stored at:
    {mount_path}/{user_id}/

Agent workspaces live under:
    {mount_path}/{user_id}/agents/{agent_name}/

This module handles filesystem CRUD for agent workspaces on EFS.
No S3 or Docker involved -- plain file operations on a mounted volume.
"""

import logging
from pathlib import Path
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)

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

    def write_file(self, user_id: str, path: str, content: str) -> None:
        """Write a text file into a user's workspace.

        Creates parent directories as needed.

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
