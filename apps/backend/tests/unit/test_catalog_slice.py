import pytest

from core.services.catalog_slice import (
    extract_agent_slice,
    strip_user_specific_fields,
)


FULL_OPENCLAW_JSON = {
    "defaultAgentId": "agent_abc",
    "agents": [
        {
            "id": "agent_abc",
            "workspace": ".openclaw/workspaces/agent_abc",
            "name": "Pitch",
            "model": "qwen/qwen3-vl-235b",
            "thinkingDefault": True,
            "skills": ["web-search", "email-send"],
            "channels": {"telegram": {"bot_token": "SECRET"}},
            "cron": [{"schedule": "0 8 * * *", "workflow": "morning-briefing"}],
        },
        {"id": "agent_zzz", "name": "Other"},
    ],
    "plugins": {"memory": {"enabled": True}},
    "tools": {"allowed": ["web-search", "email-send"]},
}


def test_extract_agent_slice_returns_only_named_agent():
    slice_ = extract_agent_slice(FULL_OPENCLAW_JSON, "agent_abc")
    assert slice_["agent"]["name"] == "Pitch"


def test_extract_agent_slice_includes_required_plugins_and_tools():
    slice_ = extract_agent_slice(FULL_OPENCLAW_JSON, "agent_abc")
    assert slice_["plugins"] == {"memory": {"enabled": True}}
    assert slice_["tools"] == {"allowed": ["web-search", "email-send"]}


def test_extract_agent_slice_missing_agent_raises():
    with pytest.raises(KeyError):
        extract_agent_slice(FULL_OPENCLAW_JSON, "agent_does_not_exist")


def test_strip_user_specific_fields_removes_model():
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "model" not in cleaned


def test_strip_user_specific_fields_removes_channels():
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "channels" not in cleaned


def test_strip_user_specific_fields_removes_workspace_path():
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "workspace" not in cleaned


def test_strip_user_specific_fields_removes_id():
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "id" not in cleaned


def test_strip_user_specific_fields_keeps_behavioral_flags():
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert cleaned["thinkingDefault"] is True
    assert cleaned["skills"] == ["web-search", "email-send"]
    assert cleaned["cron"] == [{"schedule": "0 8 * * *", "workflow": "morning-briefing"}]
