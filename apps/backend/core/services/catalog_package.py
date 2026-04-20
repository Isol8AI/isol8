"""Manifest construction and safe tar/untar helpers for catalog packages."""

from __future__ import annotations

import io
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


def build_manifest(
    *,
    slug: str,
    version: int,
    name: str,
    emoji: str,
    vibe: str,
    description: str,
    suggested_model: str,
    suggested_channels: list[str],
    required_skills: list[str],
    required_plugins: list[str],
    required_tools: list[str],
    published_by: str,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "version": version,
        "name": name,
        "emoji": emoji,
        "vibe": vibe,
        "description": description,
        "suggested_model": suggested_model,
        "suggested_channels": suggested_channels,
        "required_skills": required_skills,
        "required_plugins": required_plugins,
        "required_tools": required_tools,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "published_by": published_by,
    }


def tar_directory(src: Path) -> bytes:
    """Tar (gzip) a directory's contents with paths relative to src."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(src, arcname=".")
    return buf.getvalue()


def untar_to_directory(tar_stream: BinaryIO, dst: Path) -> None:
    """Extract a tar.gz stream into dst, rejecting any member whose resolved
    path escapes dst (absolute paths or `..` traversal). Raises ValueError on
    a suspicious member.
    """
    dst_resolved = dst.resolve()
    with tarfile.open(fileobj=tar_stream, mode="r:gz") as tf:
        members = tf.getmembers()
        for m in members:
            if m.name.startswith("/"):
                raise ValueError(f"tar member has absolute path: {m.name!r}")
            target = (dst / m.name).resolve()
            try:
                target.relative_to(dst_resolved)
            except ValueError as exc:
                raise ValueError(f"tar member escapes extraction directory: {m.name!r}") from exc
        tf.extractall(dst)
