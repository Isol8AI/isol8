import io
from pathlib import Path

import pytest

from core.services.catalog_package import (
    build_manifest,
    tar_directory,
    untar_to_directory,
)


def test_build_manifest_populates_required_fields():
    manifest = build_manifest(
        slug="pitch",
        version=3,
        name="Pitch",
        emoji="🎯",
        vibe="Direct, data-driven",
        description="Runs outbound sales sequences",
        suggested_model="qwen/qwen3-vl-235b",
        suggested_channels=["telegram"],
        required_skills=["web-search"],
        required_plugins=["memory"],
        required_tools=["web-search"],
        published_by="user_admin_123",
    )
    assert manifest["slug"] == "pitch"
    assert manifest["version"] == 3
    assert manifest["name"] == "Pitch"
    assert manifest["suggested_model"] == "qwen/qwen3-vl-235b"
    assert manifest["published_by"] == "user_admin_123"
    assert "published_at" in manifest


def test_tar_and_untar_roundtrip(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "IDENTITY.md").write_text("name: Pitch\n")
    (src / "uploads").mkdir()
    (src / "uploads" / "hello.txt").write_text("world")

    tar_bytes = tar_directory(src)
    assert isinstance(tar_bytes, bytes)
    assert len(tar_bytes) > 0

    dst = tmp_path / "dst"
    dst.mkdir()
    untar_to_directory(io.BytesIO(tar_bytes), dst)

    assert (dst / "IDENTITY.md").read_text() == "name: Pitch\n"
    assert (dst / "uploads" / "hello.txt").read_text() == "world"


def test_untar_rejects_absolute_paths(tmp_path: Path):
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"malicious"
        info = tarfile.TarInfo(name="/etc/evil")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)

    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(ValueError):
        untar_to_directory(buf, dst)


def test_untar_rejects_parent_traversal(tmp_path: Path):
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"payload"
        info = tarfile.TarInfo(name="../escape")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)

    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(ValueError):
        untar_to_directory(buf, dst)


def test_untar_rejects_symlink_members(tmp_path: Path):
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="pwn")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)
    buf.seek(0)

    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(ValueError, match="symlink or hardlink"):
        untar_to_directory(buf, dst)


def test_untar_rejects_hardlink_members(tmp_path: Path):
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="pwn")
        info.type = tarfile.LNKTYPE
        info.linkname = "../escape"
        tf.addfile(info)
    buf.seek(0)

    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(ValueError, match="symlink or hardlink"):
        untar_to_directory(buf, dst)
