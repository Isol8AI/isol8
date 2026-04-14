"""Tests for Workspace.list_directory() and Workspace.read_file_info()."""

import base64
import struct
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.auth import AuthContext
from core.config import settings
from core.containers.workspace import Workspace, WorkspaceError

USER_ID = "user_test_abc"
AGENT_ID = "agent-abc-123"


def _auth(owner_id: str = USER_ID) -> AuthContext:
    """Build a minimal AuthContext for direct handler calls (personal mode)."""
    return AuthContext(user_id=owner_id)


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


@pytest.fixture(autouse=True)
def _local_environment(monkeypatch):
    """Force ENVIRONMENT=local so os.chown is skipped on macOS during tests."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")


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

    def test_iterdir_oserror_raises_workspace_error(self, populated_workspace):
        """OSError during iterdir() is wrapped in WorkspaceError."""
        ws, _ = populated_workspace
        with patch.object(Path, "iterdir", side_effect=OSError("NFS stale handle")):
            with pytest.raises(WorkspaceError, match="Failed to list directory"):
                ws.list_directory(USER_ID, "")


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

    def test_non_utf8_text_extension_falls_back_to_binary(self, tmp_path):
        """A .py file with non-UTF-8 bytes falls through to binary result."""
        ws = _make_workspace(tmp_path)
        root = tmp_path / USER_ID
        root.mkdir(parents=True)
        # Write raw bytes that are not valid UTF-8.
        (root / "bad.py").write_bytes(b"\x80\x81\x82\xff")
        info = ws.read_file_info(USER_ID, "bad.py")
        assert info["binary"] is True
        assert info["content"] is None

    def test_mime_type_fallback(self, populated_workspace):
        """Unknown extension gets application/octet-stream instead of None."""
        ws, root = populated_workspace
        info = ws.read_file_info(USER_ID, "agents/my-agent/data.bin")
        assert info["mime_type"] == "application/octet-stream"

    def test_known_mime_type_preserved(self, populated_workspace):
        """Known extension retains its real mime_type."""
        ws, _ = populated_workspace
        info = ws.read_file_info(USER_ID, "image.png")
        assert info["mime_type"] == "image/png"


# ===========================================================================
# TestConfigFilesEndpoint / TestConfigFileReadEndpoint
# ===========================================================================


class TestConfigFilesEndpoint:
    """Tests for GET /workspace/{agent_id}/config-files."""

    def test_returns_only_allowlisted_files(self, tmp_path):
        """Only allowlisted files that exist on disk are returned."""
        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)
        (agent_dir / "SOUL.md").write_text("I am helpful", encoding="utf-8")
        (agent_dir / "MEMORY.md").write_text("Remember this", encoding="utf-8")
        (agent_dir / "sessions").mkdir()  # should be excluded
        (agent_dir / "secret.json").write_text("{}", encoding="utf-8")  # not allowlisted

        from routers.workspace_files import _list_config_files

        result = _list_config_files(ws, USER_ID, AGENT_ID)
        names = {f["name"] for f in result}
        assert names == {"SOUL.md", "MEMORY.md"}
        assert all(f["type"] == "file" for f in result)

    def test_empty_when_no_agent_dir(self, tmp_path):
        """Returns empty list when agent dir doesn't exist."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID).mkdir(parents=True)
        from routers.workspace_files import _list_config_files

        result = _list_config_files(ws, USER_ID, AGENT_ID)
        assert result == []

    def test_file_entries_have_required_fields(self, tmp_path):
        """Each entry has name, path, type, size, modified_at."""
        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)
        (agent_dir / "BOOTSTRAP.md").write_text("# Bootstrap", encoding="utf-8")
        from routers.workspace_files import _list_config_files

        result = _list_config_files(ws, USER_ID, AGENT_ID)
        assert len(result) == 1
        entry = result[0]
        assert entry["name"] == "BOOTSTRAP.md"
        assert entry["path"] == "BOOTSTRAP.md"
        assert entry["type"] == "file"
        assert isinstance(entry["size"], int)
        assert isinstance(entry["modified_at"], float)


