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
