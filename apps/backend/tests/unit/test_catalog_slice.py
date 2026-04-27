import pytest

from core.services.catalog_slice import (
    extract_agent_slice,
    filter_cron_jobs_for_agent,
    strip_user_specific_fields,
)


FULL_OPENCLAW_JSON = {
    "defaultAgentId": "agent_abc",
    # Matches upstream OpenClaw schema (openclaw/src/config/zod-schema.agents.ts):
    # agents: { defaults?, list?: AgentEntry[] }
    "agents": {
        "defaults": {"workspace": "/workspace/root"},
        "list": [
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
    },
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


def test_extract_agent_slice_tolerates_non_dict_entries_in_agents_list():
    """Live prod regression: publish crashed with AttributeError when
    ``agents.list`` had a bare string alongside the dict entries."""
    cfg = {
        "agents": {
            "list": [
                "some-stray-string",
                {"id": "agent_abc", "name": "Pitch", "skills": ["web-search"]},
                None,
            ],
        },
        "plugins": {},
        "tools": {},
    }
    slice_ = extract_agent_slice(cfg, "agent_abc")
    assert slice_["agent"]["name"] == "Pitch"


def test_extract_agent_slice_raises_when_agents_missing_or_malformed():
    """Missing agents key, non-dict/non-list agents, or missing .list → empty."""
    for cfg in [
        {"plugins": {}, "tools": {}},
        {"agents": None, "plugins": {}, "tools": {}},
        {"agents": [], "plugins": {}, "tools": {}},  # empty flat list
        {"agents": {"defaults": {"workspace": "/x"}}, "plugins": {}, "tools": {}},
    ]:
        with pytest.raises(KeyError):
            extract_agent_slice(cfg, "agent_abc")


def test_extract_agent_slice_accepts_legacy_flat_list():
    """Codex P2 regression: admins whose configs are still in the legacy flat
    shape (``agents: [...]``) must still be able to publish. The write path
    in config_patcher migrates the shape on deploy; the read path here
    tolerates it so we don't regress working admins while they wait for a
    migration write."""
    cfg = {
        "agents": [{"id": "agent_abc", "name": "Pitch", "skills": ["web-search"]}],
        "plugins": {"memory": {"enabled": True}},
        "tools": {"allowed": ["web-search"]},
    }
    slice_ = extract_agent_slice(cfg, "agent_abc")
    assert slice_["agent"]["name"] == "Pitch"
    assert slice_["plugins"] == {"memory": {"enabled": True}}


def test_strip_user_specific_fields_removes_model():
    agent = dict(FULL_OPENCLAW_JSON["agents"]["list"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "model" not in cleaned


def test_strip_user_specific_fields_removes_channels():
    agent = dict(FULL_OPENCLAW_JSON["agents"]["list"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "channels" not in cleaned


def test_strip_user_specific_fields_removes_workspace_path():
    agent = dict(FULL_OPENCLAW_JSON["agents"]["list"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "workspace" not in cleaned


def test_strip_user_specific_fields_removes_id():
    agent = dict(FULL_OPENCLAW_JSON["agents"]["list"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "id" not in cleaned


def test_strip_user_specific_fields_keeps_behavioral_flags():
    agent = dict(FULL_OPENCLAW_JSON["agents"]["list"][0])
    cleaned = strip_user_specific_fields(agent)
    assert cleaned["thinkingDefault"] is True
    assert cleaned["skills"] == ["web-search", "email-send"]
    assert cleaned["cron"] == [{"schedule": "0 8 * * *", "workflow": "morning-briefing"}]


def test_strip_user_specific_fields_removes_agentDir():
    """agentDir is keyed to the publisher's agent id. If carried into the slice,
    a self-deploy collides with the publisher's existing agent and trips
    OpenClaw's ``DuplicateAgentDirError`` (config rejected, deploy invisible)."""
    agent = {
        "id": "pulse",
        "name": "Pulse",
        "agentDir": "/home/node/.openclaw/agents/pulse/agent",
        "skills": ["web-search"],
    }
    cleaned = strip_user_specific_fields(agent)
    assert "agentDir" not in cleaned
    assert cleaned["skills"] == ["web-search"]


# ---- filter_cron_jobs_for_agent ----


def test_filter_cron_jobs_keeps_only_matching_agent():
    jobs = [
        {"id": "j1", "agentId": "agent_abc", "name": "Daily"},
        {"id": "j2", "agentId": "agent_xyz", "name": "Other"},
        {"id": "j3", "agentId": "agent_abc", "name": "Weekly"},
    ]
    out = filter_cron_jobs_for_agent(jobs, "agent_abc")
    assert [j["name"] for j in out] == ["Daily", "Weekly"]


def test_filter_cron_jobs_strips_runtime_and_user_specific_fields():
    """``id``, ``sessionKey``, ``state``, ``createdAtMs``, ``updatedAtMs``
    are regenerated at deploy and must not leak through the slice."""
    jobs = [
        {
            "id": "j1",
            "agentId": "agent_abc",
            "sessionKey": "agent:agent_abc:user_publisher",
            "name": "Daily",
            "schedule": {"kind": "cron", "expr": "0 9 * * *", "tz": "UTC"},
            "payload": {"kind": "agentTurn", "message": "Run morning brief"},
            "delivery": {"mode": "announce", "channel": "telegram"},
            "createdAtMs": 1700000000000,
            "updatedAtMs": 1700000060000,
            "state": {"nextRunAtMs": 1700000120000, "lastRunAtMs": 1700000000000},
            "enabled": True,
        }
    ]
    [out] = filter_cron_jobs_for_agent(jobs, "agent_abc")
    assert "id" not in out
    assert "sessionKey" not in out
    assert "state" not in out
    assert "createdAtMs" not in out
    assert "updatedAtMs" not in out
    # Behavioral fields preserved.
    assert out["agentId"] == "agent_abc"
    assert out["name"] == "Daily"
    assert out["schedule"] == {"kind": "cron", "expr": "0 9 * * *", "tz": "UTC"}
    assert out["payload"]["message"] == "Run morning brief"
    assert out["delivery"] == {"mode": "announce", "channel": "telegram"}
    assert out["enabled"] is True


def test_filter_cron_jobs_skips_non_dict_entries():
    """Defensive: same posture as the agents-list reader. Stray strings or
    None entries from hand-edits don't crash; they're skipped."""
    jobs = [
        "stray-string",
        None,
        {"id": "j1", "agentId": "agent_abc", "name": "Keep"},
    ]
    out = filter_cron_jobs_for_agent(jobs, "agent_abc")
    assert [j["name"] for j in out] == ["Keep"]


def test_filter_cron_jobs_empty_input_returns_empty():
    assert filter_cron_jobs_for_agent([], "agent_abc") == []