class TestConfigFileReadEndpoint:
    """Tests for GET /workspace/{agent_id}/config-file."""

    def test_reads_allowlisted_file(self, tmp_path):
        """Can read an allowlisted config file."""
        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)
        (agent_dir / "SOUL.md").write_text("I am helpful", encoding="utf-8")
        info = ws.read_file_info(USER_ID, f"agents/{AGENT_ID}/SOUL.md")
        assert info["content"] == "I am helpful"
        assert info["binary"] is False

    @pytest.mark.asyncio
    async def test_read_rejects_non_allowlisted_path(self, workspace, monkeypatch):
        """read_config_file returns 400 for a path not in the allowlist."""
        from routers.workspace_files import read_config_file

        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        workspace.ensure_user_dir(USER_ID)
        with pytest.raises(HTTPException) as exc:
            await read_config_file(agent_id=AGENT_ID, path="secret.json", auth=_auth())
        assert exc.value.status_code == 400
        assert "allowlist" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_read_rejects_traversal_in_path(self, workspace, monkeypatch):
        """read_config_file rejects a path with traversal sequences."""
        from routers.workspace_files import read_config_file

        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        workspace.ensure_user_dir(USER_ID)
        with pytest.raises(HTTPException) as exc:
            await read_config_file(agent_id=AGENT_ID, path="../../etc/passwd", auth=_auth())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_read_rejects_traversal_in_agent_id(self, workspace, monkeypatch):
        """read_config_file rejects a traversal sequence in agent_id."""
        from routers.workspace_files import read_config_file

        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        workspace.ensure_user_dir(USER_ID)
        with pytest.raises(HTTPException) as exc:
            await read_config_file(agent_id="../other", path="SOUL.md", auth=_auth())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_list_rejects_traversal_in_agent_id(self, workspace, monkeypatch):
        """list_config_files returns 400 for an agent_id containing '..'."""
        from routers.workspace_files import list_config_files

        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        workspace.ensure_user_dir(USER_ID)
        with pytest.raises(HTTPException) as exc:
            await list_config_files(agent_id="../../other", auth=_auth())
        assert exc.value.status_code == 400


# ===========================================================================
# TestWriteFileEndpoint
# ===========================================================================


