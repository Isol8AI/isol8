# Control Dashboard V2 — Design

**Date:** 2026-02-28
**Goal:** Make the control dashboard functional by fixing RPC method names and building rich UI for the 5 core panels (Overview, Agents, Sessions, Logs, Config).

## Context

The frontend has 12 control panels that call the backend RPC proxy (`POST /container/rpc`), which forwards to the OpenClaw gateway via WebSocket. Currently all panels show errors because:
1. Some use wrong method names (e.g. `agents.get` doesn't exist)
2. Response shapes aren't handled correctly (gateway wraps data differently)
3. Panels render raw JSON instead of usable UI

## Scope (Frontend + Backend)

Backend change: upgrade handshake scopes to `operator.admin` so all methods work (config editing, session deletion, cron control, etc.).

### Core Panels (this pass)

| Panel | RPC Method | Response Shape | UI |
|-------|-----------|----------------|-----|
| Overview | `health` | `{ status, uptime, ... }` | Status card, uptime, instance/session counts |
| Agents | `agents.list` | `{ defaultId, agents[] }` | Agent list, file browser (read-only), tools, identity |
| Sessions | `sessions.list` | `{ sessions[] }` | Session list with key, model, timestamps |
| Logs | `logs.tail` | `{ file, lines[], cursor }` | Log viewer with level filters, timestamps |
| Config | `config.get` | `{ raw, hash }` | Read-only JSON viewer (edit requires admin scope) |

### Remaining 7 panels

Fix method names only, keep current UI for now.

## OpenClaw Gateway Method Reference (Correct Names)

| Dashboard Panel | Wrong Name | Correct Name | Scope |
|----------------|------------|--------------|-------|
| Channels | `channels.list` | `channels.status` | read |
| Instances | `instances.list` | N/A (use `node.list`) | read |
| Usage | `usage.summary` | `usage.status` / `usage.cost` | read |
| Skills | `skills.list` | `skills.status` | read |
| Nodes | `nodes.list` | `node.list` | read |

## Agent File System

The agent file editor in the real OpenClaw dashboard shows core files (SOUL.md, IDENTITY.md, TOOLS.md, etc.) and allows editing. For this pass we'll use `agents.list` to get agent info, then explore adding file read capability via the `agent` RPC or HTTP endpoints in a follow-up.

## Architecture

No changes to the RPC hook (`useContainerRpc`) or backend proxy. All changes are in the panel components — fix method names and properly destructure response payloads.
