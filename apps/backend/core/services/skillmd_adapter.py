"""SKILL.md → CatalogPackage adapter.

SKILL.md often references support files via relative paths. When packaged
into a tarball and unpacked into <client-skill-dir>/<slug>/, those paths
must remain valid. This adapter:
  1. Rejects absolute paths (/usr/local/...) — they break post-install.
  2. Rejects upward-relative paths (../) — they escape the install dir.
  3. Validates YAML frontmatter has at minimum `name` and `description`.
  4. Produces a CatalogPackage with an empty openclaw_slice.
"""

import io
import re
import tarfile
from dataclasses import dataclass, field
from typing import Any

import yaml


_ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s`'\"(])(/[^\s`'\")]+)")
_UPWARD_PATH_RE = re.compile(r"\.\./")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class PathRejectionError(Exception):
    """SKILL.md contains a path that won't survive install (absolute or upward-relative)."""


class FrontmatterError(Exception):
    """SKILL.md is missing valid YAML frontmatter or required fields."""


@dataclass
class CatalogPackage:
    format: str
    manifest: dict[str, Any]
    openclaw_slice: dict[str, Any]
    tarball_bytes: bytes
    tarball_contents: list[str] = field(default_factory=list)


def _validate_paths(skill_md_text: str) -> None:
    abs_matches = _ABSOLUTE_PATH_RE.findall(skill_md_text)
    if abs_matches:
        raise PathRejectionError(
            f"SKILL.md contains absolute path(s): {abs_matches[:3]}. "
            f"Use relative paths only — all paths must resolve relative "
            f"to the skill's install directory."
        )
    if _UPWARD_PATH_RE.search(skill_md_text):
        raise PathRejectionError(
            "SKILL.md contains an upward-relative path ('../'). Skills cannot escape their install directory."
        )


def _parse_frontmatter(skill_md_text: str) -> dict[str, Any]:
    m = _FRONTMATTER_RE.match(skill_md_text)
    if not m:
        raise FrontmatterError("SKILL.md must begin with YAML frontmatter delimited by '---'.")
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        raise FrontmatterError(f"SKILL.md frontmatter is not valid YAML: {e}")
    if not isinstance(meta, dict):
        raise FrontmatterError("SKILL.md frontmatter must be a YAML mapping.")
    for required in ("name", "description"):
        if not meta.get(required):
            raise FrontmatterError(f"SKILL.md frontmatter missing required field '{required}'.")
    return meta


def _build_tarball(files: dict[str, str | bytes]) -> tuple[bytes, list[str]]:
    buf = io.BytesIO()
    contents: list[str] = []
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, body in files.items():
            data = body.encode("utf-8") if isinstance(body, str) else body
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            contents.append(path)
    return buf.getvalue(), contents


def pack_skillmd(files: dict[str, str | bytes]) -> CatalogPackage:
    """Pack a SKILL.md + support files into the catalog package format."""
    if "SKILL.md" not in files:
        raise FrontmatterError("Bundle must contain a SKILL.md file.")
    skill_md = files["SKILL.md"]
    if isinstance(skill_md, bytes):
        skill_md = skill_md.decode("utf-8")
    _validate_paths(skill_md)
    meta = _parse_frontmatter(skill_md)

    tarball_bytes, contents = _build_tarball(files)
    manifest = {
        "name": meta["name"],
        "description": meta["description"],
        "format": "skillmd",
        "tags": meta.get("tags", []),
        "version": meta.get("version", "1.0.0"),
    }
    return CatalogPackage(
        format="skillmd",
        manifest=manifest,
        openclaw_slice={},
        tarball_bytes=tarball_bytes,
        tarball_contents=contents,
    )
