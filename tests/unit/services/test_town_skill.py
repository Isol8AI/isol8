"""Tests for TownSkillService."""

import pytest
from core.services.town_skill import TownSkillService, HEARTBEAT_MARKER


@pytest.fixture
def efs_tmp(tmp_path):
    """Create a temporary EFS-like directory structure."""
    return tmp_path


@pytest.fixture
def skill_service(efs_tmp):
    return TownSkillService(str(efs_tmp))


class TestTownSkillService:
    def test_install_skill(self, skill_service, efs_tmp):
        """Install copies skill files to user workspace."""
        skill_service.install_skill("user_1")
        dest = efs_tmp / "user_1" / "skills" / "goosetown"
        assert dest.exists()
        assert (dest / "skill.json").exists()
        assert (dest / "tools").exists()

    def test_install_skill_overwrites(self, skill_service, efs_tmp):
        """Installing twice overwrites cleanly."""
        skill_service.install_skill("user_1")
        skill_service.install_skill("user_1")
        dest = efs_tmp / "user_1" / "skills" / "goosetown"
        assert dest.exists()

    def test_uninstall_skill(self, skill_service, efs_tmp):
        """Uninstall removes skill directory."""
        skill_service.install_skill("user_1")
        skill_service.uninstall_skill("user_1")
        dest = efs_tmp / "user_1" / "skills" / "goosetown"
        assert not dest.exists()

    def test_uninstall_nonexistent(self, skill_service):
        """Uninstalling when not installed doesn't raise."""
        skill_service.uninstall_skill("user_no_skill")

    def test_write_agent_config(self, skill_service, efs_tmp):
        """Write GOOSETOWN.md to agent workspace."""
        skill_service.write_agent_config(
            "user_1", "lucky", "tok_123", "wss://ws.example.com", "https://api.example.com"
        )
        cfg = efs_tmp / "user_1" / "agents" / "lucky" / "GOOSETOWN.md"
        assert cfg.exists()
        content = cfg.read_text()
        assert "token: tok_123" in content
        assert "ws_url: wss://ws.example.com" in content
        assert "agent: lucky" in content

    def test_remove_agent_config(self, skill_service, efs_tmp):
        """Remove GOOSETOWN.md from agent workspace."""
        skill_service.write_agent_config(
            "user_1", "lucky", "tok_123", "wss://ws.example.com", "https://api.example.com"
        )
        skill_service.remove_agent_config("user_1", "lucky")
        cfg = efs_tmp / "user_1" / "agents" / "lucky" / "GOOSETOWN.md"
        assert not cfg.exists()

    def test_remove_nonexistent_config(self, skill_service):
        """Removing nonexistent config doesn't raise."""
        skill_service.remove_agent_config("user_x", "agent_x")

    def test_append_heartbeat(self, skill_service, efs_tmp):
        """Append GooseTown section to HEARTBEAT.md."""
        # Create agent dir with existing HEARTBEAT.md
        agent_dir = efs_tmp / "user_1" / "agents" / "lucky"
        agent_dir.mkdir(parents=True)
        (agent_dir / "HEARTBEAT.md").write_text("## Existing\nDo something\n")

        skill_service.append_heartbeat("user_1", "lucky")
        content = (agent_dir / "HEARTBEAT.md").read_text()
        assert "## Existing" in content
        assert HEARTBEAT_MARKER in content
        assert "TOWN_STATUS.md" in content

    def test_append_heartbeat_empty(self, skill_service, efs_tmp):
        """Append to nonexistent HEARTBEAT.md creates it."""
        skill_service.append_heartbeat("user_1", "bob")
        hb = efs_tmp / "user_1" / "agents" / "bob" / "HEARTBEAT.md"
        assert hb.exists()
        assert HEARTBEAT_MARKER in hb.read_text()

    def test_append_heartbeat_idempotent(self, skill_service, efs_tmp):
        """Appending twice doesn't duplicate."""
        skill_service.append_heartbeat("user_1", "lucky")
        skill_service.append_heartbeat("user_1", "lucky")
        hb = efs_tmp / "user_1" / "agents" / "lucky" / "HEARTBEAT.md"
        assert hb.read_text().count(HEARTBEAT_MARKER) == 1

    def test_strip_heartbeat(self, skill_service, efs_tmp):
        """Strip removes GooseTown section."""
        agent_dir = efs_tmp / "user_1" / "agents" / "lucky"
        agent_dir.mkdir(parents=True)
        (agent_dir / "HEARTBEAT.md").write_text("## Existing\nDo stuff\n\n## GooseTown\nTown stuff\n")

        skill_service.strip_heartbeat("user_1", "lucky")
        content = (agent_dir / "HEARTBEAT.md").read_text()
        assert "## Existing" in content
        assert HEARTBEAT_MARKER not in content

    def test_strip_heartbeat_only_section(self, skill_service, efs_tmp):
        """Strip removes file if GooseTown was the only section."""
        agent_dir = efs_tmp / "user_1" / "agents" / "lucky"
        agent_dir.mkdir(parents=True)
        (agent_dir / "HEARTBEAT.md").write_text("## GooseTown\nTown stuff\n")

        skill_service.strip_heartbeat("user_1", "lucky")
        hb = agent_dir / "HEARTBEAT.md"
        assert not hb.exists()

    def test_strip_nonexistent(self, skill_service):
        """Stripping nonexistent file doesn't raise."""
        skill_service.strip_heartbeat("user_x", "agent_x")