class TestWriteFileEndpoint:
    """Tests for the _write_file helper used by the PUT endpoint."""

    def test_write_workspace_file(self, tmp_path):
        """Writing a workspace file for a custom agent creates it under agents/{id}/."""
        ws = _make_workspace(tmp_path)
        user_root = tmp_path / USER_ID
        user_root.mkdir(parents=True)
        ws_dir = user_root / "agents" / AGENT_ID
        ws_dir.mkdir(parents=True)

        from routers.workspace_files import _write_file

        _write_file(ws, USER_ID, AGENT_ID, "plan.md", "# My Plan", "workspace")
        assert (ws_dir / "plan.md").read_text() == "# My Plan"

    def test_write_config_file_allowlisted(self, tmp_path):
        """Writing an allowlisted config file succeeds."""
        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)

        from routers.workspace_files import _write_file

        _write_file(ws, USER_ID, AGENT_ID, "SOUL.md", "I am kind", "config")
        assert (agent_dir / "SOUL.md").read_text() == "I am kind"

    def test_write_config_file_not_allowlisted_raises(self, tmp_path):
        """Writing a non-allowlisted config file raises ValueError."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file

        with pytest.raises(ValueError, match="not in allowlist"):
            _write_file(ws, USER_ID, AGENT_ID, "secret.json", "{}", "config")

    def test_write_creates_parent_dirs(self, tmp_path):
        """Writing to a nested path creates intermediate directories."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file

        _write_file(ws, USER_ID, AGENT_ID, "deep/nested/file.txt", "hello", "workspace")
        assert (tmp_path / USER_ID / "agents" / AGENT_ID / "deep" / "nested" / "file.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_endpoint_rejects_traversal_in_agent_id(self, workspace, monkeypatch):
        """PUT endpoint returns 400 for traversal in agent_id."""
        from fastapi import HTTPException
        from routers.workspace_files import WriteFileRequest, write_workspace_file

        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        workspace.ensure_user_dir(USER_ID)
        body = WriteFileRequest(path="plan.md", content="x", tab="workspace")
        with pytest.raises(HTTPException) as exc:
            await write_workspace_file(agent_id="../other", body=body, auth=_auth())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_endpoint_rejects_invalid_tab(self, workspace, monkeypatch):
        """PUT endpoint returns 400 for a tab value that is neither workspace nor config."""
        from fastapi import HTTPException
        from routers.workspace_files import WriteFileRequest, write_workspace_file

        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        workspace.ensure_user_dir(USER_ID)
        body = WriteFileRequest(path="plan.md", content="x", tab="bogus")
        with pytest.raises(HTTPException) as exc:
            await write_workspace_file(agent_id=AGENT_ID, body=body, auth=_auth())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_endpoint_rejects_non_allowlisted_config_filename(self, workspace, monkeypatch):
        """PUT endpoint returns 400 when writing a non-allowlisted config file."""
        from fastapi import HTTPException
        from routers.workspace_files import WriteFileRequest, write_workspace_file

        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        workspace.ensure_user_dir(USER_ID)
        body = WriteFileRequest(path="secret.json", content="{}", tab="config")
        with pytest.raises(HTTPException) as exc:
            await write_workspace_file(agent_id=AGENT_ID, body=body, auth=_auth())
        assert exc.value.status_code == 400

    def test_write_rejects_traversal_in_path(self, tmp_path):
        """`..` in path raises ValueError (regression for allowlist bypass)."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file

        with pytest.raises(ValueError, match=r"\.\."):
            _write_file(
                ws,
                USER_ID,
                AGENT_ID,
                "../../agents/" + AGENT_ID + "/SOUL.md",
                "hacked",
                "workspace",
            )

    def test_write_rejects_absolute_path(self, tmp_path):
        """Absolute paths are rejected."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file

        with pytest.raises(ValueError, match="relative"):
            _write_file(ws, USER_ID, AGENT_ID, "/etc/passwd", "x", "workspace")

    def test_write_rejects_empty_path(self, tmp_path):
        """Empty path is rejected."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file

        with pytest.raises(ValueError):
            _write_file(ws, USER_ID, AGENT_ID, "", "x", "workspace")

    def test_write_rejects_dot_only_path(self, tmp_path):
        """Dot-only paths (., ./, .) are rejected with ValueError."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file

        for bad in [".", "./", "./.", "././"]:
            with pytest.raises(ValueError, match=r"dot-only"):
                _write_file(ws, USER_ID, AGENT_ID, bad, "x", "workspace")

    def test_write_rejects_oversized_content(self, tmp_path):
        """Content over 10MB is rejected."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file

        big = "a" * (10 * 1024 * 1024 + 1)
        with pytest.raises(ValueError, match="10MB"):
            _write_file(ws, USER_ID, AGENT_ID, "big.txt", big, "workspace")

    @pytest.mark.asyncio
    async def test_endpoint_rejects_traversal_in_path(self, workspace, monkeypatch):
        """PUT endpoint returns 400 for `..` in body.path (regression test)."""
        from fastapi import HTTPException
        from routers.workspace_files import WriteFileRequest, write_workspace_file

        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        workspace.ensure_user_dir(USER_ID)
        body = WriteFileRequest(
            path=f"../../agents/{AGENT_ID}/SOUL.md",
            content="hacked",
            tab="workspace",
        )
        with pytest.raises(HTTPException) as exc:
            await write_workspace_file(agent_id=AGENT_ID, body=body, auth=_auth())
        assert exc.value.status_code == 400

    def test_write_rejects_symlink_escape_workspace(self, tmp_path):
        """Symlink in the custom agent's workspace dir pointing outside must be rejected."""
        import os

        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)
        target = tmp_path / USER_ID / "elsewhere.txt"
        target.write_text("original", encoding="utf-8")

        # Symlink agents/{id}/evil -> ../../elsewhere.txt
        os.symlink("../../elsewhere.txt", agent_dir / "evil")

        from routers.workspace_files import _write_file

        with pytest.raises(ValueError, match="escapes"):
            _write_file(ws, USER_ID, AGENT_ID, "evil", "hacked", "workspace")

        # target must be untouched
        assert target.read_text() == "original"

    def test_write_rejects_symlink_escape_config(self, tmp_path):
        """Symlink in agents/{id}/ pointing outside must be rejected."""
        import os

        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)
        target = tmp_path / USER_ID / "elsewhere.txt"
        target.write_text("original", encoding="utf-8")

        # Symlink agents/{id}/SOUL.md -> ../../elsewhere.txt
        os.symlink("../../elsewhere.txt", agent_dir / "SOUL.md")

        from routers.workspace_files import _write_file

        with pytest.raises(ValueError, match="escapes"):
            _write_file(ws, USER_ID, AGENT_ID, "SOUL.md", "hacked", "config")

        assert target.read_text() == "original"

    def test_write_allows_nested_dirs_within_workspace(self, tmp_path):
        """Subtree check allows legitimate nested paths inside the workspace."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file

        written = _write_file(ws, USER_ID, AGENT_ID, "deep/nested/notes.md", "ok", "workspace")
        assert written == f"agents/{AGENT_ID}/deep/nested/notes.md"
        assert (tmp_path / USER_ID / "agents" / AGENT_ID / "deep" / "nested" / "notes.md").read_text() == "ok"


# ===========================================================================
# TestUploadPath
# ===========================================================================


class TestUploadPath:
    """Verify upload destination path construction."""

    def test_upload_writes_to_custom_agent_workspace(self, tmp_path):
        """Uploads for a custom agent should go to agents/{agent_id}/uploads/."""
        from routers.workspace_files import _agent_workspace_dir

        ws = _make_workspace(tmp_path)
        ws_dir = tmp_path / USER_ID / "agents" / AGENT_ID / "uploads"
        (tmp_path / USER_ID).mkdir(parents=True)

        dest_path = f"{_agent_workspace_dir(AGENT_ID)}/uploads/test.pdf"
        ws.write_bytes(USER_ID, dest_path, b"fake pdf content")
        assert (ws_dir / "test.pdf").read_bytes() == b"fake pdf content"

    def test_upload_writes_to_main_agent_workspace(self, tmp_path):
        """Uploads for the main agent should go to workspaces/uploads/ (user root)."""
        from routers.workspace_files import _agent_workspace_dir

        ws = _make_workspace(tmp_path)
        ws_dir = tmp_path / USER_ID / "workspaces" / "uploads"
        (tmp_path / USER_ID).mkdir(parents=True)

        dest_path = f"{_agent_workspace_dir('main')}/uploads/test.pdf"
        ws.write_bytes(USER_ID, dest_path, b"fake pdf content")
        assert (ws_dir / "test.pdf").read_bytes() == b"fake pdf content"

    def test_agent_visible_path_custom(self):
        """Agent-visible path for a custom agent should include agents/{agent_id}."""
        from routers.workspace_files import _agent_workspace_dir

        agent_id = "my-agent"
        filename = "data.csv"
        dest_path = f"{_agent_workspace_dir(agent_id)}/uploads/{filename}"
        agent_path = f".openclaw/{dest_path}"
        assert agent_path == f".openclaw/agents/{agent_id}/uploads/{filename}"

    def test_agent_visible_path_main(self):
        """Agent-visible path for the main agent should use workspaces/ at user root."""
        from routers.workspace_files import _agent_workspace_dir

        filename = "data.csv"
        dest_path = f"{_agent_workspace_dir('main')}/uploads/{filename}"
        agent_path = f".openclaw/{dest_path}"
        assert agent_path == f".openclaw/workspaces/uploads/{filename}"


# ===========================================================================
# TestWorkspaceTreeRoundTrip
# ===========================================================================


class TestWorkspaceTreeRoundTrip:
    """Verify list → read uses the same agent-relative path contract."""

    @pytest.mark.asyncio
    async def test_tree_path_feeds_back_to_read(self, workspace, monkeypatch):
        """A path returned by the tree endpoint reads successfully via the file endpoint."""
        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        ws_dir = workspace._mount / USER_ID / "agents" / AGENT_ID
        ws_dir.mkdir(parents=True)
        (ws_dir / "plan.md").write_text("# Plan\nstep 1", encoding="utf-8")
        (ws_dir / "uploads").mkdir()
        (ws_dir / "uploads" / "data.csv").write_text("a,b\n1,2", encoding="utf-8")

        from routers.workspace_files import list_workspace_tree, read_workspace_file

        tree = await list_workspace_tree(
            agent_id=AGENT_ID,
            path="",
            recursive=True,
            auth=_auth(),
        )
        paths = {f["path"] for f in tree["files"]}
        # Paths must be agent-relative (no `agents/{agent_id}/` prefix)
        assert "plan.md" in paths
        assert "uploads" in paths
        assert "uploads/data.csv" in paths
        assert not any(p.startswith("agents/") for p in paths if p)
        assert not any(p.startswith("workspaces/") for p in paths if p)

        # Every file path should read successfully via the file endpoint
        for entry in tree["files"]:
            if entry["type"] == "file":
                info = await read_workspace_file(
                    agent_id=AGENT_ID,
                    path=entry["path"],
                    auth=_auth(),
                )
                assert info["name"] == entry["name"]
                assert info["size"] == entry["size"]

    @pytest.mark.asyncio
    async def test_write_then_tree_then_read(self, workspace, monkeypatch):
        """After saveWorkspaceFile writes a workspace file, tree lists it and read returns content."""
        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        (workspace._mount / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import (
            WriteFileRequest,
            list_workspace_tree,
            read_workspace_file,
            write_workspace_file,
        )

        body = WriteFileRequest(path="notes.txt", content="hello world", tab="workspace")
        result = await write_workspace_file(agent_id=AGENT_ID, body=body, auth=_auth())
        assert result["status"] == "ok"
        # Backend returned path is user-root-relative; tree will show agent-relative
        assert result["path"] == f"agents/{AGENT_ID}/notes.txt"

        tree = await list_workspace_tree(
            agent_id=AGENT_ID,
            path="",
            recursive=True,
            auth=_auth(),
        )
        assert any(f["path"] == "notes.txt" and f["type"] == "file" for f in tree["files"])

        info = await read_workspace_file(agent_id=AGENT_ID, path="notes.txt", auth=_auth())
        assert info["content"] == "hello world"


# ===========================================================================
# TestMainAgentLayout
#
# The `main` agent inherits OpenClaw's default workspace setting, which points
# at the user-root `workspaces/` directory — NOT a per-agent subdir. Custom
# agents, by contrast, override workspace to `agents/{id}/`. This class covers
# the main-agent branch of `_agent_workspace_dir`.
# ===========================================================================


class TestMainAgentLayout:
    """Tests verifying main agent's workspace resolves to user-root workspaces/."""

    def test_agent_workspace_dir_main(self):
        """Main agent maps to the user-root workspaces/ directory."""
        from routers.workspace_files import _agent_workspace_dir

        assert _agent_workspace_dir("main") == "workspaces"

    def test_agent_workspace_dir_custom(self):
        """Custom agent maps to agents/{id}/."""
        from routers.workspace_files import _agent_workspace_dir

        assert _agent_workspace_dir("ember") == "agents/ember"
        assert _agent_workspace_dir(AGENT_ID) == f"agents/{AGENT_ID}"

    def test_list_config_files_main(self, tmp_path):
        """Config files for main agent are read from workspaces/ at user root."""
        ws = _make_workspace(tmp_path)
        ws_dir = tmp_path / USER_ID / "workspaces"
        ws_dir.mkdir(parents=True)
        (ws_dir / "SOUL.md").write_text("I am main", encoding="utf-8")
        (ws_dir / "MEMORY.md").write_text("Remember", encoding="utf-8")
        (ws_dir / "IDENTITY.md").write_text("Me", encoding="utf-8")
        (ws_dir / "TOOLS.md").write_text("Tools", encoding="utf-8")
        (ws_dir / "USER.md").write_text("User", encoding="utf-8")
        (ws_dir / "HEARTBEAT.md").write_text("Heartbeat", encoding="utf-8")
        # Non-allowlisted file should not appear
        (ws_dir / "random.json").write_text("{}", encoding="utf-8")

        from routers.workspace_files import _list_config_files

        result = _list_config_files(ws, USER_ID, "main")
        names = {f["name"] for f in result}
        assert names == {"SOUL.md", "MEMORY.md", "IDENTITY.md", "TOOLS.md", "USER.md", "HEARTBEAT.md"}
        assert all(f["type"] == "file" for f in result)

    def test_list_config_files_main_empty_when_no_workspaces_dir(self, tmp_path):
        """No workspaces/ dir yet -> empty config list for main (not an error)."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID).mkdir(parents=True)

        from routers.workspace_files import _list_config_files

        assert _list_config_files(ws, USER_ID, "main") == []

    @pytest.mark.asyncio
    async def test_read_workspace_file_main(self, workspace, monkeypatch):
        """Reading a workspace file for main reads from workspaces/ at user root."""
        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        ws_dir = workspace._mount / USER_ID / "workspaces"
        ws_dir.mkdir(parents=True)
        (ws_dir / "SOUL.md").write_text("main soul", encoding="utf-8")

        from routers.workspace_files import read_workspace_file

        info = await read_workspace_file(agent_id="main", path="SOUL.md", auth=_auth())
        assert info["name"] == "SOUL.md"
        assert info["content"] == "main soul"

    @pytest.mark.asyncio
    async def test_write_workspace_file_main_config_tab(self, workspace, monkeypatch):
        """Writing SOUL.md for main via tab=config lands in workspaces/SOUL.md."""
        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        (workspace._mount / USER_ID / "workspaces").mkdir(parents=True)

        from routers.workspace_files import WriteFileRequest, write_workspace_file

        body = WriteFileRequest(path="SOUL.md", content="I am main", tab="config")
        result = await write_workspace_file(agent_id="main", body=body, auth=_auth())
        assert result["status"] == "ok"
        assert result["path"] == "workspaces/SOUL.md"

        on_disk = workspace._mount / USER_ID / "workspaces" / "SOUL.md"
        assert on_disk.read_text() == "I am main"

    @pytest.mark.asyncio
    async def test_write_workspace_file_main_workspace_tab(self, workspace, monkeypatch):
        """Writing an arbitrary workspace file for main lands under workspaces/."""
        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        (workspace._mount / USER_ID / "workspaces").mkdir(parents=True)

        from routers.workspace_files import WriteFileRequest, write_workspace_file

        body = WriteFileRequest(path="plan.md", content="plan text", tab="workspace")
        result = await write_workspace_file(agent_id="main", body=body, auth=_auth())
        assert result["status"] == "ok"
        assert result["path"] == "workspaces/plan.md"

        assert (workspace._mount / USER_ID / "workspaces" / "plan.md").read_text() == "plan text"

    @pytest.mark.asyncio
    async def test_list_workspace_tree_main(self, workspace, monkeypatch):
        """list_workspace_tree for main returns entries from workspaces/ at user root."""
        monkeypatch.setattr("routers.workspace_files.get_workspace", lambda: workspace)
        ws_dir = workspace._mount / USER_ID / "workspaces"
        ws_dir.mkdir(parents=True)
        (ws_dir / "SOUL.md").write_text("soul", encoding="utf-8")
        (ws_dir / "notes").mkdir()
        (ws_dir / "notes" / "plan.md").write_text("plan", encoding="utf-8")

        from routers.workspace_files import list_workspace_tree

        tree = await list_workspace_tree(
            agent_id="main",
            path="",
            recursive=True,
            auth=_auth(),
        )
        paths = {f["path"] for f in tree["files"]}
        # Paths returned must be relative to workspaces/, not including workspaces/ prefix
        assert "SOUL.md" in paths
        assert "notes" in paths
        assert "notes/plan.md" in paths
        assert not any(p.startswith("workspaces/") for p in paths if p)

    def test_strip_agent_prefix_main(self):
        """_strip_agent_prefix strips workspaces/ prefix when agent_id=main."""
        from routers.workspace_files import _strip_agent_prefix

        entries = [
            {"name": "workspaces", "type": "dir", "path": "workspaces"},
            {"name": "SOUL.md", "type": "file", "path": "workspaces/SOUL.md"},
            {"name": "plan.md", "type": "file", "path": "workspaces/notes/plan.md"},
        ]
        out = _strip_agent_prefix(entries, "main")
        out_paths = [e["path"] for e in out]
        assert "" in out_paths  # the root itself
        assert "SOUL.md" in out_paths
        assert "notes/plan.md" in out_paths

    def test_strip_agent_prefix_custom(self):
        """_strip_agent_prefix strips agents/{id}/ prefix for custom agents."""
        from routers.workspace_files import _strip_agent_prefix

        entries = [
            {"name": AGENT_ID, "type": "dir", "path": f"agents/{AGENT_ID}"},
            {"name": "SOUL.md", "type": "file", "path": f"agents/{AGENT_ID}/SOUL.md"},
        ]
        out = _strip_agent_prefix(entries, AGENT_ID)
        out_paths = [e["path"] for e in out]
        assert "" in out_paths
        assert "SOUL.md" in out_paths

    def test_write_main_with_symlink_escape_rejected(self, tmp_path):
        """Symlink in workspaces/ pointing outside must be rejected for main agent."""
        import os

        ws = _make_workspace(tmp_path)
        ws_dir = tmp_path / USER_ID / "workspaces"
        ws_dir.mkdir(parents=True)
        target = tmp_path / USER_ID / "elsewhere.txt"
        target.write_text("original", encoding="utf-8")

        os.symlink("../elsewhere.txt", ws_dir / "evil")

        from routers.workspace_files import _write_file

        with pytest.raises(ValueError, match="escapes"):
            _write_file(ws, USER_ID, "main", "evil", "hacked", "workspace")

        assert target.read_text() == "original"
