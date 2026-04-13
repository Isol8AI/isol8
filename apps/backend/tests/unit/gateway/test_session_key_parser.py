"""Tests for _parse_session_key pure function."""

import os

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from core.gateway.connection_pool import _parse_session_key  # noqa: E402


@pytest.mark.parametrize(
    "session_key,expected",
    [
        # Personal webchat
        (
            "agent:main:main",
            {"agent_id": "main", "source": "webchat"},
        ),
        # Org webchat — parts[2] is a Clerk user_id
        (
            "agent:main:user_2abc123",
            {"agent_id": "main", "source": "webchat", "member_id": "user_2abc123"},
        ),
        # Channel DM (per-account-channel-peer)
        (
            "agent:sales:telegram:sales:direct:99999",
            {
                "agent_id": "sales",
                "source": "dm",
                "channel": "telegram",
                "peer_id": "99999",
            },
        ),
        # Channel group
        (
            "agent:main:telegram:group:-1001234567890",
            {
                "agent_id": "main",
                "source": "group",
                "channel": "telegram",
                "group_id": "-1001234567890",
            },
        ),
        # Group with topic (Telegram forum)
        (
            "agent:main:telegram:group:-1001234567890:topic:42",
            {
                "agent_id": "main",
                "source": "group",
                "channel": "telegram",
                "group_id": "-1001234567890",
            },
        ),
        # Slack channel
        (
            "agent:main:slack:channel:C123ABC",
            {
                "agent_id": "main",
                "source": "channel",
                "channel": "slack",
                "channel_id": "C123ABC",
            },
        ),
        # Slack thread
        (
            "agent:main:slack:channel:C123ABC:thread:1234.5678",
            {
                "agent_id": "main",
                "source": "channel",
                "channel": "slack",
                "channel_id": "C123ABC",
            },
        ),
        # Cron chat session
        (
            "agent:main:cron:dfb80362-1cdb-4089-b778-27a5f51d765a",
            {"agent_id": "main", "source": "cron", "cron_id": "dfb80362-1cdb-4089-b778-27a5f51d765a"},
        ),
        # Cron run event (longer key)
        (
            "agent:main:cron:dfb80362-1cdb-4089-b778-27a5f51d765a:run:d89",
            {"agent_id": "main", "source": "cron", "cron_id": "dfb80362-1cdb-4089-b778-27a5f51d765a"},
        ),
        # Cron with no ID (just "cron" at position 2)
        (
            "agent:sales:cron",
            {"agent_id": "sales", "source": "cron"},
        ),
        # Malformed
        ("garbage", {}),
        ("", {}),
        # Sub-agent webchat (3 parts, parts[2] == main)
        ("agent:research_subagent:main", {"agent_id": "research_subagent", "source": "webchat"}),
    ],
)
def test_parse_session_key(session_key, expected):
    result = _parse_session_key(session_key)
    assert result == expected


def test_cron_session_is_not_webchat():
    """Cron sessions must not be classified as webchat — their events should
    not be forwarded to frontends (a cron chat.final would terminate an
    active user's streaming session)."""
    result = _parse_session_key("agent:main:cron:dfb80362-1cdb-4089-b778-27a5f51d765a")
    assert result["source"] == "cron"
    assert result["source"] not in ("webchat", "dm", "group", "channel")
    assert "member_id" not in result


def test_group_key_does_not_return_literal_channel_as_member_id():
    """Regression test for the pre-existing parser bug where group session
    keys wrote member:telegram:{period}. The new parser must NOT expose
    'telegram' (or any channel name) as a member_id anywhere."""
    result = _parse_session_key("agent:main:telegram:group:-100123")
    assert result.get("source") == "group"
    assert "member_id" not in result
