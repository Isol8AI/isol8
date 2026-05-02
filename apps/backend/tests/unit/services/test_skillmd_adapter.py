"""Tests for skillmd_adapter."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

import pytest  # noqa: E402

from core.services import skillmd_adapter  # noqa: E402


def test_pack_skillmd_with_valid_relative_paths_succeeds():
    files = {
        "SKILL.md": (
            "---\nname: test-skill\ndescription: A test skill\n---\n\nRun `./scripts/setup.sh` to initialize.\n"
        ),
        "scripts/setup.sh": "#!/bin/bash\necho hi\n",
    }
    pkg = skillmd_adapter.pack_skillmd(files)
    assert pkg.format == "skillmd"
    assert pkg.manifest["name"] == "test-skill"
    assert "SKILL.md" in pkg.tarball_contents
    assert "scripts/setup.sh" in pkg.tarball_contents


def test_pack_skillmd_rejects_absolute_paths():
    files = {
        "SKILL.md": ("---\nname: test\ndescription: bad\n---\n\nRun `/usr/local/bin/setup.sh` to initialize.\n"),
    }
    with pytest.raises(skillmd_adapter.PathRejectionError) as ei:
        skillmd_adapter.pack_skillmd(files)
    assert "absolute" in str(ei.value).lower()


def test_pack_skillmd_rejects_upward_relative_paths():
    files = {
        "SKILL.md": ("---\nname: test\ndescription: bad\n---\n\nOpen `../../private/keys.txt` for setup.\n"),
    }
    with pytest.raises(skillmd_adapter.PathRejectionError) as ei:
        skillmd_adapter.pack_skillmd(files)
    assert "../" in str(ei.value)


def test_pack_skillmd_requires_frontmatter():
    files = {"SKILL.md": "Just a skill, no YAML frontmatter."}
    with pytest.raises(skillmd_adapter.FrontmatterError):
        skillmd_adapter.pack_skillmd(files)


def test_pack_skillmd_produces_empty_openclaw_slice():
    files = {
        "SKILL.md": "---\nname: x\ndescription: y\n---\nbody",
    }
    pkg = skillmd_adapter.pack_skillmd(files)
    assert pkg.openclaw_slice == {}


# ----------------------------------------------------------------------
# unpack_zip_and_normalize — Path A upload helper
# ----------------------------------------------------------------------

import io  # noqa: E402
import zipfile  # noqa: E402


def _make_zip(entries: dict[str, bytes], wrap_in_dir: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in entries.items():
            full = f"{wrap_in_dir}/{name}" if wrap_in_dir else name
            zf.writestr(full, body)
    return buf.getvalue()


def test_unpack_zip_no_wrapper_kept_flat():
    body = _make_zip(
        {
            "SKILL.md": b"---\nname: x\ndescription: y\n---\nbody",
            "scripts/x.sh": b"#!/bin/sh\n",
        }
    )
    files = skillmd_adapter.unpack_zip_and_normalize(body)
    assert "SKILL.md" in files
    assert "scripts/x.sh" in files


def test_unpack_zip_single_wrapper_dir_stripped():
    body = _make_zip(
        {
            "SKILL.md": b"---\nname: x\ndescription: y\n---\nbody",
            "scripts/x.sh": b"#!/bin/sh\n",
        },
        wrap_in_dir="my-skill",
    )
    files = skillmd_adapter.unpack_zip_and_normalize(body)
    # wrapper stripped — flat layout
    assert "SKILL.md" in files
    assert "scripts/x.sh" in files
    assert "my-skill/SKILL.md" not in files


def test_unpack_zip_multiple_top_levels_kept_as_is():
    body = _make_zip(
        {
            "SKILL.md": b"---\nname: x\ndescription: y\n---",
            "extras/note.txt": b"hi",
        }
    )
    files = skillmd_adapter.unpack_zip_and_normalize(body)
    assert "SKILL.md" in files
    assert "extras/note.txt" in files


def test_unpack_zip_rejects_absolute_path():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/etc/evil.txt", b"x")
    with pytest.raises(skillmd_adapter.ZipValidationError) as ei:
        skillmd_adapter.unpack_zip_and_normalize(buf.getvalue())
    assert "absolute" in str(ei.value).lower()


def test_unpack_zip_rejects_dotdot_path():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", b"x")
    with pytest.raises(skillmd_adapter.ZipValidationError) as ei:
        skillmd_adapter.unpack_zip_and_normalize(buf.getvalue())
    assert "upward" in str(ei.value).lower()


def test_unpack_zip_rejects_symlink():
    import stat as stat_mod

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link.txt")
        info.create_system = 3  # unix
        info.external_attr = (stat_mod.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(skillmd_adapter.ZipValidationError) as ei:
        skillmd_adapter.unpack_zip_and_normalize(buf.getvalue())
    assert "symlink" in str(ei.value).lower()


def test_unpack_zip_rejects_oversized():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        # 11 MB single file — exceeds 10 MB cap.
        zf.writestr("big.bin", b"\x00" * (11 * 1024 * 1024))
    with pytest.raises(skillmd_adapter.ZipValidationError) as ei:
        skillmd_adapter.unpack_zip_and_normalize(buf.getvalue())
    assert "uncompressed" in str(ei.value).lower()


def test_unpack_zip_rejects_too_many_files():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(skillmd_adapter.MAX_ZIP_FILE_COUNT + 5):
            zf.writestr(f"f{i}.txt", b"x")
    with pytest.raises(skillmd_adapter.ZipValidationError) as ei:
        skillmd_adapter.unpack_zip_and_normalize(buf.getvalue())
    assert "max allowed" in str(ei.value).lower()
