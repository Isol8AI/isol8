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
import stat
import tarfile
import zipfile
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


# Zip upload caps. Compressed body cap is enforced by the upload endpoint
# (FastAPI request body size); uncompressed cap is enforced here while
# extracting members one-by-one to defuse zip-bomb attacks.
MAX_ZIP_UNCOMPRESSED_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ZIP_FILE_COUNT = 256


class ZipValidationError(Exception):
    """Uploaded zip violated a validation rule (size, count, traversal, symlink)."""


def unpack_zip_and_normalize(zip_bytes: bytes) -> dict[str, bytes]:
    """Extract a seller-uploaded zip into a flat path → bytes map.

    Validates:
      - File count <= MAX_ZIP_FILE_COUNT
      - Total uncompressed size <= MAX_ZIP_UNCOMPRESSED_BYTES
      - No symlinks (zip external_attr indicates symlink mode bits)
      - No absolute paths
      - No upward-relative ('..') path components

    After extraction, applies a single-wrapper-strip rule: if the result
    has exactly one top-level directory AND that directory contains
    ``SKILL.md`` directly, strip the wrapper. Multiple top-level entries
    are kept as-is. This makes buyer install layouts deterministic
    regardless of how the seller packaged the zip (right-click → Compress
    on macOS / Windows wraps in a folder; ``cd skill && zip -r ...`` does
    not).

    Args:
        zip_bytes: Raw zip file body uploaded via multipart form.

    Returns:
        Map of relative path to file bytes, ready for ``pack_skillmd``.

    Raises:
        ZipValidationError: On any validation rule violation.
    """
    files: dict[str, bytes] = {}

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ZipValidationError(f"upload is not a valid zip file: {exc}") from exc

    members = zf.infolist()
    if len(members) > MAX_ZIP_FILE_COUNT:
        raise ZipValidationError(f"zip contains {len(members)} entries; max allowed is {MAX_ZIP_FILE_COUNT}")

    total_bytes = 0
    for info in members:
        name = info.filename
        if name.endswith("/"):
            # Directory entry — no payload to extract; structure follows from files.
            continue
        if name.startswith("/"):
            raise ZipValidationError(f"zip member has absolute path: {name!r}")
        if any(part == ".." for part in name.split("/")):
            raise ZipValidationError(f"zip member has upward-relative path: {name!r}")
        # Symlink check: zip stores mode bits in the upper 16 of external_attr
        # for unix-style entries. S_ISLNK indicates a symlink.
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and stat.S_ISLNK(mode):
            raise ZipValidationError(f"zip member is a symlink: {name!r}")

        total_bytes += info.file_size
        if total_bytes > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ZipValidationError(f"zip exceeds {MAX_ZIP_UNCOMPRESSED_BYTES // (1024 * 1024)}MB uncompressed cap")
        # Read in one shot — file_size already validated against the cap.
        files[name] = zf.read(info)

    if not files:
        raise ZipValidationError("zip is empty")

    # Wrapper-strip: exactly one top-level directory, and SKILL.md sits at
    # that directory's root.
    top_levels = {name.split("/", 1)[0] for name in files}
    if len(top_levels) == 1:
        wrapper = next(iter(top_levels))
        # Heuristic: there must be a slash in at least one filename (i.e., it
        # really is a wrapper directory, not a single SKILL.md at root).
        wrapped = {name for name in files if "/" in name}
        if wrapped == set(files.keys()):
            sentinel = f"{wrapper}/SKILL.md"
            if sentinel in files:
                files = {name[len(wrapper) + 1 :]: data for name, data in files.items()}

    return files


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
