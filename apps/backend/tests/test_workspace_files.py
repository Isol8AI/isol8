"""Tests for Workspace.list_directory() and Workspace.read_file_info()."""

import base64
import struct
import zlib
from pathlib import Path

import pytest

from core.containers.workspace import Workspace, WorkspaceError

USER_ID = "user_test_abc"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workspace(tmp_path: Path) -> Workspace:
    """Return a Workspace rooted at tmp_path."""
    return Workspace(mount_path=str(tmp_path))


def _user_root(tmp_path: Path) -> Path:
    return tmp_path / USER_ID


def _minimal_png() -> bytes:
    """Return a valid 1×1 white PNG as bytes."""
    # Build raw IDAT data: one filter byte + one RGB pixel (white)
    raw = b"\x00\xff\xff\xff"
    compressed = zlib.compress(raw)

    def chunk(name: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
        return length + name + data + crc

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    return png


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Workspace:
    """Fresh Workspace using a tmp directory."""
    return _make_workspace(tmp_path)


@pytest.fixture()
def populated_workspace(tmp_path: Path) -> tuple[Workspace, Path]:
    """Workspace pre-populated with sample files and dirs.

    Layout under {tmp_path}/{USER_ID}/:
        agents/
            my-agent/
                notes.md   (text)
                data.bin   (binary, non-image)
        docs/
            readme.txt     (text)
        image.png          (1×1 PNG)
        script.py          (text)
        openclaw.json      (excluded)
        .hidden_file       (excluded — hidden)
        node_modules/      (excluded)
        __pycache__/       (excluded)
    """
    ws = _make_workspace(tmp_path)
    root = tmp_path / USER_ID

    # Visible files/dirs
    (root / "agents" / "my-agent").mkdir(parents=True)
    (root / "agents" / "my-agent" / "notes.md").write_text("# Notes\nHello!", encoding="utf-8")
    (root / "agents" / "my-agent" / "data.bin").write_bytes(b"\x00\x01\x02\x03")
    (root / "docs").mkdir()
    (root / "docs" / "readme.txt").write_text("Hello world", encoding="utf-8")
    (root / "image.png").write_bytes(_minimal_png())
    (root / "script.py").write_text('print("hi")\n', encoding="utf-8")

    # Excluded items
    (root / "openclaw.json").write_text("{}", encoding="utf-8")
    (root / ".hidden_file").write_text("secret", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "__pycache__").mkdir()

    return ws, root


# ===========================================================================
# TestListDirectory
# ===========================================================================


class TestListDirectory:
    def test_list_agent_root(self, populated_workspace):
        """list_directory on user root returns expected visible entries."""
        ws, root = populated_workspace
        entries = ws.list_directory(USER_ID, "")
        names = {e["name"] for e in entries}
        # Visible items
        assert "agents" in names
        assert "docs" in names
        assert "image.png" in names
        assert "script.py" in names
        # Excluded items must not appear
        assert "openclaw.json" not in names
        assert ".hidden_file" not in names
        assert "node_modules" not in names
        assert "__pycache__" not in names

    def test_list_subdirectory(self, populated_workspace):
        """list_directory on a sub-path works correctly."""
        ws, root = populated_workspace
        entries = ws.list_directory(USER_ID, "agents/my-agent")
        names = {e["name"] for e in entries}
        assert "notes.md" in names
        assert "data.bin" in names

    def test_entry_fields_file(self, populated_workspace):
        """File entry has required fields with correct types."""
        ws, root = populated_workspace
        entries = ws.list_directory(USER_ID, "docs")
        assert len(entries) == 1
        entry = entries[0]
        assert entry["name"] == "readme.txt"
        assert entry["type"] == "file"
        assert isinstance(entry["size"], int)
        assert entry["size"] > 0
        assert isinstance(entry["modified_at"], float)
        assert entry["path"] == "docs/readme.txt"

    def test_dirs_have_null_size(self, populated_workspace):
        """Directory entries have size=None."""
        ws, root = populated_workspace
        entries = ws.list_directory(USER_ID, "")
        dir_entries = [e for e in entries if e["type"] == "dir"]
        assert all(e["size"] is None for e in dir_entries)

    def test_sort_order_dirs_first(self, populated_workspace):
        """Directories appear before files; ties broken alphabetically."""
        ws, root = populated_workspace
        entries = ws.list_directory(USER_ID, "")
        types = [e["type"] for e in entries]
        # All dirs must precede all files
        seen_file = False
        for t in types:
            if t == "file":
                seen_file = True
            else:
                assert not seen_file, "A dir appeared after a file"

    def test_sort_order_alphabetical_within_group(self, populated_workspace):
        """Within each group (dirs / files) entries are alphabetically sorted."""
        ws, root = populated_workspace
        entries = ws.list_directory(USER_ID, "")
        dir_names = [e["name"].lower() for e in entries if e["type"] == "dir"]
        file_names = [e["name"].lower() for e in entries if e["type"] == "file"]
        assert dir_names == sorted(dir_names)
        assert file_names == sorted(file_names)

    def test_path_traversal_blocked(self, populated_workspace):
        """Traversal outside the user root raises WorkspaceError."""
        ws, _ = populated_workspace
        with pytest.raises(WorkspaceError):
            ws.list_directory(USER_ID, "../../etc")

    def test_nonexistent_directory(self, workspace):
        """Listing a path that does not exist raises WorkspaceError."""
        (workspace._mount / USER_ID).mkdir(parents=True, exist_ok=True)
        with pytest.raises(WorkspaceError):
            workspace.list_directory(USER_ID, "nonexistent_dir")

    def test_excludes_system_files(self, populated_workspace):
        """All entries in _EXCLUDED_NAMES are hidden from listings."""
        from core.containers.workspace import _EXCLUDED_NAMES

        ws, root = populated_workspace
        entries = ws.list_directory(USER_ID, "")
        names = {e["name"] for e in entries}
        for excluded in _EXCLUDED_NAMES:
            assert excluded not in names, f"{excluded!r} should be excluded"

    def test_path_is_relative_to_user_root(self, populated_workspace):
        """Entry 'path' values are relative to the user's workspace root."""
        ws, root = populated_workspace
        entries = ws.list_directory(USER_ID, "agents/my-agent")
        for entry in entries:
            assert not entry["path"].startswith("/"), "path must be relative"
            assert entry["path"].startswith("agents/my-agent/")


# ===========================================================================
# TestReadFileInfo
# ===========================================================================


class TestReadFileInfo:
    def test_read_text_file(self, populated_workspace):
        """Text file is returned with content as a UTF-8 string."""
        ws, _ = populated_workspace
        info = ws.read_file_info(USER_ID, "docs/readme.txt")
        assert info["name"] == "readme.txt"
        assert info["binary"] is False
        assert info["content"] == "Hello world"
        assert info["size"] == len("Hello world".encode())
        assert isinstance(info["modified_at"], float)
        assert info["path"] == "docs/readme.txt"

    def test_read_text_file_mime_type(self, populated_workspace):
        """Text file has a recognisable mime_type or None (acceptable)."""
        ws, _ = populated_workspace
        info = ws.read_file_info(USER_ID, "script.py")
        assert info["binary"] is False
        assert info["content"] == 'print("hi")\n'
        # mime_type may vary by platform but should not raise

    def test_read_image_file(self, populated_workspace):
        """Image file is returned base64-encoded with binary=True."""
        ws, _ = populated_workspace
        info = ws.read_file_info(USER_ID, "image.png")
        assert info["name"] == "image.png"
        assert info["binary"] is True
        assert info["mime_type"] == "image/png"
        assert info["content"] is not None
        # Verify it round-trips to valid PNG bytes
        decoded = base64.b64decode(info["content"])
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_read_binary_non_image(self, populated_workspace):
        """Non-image binary file returns content=None, binary=True."""
        ws, _ = populated_workspace
        info = ws.read_file_info(USER_ID, "agents/my-agent/data.bin")
        assert info["binary"] is True
        assert info["content"] is None

    def test_path_traversal_blocked(self, populated_workspace):
        """Traversal outside the user root raises WorkspaceError."""
        ws, _ = populated_workspace
        with pytest.raises(WorkspaceError):
            ws.read_file_info(USER_ID, "../../etc/passwd")

    def test_nonexistent_file(self, workspace):
        """Reading a non-existent path raises WorkspaceError."""
        (workspace._mount / USER_ID).mkdir(parents=True, exist_ok=True)
        with pytest.raises(WorkspaceError):
            workspace.read_file_info(USER_ID, "ghost.txt")

    def test_directory_raises(self, populated_workspace):
        """Passing a directory path raises WorkspaceError (not a file)."""
        ws, _ = populated_workspace
        with pytest.raises(WorkspaceError):
            ws.read_file_info(USER_ID, "docs")

    def test_markdown_file(self, populated_workspace):
        """Markdown (.md) is treated as text."""
        ws, _ = populated_workspace
        info = ws.read_file_info(USER_ID, "agents/my-agent/notes.md")
        assert info["binary"] is False
        assert "Notes" in info["content"]

    def test_result_path_is_relative(self, populated_workspace):
        """'path' field in result is relative to user workspace root."""
        ws, _ = populated_workspace
        info = ws.read_file_info(USER_ID, "script.py")
        assert not info["path"].startswith("/")
        assert info["path"] == "script.py"
