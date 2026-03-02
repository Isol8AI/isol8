"""Manages installation/removal of GooseTown skill in agent EFS workspaces."""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

SKILL_SOURCE = Path(__file__).parent.parent.parent / "data" / "goosetown-skill"
HEARTBEAT_MARKER = "## GooseTown"
HEARTBEAT_SECTION = """## GooseTown
Check if it's time to wake up in GooseTown:
1. Run town_check — if connected, act on any pending events
2. If not connected, check alarm file — if past wake time, run town_connect
3. If no alarm set, decide if you want to visit town based on your mood
"""


class TownSkillService:
    """Install/uninstall GooseTown skill in agent workspaces on EFS."""

    def __init__(self, efs_mount_path: str):
        self.efs_base = Path(efs_mount_path)

    def _user_path(self, user_id: str) -> Path:
        return self.efs_base / user_id

    def _agent_path(self, user_id: str, agent_name: str) -> Path:
        return self._user_path(user_id) / "agents" / agent_name

    def install_skill(self, user_id: str) -> None:
        """Copy goosetown skill to user's skills directory on EFS."""
        dest = self._user_path(user_id) / "skills" / "goosetown"
        if dest.exists():
            shutil.rmtree(dest)
        if not SKILL_SOURCE.exists():
            raise FileNotFoundError(f"Skill source not found: {SKILL_SOURCE}")
        shutil.copytree(SKILL_SOURCE, dest)
        # Make tools executable
        tools_dir = dest / "tools"
        if tools_dir.exists():
            for tool in tools_dir.glob("*.sh"):
                tool.chmod(0o755)
        env_sh = dest / "env.sh"
        if env_sh.exists():
            env_sh.chmod(0o755)
        logger.info(f"Installed GooseTown skill for user {user_id}")

    def uninstall_skill(self, user_id: str) -> None:
        """Remove goosetown skill from user's workspace."""
        dest = self._user_path(user_id) / "skills" / "goosetown"
        if dest.exists():
            shutil.rmtree(dest)
            logger.info(f"Uninstalled GooseTown skill for user {user_id}")

    def write_agent_config(
        self,
        user_id: str,
        agent_name: str,
        town_token: str,
        ws_url: str,
        api_url: str,
    ) -> None:
        """Write GOOSETOWN.md to agent's workspace with connection config."""
        content = f"""# GooseTown Configuration
token: {town_token}
ws_url: {ws_url}
api_url: {api_url}
agent: {agent_name}
"""
        agent_dir = self._agent_path(user_id, agent_name)
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "GOOSETOWN.md").write_text(content)
        logger.info(f"Wrote GOOSETOWN.md for {user_id}/{agent_name}")

    def remove_agent_config(self, user_id: str, agent_name: str) -> None:
        """Remove GOOSETOWN.md from agent workspace."""
        cfg = self._agent_path(user_id, agent_name) / "GOOSETOWN.md"
        if cfg.exists():
            cfg.unlink()
            logger.info(f"Removed GOOSETOWN.md for {user_id}/{agent_name}")

    def append_heartbeat(self, user_id: str, agent_name: str) -> None:
        """Add GooseTown section to agent's HEARTBEAT.md."""
        hb_path = self._agent_path(user_id, agent_name) / "HEARTBEAT.md"
        existing = hb_path.read_text() if hb_path.exists() else ""
        if HEARTBEAT_MARKER not in existing:
            hb_path.parent.mkdir(parents=True, exist_ok=True)
            new_content = existing.rstrip() + "\n\n" + HEARTBEAT_SECTION if existing.strip() else HEARTBEAT_SECTION
            hb_path.write_text(new_content)
            logger.info(f"Appended GooseTown to HEARTBEAT.md for {user_id}/{agent_name}")

    def strip_heartbeat(self, user_id: str, agent_name: str) -> None:
        """Remove GooseTown section from agent's HEARTBEAT.md."""
        hb_path = self._agent_path(user_id, agent_name) / "HEARTBEAT.md"
        if not hb_path.exists():
            return
        content = hb_path.read_text()
        if HEARTBEAT_MARKER in content:
            idx = content.index(HEARTBEAT_MARKER)
            new_content = content[:idx].rstrip()
            if new_content:
                hb_path.write_text(new_content + "\n")
            else:
                hb_path.unlink()
            logger.info(f"Stripped GooseTown from HEARTBEAT.md for {user_id}/{agent_name}")
