"""Tests for TownAgentWsManager in-memory connection registry."""

from core.services.town_agent_ws import TownAgentWsManager


class TestTownAgentWsManager:
    def setup_method(self):
        self.manager = TownAgentWsManager()

    def test_register_and_lookup(self):
        self.manager.register("conn_1", "user_1", "lucky", "agent-uuid-1", "inst-uuid-1")
        conn = self.manager.get_by_connection("conn_1")
        assert conn is not None
        assert conn.agent_name == "lucky"
        assert conn.user_id == "user_1"
        assert conn.agent_id == "agent-uuid-1"
        assert conn.instance_id == "inst-uuid-1"

    def test_lookup_by_agent_name(self):
        self.manager.register("conn_1", "user_1", "lucky", "agent-uuid-1", "inst-uuid-1")
        conn_id = self.manager.get_agent_connection_id("lucky")
        assert conn_id == "conn_1"

    def test_is_agent_connected(self):
        assert not self.manager.is_agent_connected("lucky")
        self.manager.register("conn_1", "user_1", "lucky", "agent-uuid-1", "inst-uuid-1")
        assert self.manager.is_agent_connected("lucky")

    def test_unregister(self):
        self.manager.register("conn_1", "user_1", "lucky", "agent-uuid-1", "inst-uuid-1")
        self.manager.unregister("conn_1")
        assert not self.manager.is_agent_connected("lucky")
        assert self.manager.get_by_connection("conn_1") is None

    def test_unregister_nonexistent(self):
        # Should not raise
        self.manager.unregister("nonexistent")

    def test_connected_agents(self):
        self.manager.register("c1", "u1", "lucky", "a1", "i1")
        self.manager.register("c2", "u2", "bob", "a2", "i2")
        agents = self.manager.connected_agents()
        assert len(agents) == 2
        names = {a.agent_name for a in agents}
        assert names == {"lucky", "bob"}

    def test_get_by_connection_returns_none_for_unknown(self):
        assert self.manager.get_by_connection("nonexistent") is None

    def test_get_agent_connection_id_returns_none_for_unknown(self):
        assert self.manager.get_agent_connection_id("nonexistent") is None

    def test_register_replaces_existing_connection(self):
        """Re-registering the same agent_name with a new connection updates the mapping."""
        self.manager.register("conn_1", "user_1", "lucky", "a1", "i1")
        self.manager.register("conn_2", "user_1", "lucky", "a1", "i1")
        # New connection should be active
        assert self.manager.get_agent_connection_id("lucky") == "conn_2"
        conn = self.manager.get_by_connection("conn_2")
        assert conn is not None
        assert conn.agent_name == "lucky"

    def test_connected_agents_empty(self):
        assert self.manager.connected_agents() == []
