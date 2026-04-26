"""Pure functions for slicing an agent's entry out of an openclaw.json and
stripping user/tier-specific fields that must not leak into the catalog.

User/tier-specific fields never go in a catalog package:
  - model (user's tier picks a default at runtime)
  - channels (per-user credentials)
  - workspace (path; the deploy generates a new one)
  - id (regenerated per-deploy)

Behavioral fields stay:
  - skills list, plugins config, tools allowlist, cron, thinkingDefault, etc.
"""

from __future__ import annotations

import copy
from typing import Any

_STRIPPED_KEYS = frozenset({"model", "channels", "workspace", "id", "agentDir"})
# ``agentDir`` is per-agent-id (NOT per-user — the path is in-container
# uniform). Carrying the publisher's value into the slice means the deployed
# agent inherits a path keyed to the publisher's agent id, which:
#   - on self-deploy, collides with the publisher's existing agent and
#     trips OpenClaw's ``DuplicateAgentDirError`` (zod-rejected config →
#     hot-reload fails → new agent never appears in the running container);
#   - on cross-user deploy, dumps the new agent's data into a directory
#     keyed to the wrong id.
# Stripping it lets OpenClaw auto-derive ``/home/node/.openclaw/agents/{id}/agent``
# (see openclaw/src/config/agent-dirs.ts:60-79).


def strip_user_specific_fields(agent_entry: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(agent_entry)
    for key in _STRIPPED_KEYS:
        result.pop(key, None)
    return result


def _agents_list(openclaw_json: dict[str, Any]) -> list[Any]:
    """Return the agent-entry array from an openclaw.json.

    OpenClaw's config schema (zod: ``openclaw/src/config/zod-schema.agents.ts``):

        agents: { defaults: AgentDefaults, list: AgentEntry[] }

    Early versions of the Isol8 catalog code read ``config["agents"]`` as if it
    were a flat list — that worked only for configs that didn't exist, which
    is why it went unnoticed until the first real publish attempt. The write
    path (``config_patcher.apply_deploy_mutation``) migrates flat-list configs
    to the nested shape on deploy; this reader accepts BOTH so an admin with a
    legacy config can still publish without first triggering a migration.
    """
    agents = openclaw_json.get("agents")
    if isinstance(agents, list):
        return agents  # legacy flat shape — tolerated for read/publish
    if not isinstance(agents, dict):
        return []
    lst = agents.get("list")
    return lst if isinstance(lst, list) else []


def extract_agent_slice(openclaw_json: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """Return a dict with the sliced agent entry plus the required plugins/tools
    from the publisher's config. Raises KeyError if the agent_id isn't present.

    Also tolerates stray non-dict entries in ``agents.list`` (bare strings have
    been observed from hand-editing / partial runtime writes) — skip anything
    that isn't a dict rather than crashing with AttributeError.
    """
    agents = _agents_list(openclaw_json)
    matching = [a for a in agents if isinstance(a, dict) and a.get("id") == agent_id]
    if not matching:
        raise KeyError(f"agent {agent_id!r} not found in openclaw.json")
    agent_entry = matching[0]

    return {
        "agent": strip_user_specific_fields(agent_entry),
        "plugins": copy.deepcopy(openclaw_json.get("plugins") or {}),
        "tools": copy.deepcopy(openclaw_json.get("tools") or {}),
    }
