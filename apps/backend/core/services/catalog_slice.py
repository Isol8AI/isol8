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
# Cron-job fields stripped at slice time. Each is either runtime state (set
# by OpenClaw on first execution) or user-specific provenance regenerated
# at deploy. Schema reference: openclaw/src/config/types.cron.ts +
# the persisted shape in {owner_id}/cron/jobs.json.
_STRIPPED_CRON_KEYS = frozenset({"id", "sessionKey", "state", "createdAtMs", "updatedAtMs"})
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


def filter_cron_jobs_for_agent(
    all_jobs: list[Any],
    agent_id: str,
) -> list[dict[str, Any]]:
    """Keep cron jobs whose ``agentId`` matches ``agent_id``; strip runtime +
    user-specific fields that must be regenerated at deploy.

    Persisted shape (one entry of ``jobs.json#/jobs``)::

        {
          "id":            <UUID>,         # regenerated on deploy
          "agentId":       <agent_id>,     # rewritten on deploy
          "sessionKey":    "agent:{id}:{userId}",  # regenerated on deploy
          "name":          ...,
          "description":   ...,
          "enabled":       bool,
          "schedule":      {kind, expr, tz},
          "sessionTarget": ...,
          "wakeMode":      ...,
          "payload":       {kind, message, ...},
          "delivery":      {mode, channel, accountId?},  # may reference a
                                                          # channel the deployer
                                                          # hasn't bound yet —
                                                          # carried as-is so
                                                          # the deployer can
                                                          # bind + flip the
                                                          # job on later
          "createdAtMs":   ...,            # regenerated on deploy
          "updatedAtMs":   ...,            # regenerated on deploy
          "state":         {nextRunAtMs,...} # OpenClaw recomputes from schedule
        }

    Non-dict entries are skipped silently (the persisted file has been
    observed with stray strings from hand-edits, same defensive posture as
    the agents list).
    """
    out: list[dict[str, Any]] = []
    for job in all_jobs:
        if not isinstance(job, dict):
            continue
        if job.get("agentId") != agent_id:
            continue
        clean = copy.deepcopy(job)
        for k in _STRIPPED_CRON_KEYS:
            clean.pop(k, None)
        out.append(clean)
    return out


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
