# Multi-user channels design (OpenClaw 4.5)

**Date:** 2026-04-07
**Status:** Spec — awaiting user review before implementation plan
**Scope:** Make Telegram, Discord, and Slack channels work correctly for orgs with multiple members on Isol8 running OpenClaw `2026.4.5`. Drop WhatsApp.

---

## Problem

Isol8 runs one OpenClaw container per "owner" (a personal Clerk user OR a Clerk org). Channels (Telegram, Discord, Slack) are configured on that container. Today three things are broken or missing:

1. **DM session collapsing.** OpenClaw's default `session.dmScope` is `"main"`, which collapses every DM (regardless of sender) into one shared session. If two org members DM the same Telegram bot, they share one conversation context — they see each other's history. Isol8 never sets `session.dmScope`, so all containers run with the unsafe default.

2. **No per-member billing for channel-driven traffic.** OpenClaw broadcasts `chat.final` events over the operator WebSocket only when `isControlUiVisible` is true (`auto-reply/reply/agent-runner-execution.ts:541-552`), and that flag is true only for `webchat`. Channel-driven runs (Telegram, Discord, Slack) never trigger Isol8's existing billing path. **Channel usage is currently unbilled entirely.**

3. **No per-agent bot model.** Channels in `ChannelsPanel.tsx` are configured at the container level — there's no concept of "@AcmeMainBot routes to the main agent, @AcmeSalesBot routes to the sales agent." All channel traffic goes to the default agent.

There's also a pre-existing parser bug: `connection_pool.py:307`'s heuristic `parts[2] if parts[2] != "main" else self.user_id` writes `member:telegram:{period}` for group session keys (where `parts[2]` is the literal string `"telegram"`). This is fixed as a side effect of the new parser, not as a separate task.

## Goal

After this work, an org can run multiple per-agent channel bots on a shared container, members can self-link their identities once per bot via a paste-the-code flow, every DM message is billed to the correct Clerk member, and group/channel/webchat behavior continues to work as it does today (groups bill to the org, org webchat bills per-member, personal webchat bills to the user).

WhatsApp is removed from the codebase entirely.

## Non-goals

- **Per-message member attribution for groups.** OpenClaw bundles all senders in a group into one session key; the per-message `from.id` lives inside the session message store, not in the key. Group usage continues to bill to the org as a whole.
- **Webhook ingress mode for any channel.** The OpenClaw container is in a private subnet; long polling (Telegram) and persistent WebSocket (Discord, Slack Socket Mode) are the only viable transport patterns and OpenClaw handles them natively. We never expose public ingress URLs to OpenClaw containers.
- **Multi-workspace Slack distribution.** v1 supports one Slack app per agent installed in one workspace. B2B distribution where customers install your Slack app into their workspace is a follow-up.
- **Recovery UI for orphaned `channel-links` rows.** Sweep happens automatically on bot delete, member delete, and container delete; manual recovery UI is unnecessary.
- **Per-message user-id forwarding from Isol8 → OpenClaw on the operator path.** The current model (one operator WS per owner) is preserved.
- **Lifecycle/end event deduplication via runId LRU.** Pre-existing risk in today's webchat path; not a regression introduced by this work.
- **Bot health monitoring beyond `channels.status`.** Existing RPC is sufficient for v1.
- **Automated E2E specs for the channel flows.** Manual checklist only; we can add E2E coverage after dev verification.
- **Integration tests in `tests/integration/`.** Empty directory today; we don't introduce the first integration test as part of this work. Defer until we know which parts are flaky in dev.

---

## Architecture

The system has three top-level components (frontend, backend, OpenClaw container). All three exist today; this work adds new files and modifies existing ones inside the frontend and backend, and writes new fields into the OpenClaw container's `openclaw.json` (no OpenClaw code changes). **New files are marked with ★ in the diagram.**

```
                  ┌──────────────────────────────────────────────┐
                  │          Frontend (Next.js)                  │
                  │                                              │
                  │  Agents tab → AgentDetail → ChannelsSection  │
                  │     ├─ Bot setup wizard (admin only)          │
                  │     ├─ Allowlist viewer (admin only)          │
                  │     └─ "Tier required" upsell (free tier)    │
                  │                                              │
                  │  Settings → My Channels                      │
                  │     ├─ Personal user: shows existing links + │
                  │     │   admin "+ Set up bot" entry            │
                  │     └─ Org member: list bots, self-link      │
                  │                                              │
                  │  Shared: BotSetupWizard (mode: create │ link) │
                  └──────────────────┬───────────────────────────┘
                                     │ REST (Clerk JWT)
                                     ▼
              ┌─────────────────────────────────────────────┐
              │       Isol8 Backend (FastAPI)                │
              │                                              │
              │  routers/config.py  ★NEW                     │
              │     PATCH /api/v1/config                     │
              │       (replaces frontend OpenClaw RPC patch) │
              │                                              │
              │  routers/channels.py  (existing, extended)   │
              │     POST /channels/link/{provider}/start     │
              │     POST /channels/link/{provider}/complete  │
              │     DELETE /channels/link/{provider}/{...}   │
              │     GET /channels/links/me                   │
              │                                              │
              │  core/services/                              │
              │     config_patcher.py  (existing +           │
              │       ★ append_to_openclaw_config_list       │
              │       ★ remove_from_openclaw_config_list     │
              │       ★ delete_openclaw_config_path)         │
              │     ★ channel_link_service.py                │
              │       (private _read_pairing_file helper)    │
              │                                              │
              │  core/gateway/connection_pool.py             │
              │     ★ updated _handle_message: lifecycle/end │
              │     ★ updated _record_usage_from_session     │
              │       (new parser, async member resolve)     │
              │                                              │
              │  core/repositories/                          │
              │     ★ channel_link_repo.py                   │
              │                                              │
              │  models/ (DynamoDB)                          │
              │     ★ channel_link.py table schema           │
              └──────────────────┬──────────────────────────┘
                                 │ EFS file write + chokidar
                                 ▼
              ┌────────────────────────────────────────────┐
              │   OpenClaw container (per owner)            │
              │                                            │
              │   /mnt/efs/users/{owner_id}/                │
              │     ├─ openclaw.json                       │
              │     │   session.dmScope:                    │
              │     │     "per-account-channel-peer"        │
              │     │   channels.<provider>.enabled: true   │
              │     │   channels.<provider>.accounts.       │
              │     │     <agentId>.{botToken,dmPolicy,     │
              │     │       allowFrom}                      │
              │     │   bindings: [...]                     │
              │     │                                       │
              │     └─ .openclaw/credentials/               │
              │         ├─ telegram-pairing.json           │
              │         ├─ discord-pairing.json            │
              │         └─ slack-pairing.json              │
              │                                            │
              │   Channel plugin running per accountId,    │
              │   inbound DMs hit OpenClaw's pairing flow, │
              │   per-account-channel-peer keys sessions   │
              │   by individual sender                      │
              └────────────────────────────────────────────┘
```

### Frontend surfaces

- **Agents tab → AgentDetail → Channels section.** Per-agent admin home for bot config. Lists the bots attached to this agent, with add/edit/delete (admin only). Replaces the standalone `ChannelsPanel.tsx` from the control sidebar — that file is removed.
- **Settings → My Channels.** Per-user identity-link management. Lists every bot in the user's container (grouped by provider), with the calling user's link status per bot. Personal users (always admin) also see "+ Set up new bot" entries per provider that open the wizard. Org non-admin members only see Link buttons.
- **`BotSetupWizard.tsx`.** Shared component invoked from three places: Agents → ChannelsSection (admin add bot), Settings → My Channels (member self-link or personal admin add bot), and the first-time onboarding prompt after the auto-created `main` agent. Takes a `mode` prop: `"create"` shows the token paste step before the pairing-code step; `"link-only"` jumps straight to the pairing-code step.

### Backend changes summary

- **New REST endpoint `PATCH /api/v1/config`** (`routers/config.py`). Wraps `patch_openclaw_config`. Derives `owner_id` from `AuthContext`. Requires `org_admin` for org context. Tier-gates channel-related fields. Replaces the frontend's direct use of OpenClaw's `config.patch` RPC, unifying all config writes through one EFS-write code path.
- **Three new endpoints under `routers/channels.py`** for the link flow: start, complete, delete, plus a `GET /channels/links/me` for the Settings page.
- **New `channel_link_service.py`** orchestrates the link flow: reads the EFS pairing file to extract the platform user ID, calls `append_to_openclaw_config_list` to update allowFrom, writes the link row to DynamoDB.
- **Three new helpers in `config_patcher.py`**, all using the same locked read-modify-write pattern as the existing `patch_openclaw_config`:
  - `append_to_openclaw_config_list(owner_id, path, value)` — appends `value` to the list at `path`. Dedup-aware (no-op if value already present).
  - `remove_from_openclaw_config_list(owner_id, path, predicate)` — removes any list entries matching `predicate`. `predicate` is a callable so it can match by value equality (for `allowFrom` strings) or by structural match (for `bindings` dicts where we want to find `{match: {channel, accountId}}` matches).
  - `delete_openclaw_config_path(owner_id, path)` — removes the key at `path` entirely. Used by bot deletion to remove `channels.<provider>.accounts.<agentId>`. **Behavior contract**: (a) if any intermediate segment of `path` is missing, the call is a no-op (no error); (b) if the parent dict is empty after removal, it is left as `{}` rather than being pruned recursively (e.g. deleting the only Telegram bot leaves `channels.telegram.accounts = {}` rather than removing `accounts` from `channels.telegram`). Pruning empty parents is left to a future helper if needed; OpenClaw treats `accounts: {}` and missing `accounts` identically per `account-id.ts`. Acquires the same `fcntl.lockf` exclusive lock on `openclaw.json` as `patch_openclaw_config` and the other helpers.
- **`_record_usage_from_session` rewritten** to use a new `_parse_session_key` helper that handles the `per-account-channel-peer` key shape, and an `async _resolve_member_from_session` that does the DynamoDB lookup for channel DMs and falls back to `owner_id` for groups/channels/webchat-personal.
- **New trigger for billing**: lifecycle/end agent events (which fire for ALL runs, channel and webchat alike) replace the existing `chat.final` trigger (which fires only for webchat). The `chat.final` handler keeps its UI signaling (`thinking`, `chunk`, `done`) but no longer drives billing.
- **New DynamoDB table `channel-links`** stores the per-member identity mappings.
- **No new RPC subscriptions** to OpenClaw. `agent` events with `stream:"lifecycle"` already arrive on the existing operator WebSocket via the `broadcast("agent", ...)` at `openclaw/src/gateway/server-chat.ts:936`. The broadcast lives in the `else` branch of `if (isToolEvent) { ... } else { ... }`, so it fires for every non-tool agent event (lifecycle, item, etc.) regardless of channel surface — there is no `isControlUiVisible` gate on this path. Lifecycle events are not tool events (`evt.stream === "lifecycle"`, not `"tool"`), so they always reach the operator WS.

### What's removed

- `apps/frontend/src/components/control/panels/ChannelsPanel.tsx` (replaced by per-agent `AgentChannelsSection`)
- `apps/frontend/src/components/chat/ChannelCards.tsx` (the duplicate onboarding variant)
- All WhatsApp code: `channels.whatsapp.*` config in `core/containers/config.py`, the `whatsapp` plugin install logic, the QR pairing flow code, the `whatsapp.pair` and `web.login.start` / `web.login.wait` RPC calls, the `whatsapp` block in `routers/channels.py`
- Frontend direct calls to OpenClaw's `config.patch` RPC — migrated to `PATCH /api/v1/config`
- The stale `usage_poller.py` `.pyc` artifact (the source has already been deleted; the cache file should go too)

### What stays unchanged

- `agents.list`, `agents.create`, `agents.delete`, `agents.update` RPCs to OpenClaw — agent CRUD is still runtime via the existing flow
- `config.get` RPC for reading config (it returns redacted secrets, which is the right behavior for the frontend)
- `channels.status` RPC for live channel health
- The existing operator WebSocket handshake and connection pool architecture
- The existing `usage_service.record_usage` signature and DynamoDB writes
- All existing tests that don't touch the modified files

---

## Data model

### New DynamoDB table: `channel-links`

```
Table: isol8-{env}-channel-links

Primary key:
  PK (hash)  : owner_id          # container owner (org_id or user_id)
  SK (range) : provider#agent_id#peer_id

Attributes:
  owner_id    : string   # container owner
  provider    : string   # "telegram" | "discord" | "slack"
  agent_id    : string   # the Isol8 agent that owns the bot
  peer_id     : string   # platform user ID (Telegram numeric, Discord snowflake, Slack U...)
  member_id   : string   # Clerk user_id of the linked member
  linked_at   : string   # ISO8601 timestamp
  linked_via  : string   # "wizard" | "settings"

GSI: by-member
  PK : member_id
  SK : owner_id#provider#agent_id
  Use: Settings page lookup ("show me my links across all my orgs")
```

**Access patterns:**

| Query | Op | Path |
|---|---|---|
| Usage attribution: `peer_id → member_id` for one bot in one container | `GetItem(owner_id, "telegram#sales#99999")` | Main table |
| Settings page: list all links for a member | `Query(member_id)` | by-member GSI |
| Bot delete cleanup: remove all links for one bot | `Query(owner_id, begins_with(SK, "telegram#sales#"))` + `BatchDelete` | Main table |
| Container delete cleanup: remove all links for an owner | `Query(owner_id)` + `BatchDelete` | Main table |
| Member delete cleanup (Clerk webhook): remove all links for a Clerk user | `Query(member_id)` + `BatchDelete` | by-member GSI |
| Member self-unlink | `DeleteItem(owner_id, "telegram#sales#99999")` | Main table |

**A note on OpenClaw's vocabulary:** OpenClaw uses the term `accountId` in its config (`channels.<provider>.accounts.<accountId>.*`) and in session keys (`agent:<agentId>:<channel>:<accountId>:direct:<peerId>`). Isol8 uses `agent_id` everywhere. **In this design, the OpenClaw `accountId` is always the Isol8 `agent_id` — same string.** When we write `openclaw.json`, we put the agent_id into the `accountId` slot. When the parser reads a session key, the value in the `accountId` slot IS the agent_id. There is no translation step. This is a deliberate design choice; future code should not introduce any path where the two diverge.

### openclaw.json fields written by Isol8

When the admin creates the first Telegram bot for the `main` agent, the resulting patch (deep-merged into the existing config):

```json5
{
  session: {
    dmScope: "per-account-channel-peer"
  },
  channels: {
    telegram: {
      enabled: true,
      accounts: {
        main: {
          botToken: "123456:ABC-DEF...",
          dmPolicy: "pairing",
          allowFrom: []
        }
      },
      defaultAccount: "main"
    }
  },
  bindings: [
    {
      match: { channel: "telegram", accountId: "main" },
      agentId: "main"
    }
  ]
}
```

When a second bot is added for the `sales` agent:

```json5
{
  channels: {
    telegram: {
      accounts: {
        sales: {
          botToken: "789012:XYZ-...",
          dmPolicy: "pairing",
          allowFrom: []
        }
      }
    }
  },
  bindings: [
    { match: { channel: "telegram", accountId: "sales" }, agentId: "sales" }
  ]
}
```

The `bindings` array uses `append_to_openclaw_config_list` to avoid clobbering existing entries. `defaultAccount` is set on first bot creation and not changed when subsequent bots are added (admin can override later via UI — out of scope for v1).

**Field formats (verified against OpenClaw source):**

- `session.dmScope`: enum string `"main" | "per-peer" | "per-channel-peer" | "per-account-channel-peer"` (`openclaw/src/routing/session-key.ts:138`)
- `channels.<provider>.accounts.<accountId>`: keyed by string `accountId` matching regex `/^[a-z0-9][a-z0-9_-]{0,63}$/i` and lowercased (`openclaw/src/routing/account-id.ts:6,35-47`). Default if unspecified: literal `"default"`.
- Isol8 `agent_id` (also written into the OpenClaw `accountId` slot): same regex (`openclaw/src/routing/session-key.ts:91-109`). Reserved value: `"main"` cannot be passed to OpenClaw's `agents.create` per `agents-mutate.test.ts`, but the auto-created main agent uses agent_id `"main"` because OpenClaw seeds it directly, not via the create RPC. New agents created via the UI get slugified names (e.g. `"Test Agent"` → `"test-agent"`).
- `bindings[].match.channel`: string, lowercase channel id (`"telegram"`, `"discord"`, `"slack"`)
- `bindings[].match.accountId`: same as above
- `bindings[].agentId`: same regex as agentId

### Session key parsing rules

OpenClaw with `session.dmScope: "per-account-channel-peer"` produces these session key shapes (`openclaw/src/routing/session-key.ts:138-176`):

| Source | Key shape | Example |
|---|---|---|
| Personal webchat | `agent:<agentId>:main` | `agent:main:main` |
| Org webchat | `agent:<agentId>:<clerk_user_id>` | `agent:main:user_2abc...` |
| Channel DM | `agent:<agentId>:<channel>:<accountId>:direct:<peerId>` | `agent:sales:telegram:sales:direct:99999` |
| Channel group | `agent:<agentId>:<channel>:group:<id>` | `agent:sales:telegram:group:-100123` |
| Group with topic (Telegram forum) | `agent:<agentId>:<channel>:group:<id>:topic:<topicId>` | `agent:sales:telegram:group:-100123:topic:42` |
| Channel room (Slack/Discord channel) | `agent:<agentId>:<channel>:channel:<id>` | `agent:main:slack:channel:C123ABC` |
| Channel thread | (above) `:thread:<threadId>` | `agent:main:slack:channel:C123ABC:thread:1234.5678` |

The org webchat shape comes from `apps/backend/routers/websocket_chat.py:533-534`:

```python
is_org = owner_id != user_id
session_key = f"agent:{agent_id}:{user_id}" if is_org else f"agent:{agent_id}:main"
```

The new parser:

```python
def _parse_session_key(self, session_key: str) -> dict:
    parts = session_key.split(":")
    if len(parts) < 3 or parts[0] != "agent":
        return {}
    agent_id = parts[1]

    # Webchat — 3 parts
    if len(parts) == 3:
        if parts[2] == "main":
            return {"agent_id": agent_id, "source": "webchat"}
        return {
            "agent_id": agent_id,
            "source": "webchat",
            "member_id": parts[2],   # already a Clerk user_id
        }

    # Channel DM (per-account-channel-peer):
    # OpenClaw shape is agent:<agentId>:<channel>:<accountId>:direct:<peerId>.
    # In our design accountId == agentId, so parts[1] and parts[3] always hold
    # the same value. We use parts[1] (which we already extracted as agent_id).
    if len(parts) == 6 and parts[4] == "direct":
        return {
            "agent_id": agent_id,
            "source": "dm",
            "channel": parts[2],
            "peer_id": parts[5],
        }

    # Channel group (with optional topic)
    if len(parts) >= 5 and parts[3] == "group":
        return {
            "agent_id": agent_id,
            "source": "group",
            "channel": parts[2],
            "group_id": parts[4],
        }

    # Channel/room (Slack/Discord channel, with optional thread)
    if len(parts) >= 5 and parts[3] == "channel":
        return {
            "agent_id": agent_id,
            "source": "channel",
            "channel": parts[2],
            "channel_id": parts[4],
        }

    return {"agent_id": agent_id, "source": "unknown"}
```

The member resolver:

```python
async def _resolve_member_from_session(self, parsed: dict) -> str:
    """Map a parsed session key to the Clerk member_id who owns the usage.
    Falls back to self.user_id (the owner) if no per-member attribution is available.
    """
    if parsed.get("source") == "dm":
        link = await channel_link_repo.get_by_peer(
            owner_id=self.user_id,
            provider=parsed["channel"],
            agent_id=parsed["agent_id"],
            peer_id=parsed["peer_id"],
        )
        if link:
            return link["member_id"]
        return self.user_id  # unlinked DM → bill org

    if parsed.get("source") == "webchat" and parsed.get("member_id"):
        return parsed["member_id"]

    # Personal webchat, groups, channels, unknown → owner
    return self.user_id
```

### Group attribution semantics

When a group/channel session key is parsed (`agent:sales:telegram:group:-100123`), the parser cannot determine which org member sent the inbound message — OpenClaw bundles all senders into one session key, and the per-message `from.id` lives in the session message store, not in the key. The parser falls back to `owner_id`, which means:

- **Money attribution (correct):** the org's lifetime + monthly counters are incremented, the org pays, budget checks and Stripe meter reporting work normally.
- **Per-member breakdown (degraded):** the breakdown entry is written under `member:{owner_id}:{period}`. The frontend usage panel renders this bucket as "Group / unattributed" rather than as a phantom member.

This implicitly fixes a pre-existing parser bug at `connection_pool.py:307` where group session keys were attributed to the literal string `"telegram"` (or other channel name).

---

## Data flow

### Admin sets up the first Telegram bot for the `main` agent (personal user, first time)

1. User clicks "Set up Telegram" in the onboarding card or in Agents → main → Channels.
2. Frontend renders `BotSetupWizard` in `mode: "create"`.
3. User pastes the BotFather token. Frontend calls `PATCH /api/v1/config` with the patch shown in the Data model section. Backend resolves `owner_id` from `AuthContext`, checks tier (Starter+), invokes `patch_openclaw_config`, returns 200.
4. EFS write completes. Chokidar polling picks up the change within ~1-2 seconds. OpenClaw reloads config, starts the Telegram plugin for account `main`, begins long-polling Telegram.
5. Frontend polls `channels.status` RPC until the account reports `ready` or surfaces an error. On error (invalid token, missing intents), the wizard shows a clear message and lets the user re-paste.
6. Wizard advances to step 2: "DM @your_bot_username from Telegram. The bot will reply with an 8-character code. Paste it below within 1 hour."
7. User DMs the bot from Telegram. OpenClaw receives the message, sees the sender's `from.id` is not in `allowFrom`, generates a pairing code (e.g. `XYZ98765`), writes it to `/mnt/efs/users/<owner_id>/.openclaw/credentials/telegram-pairing.json`, and replies in Telegram with the code.
8. User pastes `XYZ98765` into the wizard. Frontend calls `POST /api/v1/channels/link/telegram/complete` with `{agent_id: "main", code: "XYZ98765"}`.
9. Backend `channel_link_service.complete_link`:
    1. Reads `/mnt/efs/users/<owner_id>/.openclaw/credentials/telegram-pairing.json`
    2. Finds the entry where `code == "XYZ98765"`, extracts `id` (the platform user ID, e.g. `"12345"`)
    3. Calls `append_to_openclaw_config_list(owner_id, ["channels","telegram","accounts","main","allowFrom"], "12345")`
    4. Calls `channel_link_repo.put` to write the row to DynamoDB
10. Chokidar reloads config; `12345` is now in `allowFrom`. The user is linked. Wizard shows "✅ Linked."
11. Subsequent DMs from this user bypass pairing (allowFrom hit) and run agent normally. Session key is `agent:main:telegram:main:direct:12345`.

### Org member self-links to an existing bot

1. Admin already created `@acme_main_bot` and `@acme_sales_bot` for the org's main and sales agents.
2. Bob (an org member) opens Settings → My Channels.
3. Frontend calls `GET /api/v1/channels/links/me`. Backend reads `openclaw.json` **directly from EFS** (`/mnt/efs/users/<owner_id>/openclaw.json`, same path the existing `patch_openclaw_config` uses) — not via the `config.get` RPC. This is intentional: it works even when the container is scaled to zero (Free tier downgrade), and it's faster than an RPC roundtrip. For the bot's display username, the backend calls the `channels.status` RPC if the container is up, or falls back to showing the raw `accountId` (e.g. `"main"`, `"sales"`) as the bot name when the container is down. The endpoint queries `channel_links` by-member GSI for Bob's clerk_user_id, joins with the openclaw.json account list, and returns:

    ```json5
    {
      telegram: [
        { agent_id: "main",  bot_username: "acme_main_bot",  linked: false },
        { agent_id: "sales", bot_username: "acme_sales_bot", linked: false }
      ],
      discord: [],
      slack: [],
      can_create_bots: false
    }
    ```

4. Bob clicks "Link" on `@acme_main_bot`. Wizard opens in `mode: "link-only"` with `agent_id: "main"` pre-set. Token paste step is skipped.
5. Wizard shows: "DM @acme_main_bot from Telegram. The bot will reply with a code. Paste it below."
6. Bob DMs the bot. OpenClaw generates code `ABCDEF`, writes to the pairing file, replies.
7. Bob pastes `ABCDEF`. Frontend calls `POST /api/v1/channels/link/telegram/complete` with `{agent_id: "main", code: "ABCDEF"}`.
8. Same backend flow as 4.1 step 9. Bob's peer_id is added to `allowFrom`, link row written to DynamoDB.
9. From now on, Bob's DMs to the bot resolve to him via the `_resolve_member_from_session` lookup. Usage is billed under his clerk_user_id, not the org_id.

### Inbound DM with linked member → billing

1. Bob DMs `@acme_main_bot` "what's the weather?"
2. OpenClaw receives the message. `from.id == 12345` is in `allowFrom`. Routes to the bound `main` agent. Session key is `agent:main:telegram:main:direct:12345`.
3. Agent runs, streams tokens.
4. On agent run completion, OpenClaw broadcasts an `agent` event with `stream:"lifecycle"`, `data.phase:"end"`, `sessionKey:"agent:main:telegram:main:direct:12345"`. This broadcast is **unconditional** (`openclaw/src/gateway/server-chat.ts:936`) and reaches Isol8's existing operator WebSocket connection without any subscription.
5. Isol8's `connection_pool._handle_message` receives the event. The new branch detects `stream:"lifecycle"` + `phase:"end"` and calls `_record_usage_from_session({"sessionKey": ...})`.
6. `_record_usage_from_session` calls `_parse_session_key` → `{source: "dm", channel: "telegram", agent_id: "main", peer_id: "12345"}`.
7. Async task calls `_resolve_member_from_session(parsed)`, which calls `channel_link_repo.get_by_peer(owner_id, "telegram", "main", "12345")` → returns the link row → returns Bob's clerk_user_id.
8. `_fetch_and_record_usage` runs unchanged: queries `sessions.list` RPC, reads the per-run `inputTokens`/`outputTokens` (which OpenClaw overwrites per-run, not cumulative — `openclaw/src/agents/command/session-store.ts:109-122`), calls `usage_service.record_usage(owner_id=org_id, user_id=bob_clerk_id, model, tokens...)`.
9. `record_usage` writes monthly counter (org_id), lifetime counter (org_id), and per-member counter (`member:bob_clerk_id:{period}`).
10. Org pays the money. Per-member breakdown shows accurate Bob attribution.

### Inbound DM with unlinked stranger

1. A stranger (Eve, no Isol8 account) somehow finds the bot and DMs it.
2. OpenClaw checks `allowFrom`, doesn't find Eve's ID, generates a pairing code, replies with it.
3. Eve has no way to use the code. The pairing record sits in `telegram-pairing.json` until it expires after 1 hour (`openclaw/src/pairing/pairing-store.ts:175-194` prunes expired entries on read).
4. **No agent run happens.** OpenClaw doesn't process the message. No tokens are consumed. No `chat.final` or lifecycle event fires. No usage is billed.

Pairing acts as a built-in spam guard.

### Org webchat (regression check)

1. Bob opens the in-app chat in Isol8 and sends a message to the main agent.
2. `apps/backend/routers/websocket_chat.py:533-534` constructs the session key as `agent:main:bob_clerk_id` (because `owner_id != user_id`).
3. Agent runs. Lifecycle/end fires. Isol8's parser → `{source: "webchat", member_id: "bob_clerk_id"}`. Resolver returns `bob_clerk_id`.
4. Usage billed under Bob. Same as today's behavior, preserved.

---

## Error handling and edge cases

### Bot setup wizard (admin path)

| Case | Behavior |
|---|---|
| Tier doesn't allow channels (free tier) | `PATCH /api/v1/config` returns `403 channels_require_paid_tier`. Frontend shows upsell card. No EFS write. |
| Caller is org member, not admin | `PATCH /api/v1/config` returns `403 org_admin_required`. Same response shape as the existing admin endpoints. |
| Invalid bot token (BotFather rejects it) | EFS write succeeds, but OpenClaw fails to start the channel plugin. After the chokidar wait, the wizard polls `channels.status` RPC; on token-related error status, shows "Invalid token, please re-paste." No backend retry loop. |
| Container restart mid-wizard (pasted token, container restarting from chokidar pickup, then dies) | EFS write is durable. When the container comes back, it starts the bot. Wizard times out polling status after 30s and shows a "taking longer than expected" message; user refreshes and picks up where they left off. |
| Bot token already assigned to another agent | Backend pre-check scans `channels.<provider>.accounts.*.botToken` and rejects with `409 token_already_assigned_to_other_agent` before any EFS write. |
| `append_to_openclaw_config_list` race (two concurrent admin operations) | The new helper acquires `fcntl.lockf()` exclusive on `openclaw.json` (same lock as `patch_openclaw_config`) before the read-modify-write. Two concurrent appends serialize. |

### Member self-link flow

| Case | Behavior |
|---|---|
| Pairing code expired (>1 hour) | Backend reads pairing file, no entry matches (expired entries are pruned). Returns `404 pairing_code_not_found`. UI: "Code expired or not found. Please DM the bot again." |
| Wrong code typed | Same as expired: `404 pairing_code_not_found`. |
| Code from a different bot or channel | The pairing file path is per-channel; the lookup happens in the wrong file and returns `404`. UI hint: "Make sure you DM'd the right bot for {provider}." |
| Pairing file doesn't exist yet | `ENOENT` from EFS read → `404 pairing_code_not_found`. |
| Already linked to this bot (re-link attempt) | Backend detects the row already exists with the same `member_id`. Returns `200 already_linked` (idempotent). |
| Peer already linked to a DIFFERENT member (shoulder-surfed code attack) | Backend detects an existing row with the same SK but different `member_id`. Returns `409 peer_already_linked_to_other_member`. UI: "Ask the existing member to unlink first or contact your admin." |
| Member linked, then admin deletes the bot | The link row points at a now-nonexistent `agent_id`. Settings page filters out orphans (the bot doesn't appear in the openclaw.json read, so the row has no UI representation). On bot delete, the backend sweeps `channel_links` rows by `(owner_id, provider, agent_id)` and BatchDeletes them. |
| Container restart mid-link (EFS write succeeds, DynamoDB write fails) | Worst case: peer is in `allowFrom` but no link row in DynamoDB. Detection: next message billed under owner_id (no per-member attribution). Recovery: member re-runs the link flow; the EFS append is a no-op (already in allowFrom), the DynamoDB write succeeds. Acceptable. |

### Inbound DM / billing path

| Case | Behavior |
|---|---|
| Lifecycle/end event arrives but `sessionKey` is empty | Skip silently, log warning. |
| `sessions.list` RPC times out (10s) | Existing timeout in `_fetch_and_record_usage`. On timeout, log warning, skip recording. The agent's reply still went out — we just lose that one usage record. Lost usage events are accepted as a degraded mode. |
| `sessions.list` returns the session with zero tokens | Existing path at `connection_pool.py:372-379` already handles this — log and skip. |
| DynamoDB lookup fails in `channel_link_repo.get_by_peer` | Catch exception, log, fall back to billing under `owner_id`. Worst outcome: one message billed at org level instead of member level. |
| Lifecycle/end event with `phase:"error"` (aborted run) | Skip — only `phase:"end"` triggers billing. |
| Lifecycle/end for a sub-agent run | Sub-agents emit their own lifecycle/end events with their own runId, but they use **distinct session keys** (`childSessionKey` in `openclaw/src/agents/subagent-spawn.ts:554`). The sub-agent session key has a different `agent_id` slot than the parent (e.g. `agent:research_subagent:...`), so when our parser sees it, the channel DM regex doesn't match — the parser returns `webchat` or `unknown` source and the resolver returns `owner_id`. Sub-agent token usage is correctly billed at org level. The token counts are session-scoped (one set per session key), so the parent's lifecycle/end and the sub-agent's lifecycle/end read independent counters from `sessions.list` — no double-counting. **Residual risk**: if a future OpenClaw change reuses the parent's session key for a sub-agent run, lifecycle/end would fire twice for the same key and `_fetch_and_record_usage` would re-bill the same per-run tokens. Consistent with the same risk on the existing webchat path; runId-based dedup is a deferred mitigation. |
| Same lifecycle/end event arriving twice (network duplicate) | Same risk as today's webchat path — double-billing. Pre-existing risk, not a regression. Out of scope to fix in v1; can mitigate later with a runId LRU. |

### Channel deletion / unlink

| Case | Behavior |
|---|---|
| Admin deletes a bot | Backend (a) `delete_openclaw_config_path(owner_id, ["channels", provider, "accounts", agent_id])` removes the account block (the OpenClaw `accountId` slot holds our `agent_id`). (b) `remove_from_openclaw_config_list(owner_id, ["bindings"], predicate=lambda b: b.get("match", {}).get("channel") == provider and b.get("match", {}).get("accountId") == agent_id)` removes the binding. (c) Sweep `channel_links` by `(owner_id, provider, agent_id)` and BatchDelete. (d) Container picks up the change via chokidar, stops the bot. |
| Member self-unlinks | Backend (a) `remove_from_openclaw_config_list(owner_id, ["channels", provider, "accounts", agent_id, "allowFrom"], predicate=lambda v: v == peer_id)` for the member's peer_id. (b) DynamoDB DeleteItem on the link row. If the EFS write fails (admin removed the bot in the meantime), catch and proceed with the DDB delete. End state is consistent. |
| Org member leaves the org / Clerk `user.deleted` webhook fires | Existing handler in `routers/webhooks.py` extended to sweep `channel_links` by-member GSI and BatchDelete. |
| Whole container deleted (`delete_user_service`) | `core/containers/ecs_manager.py` extended to query `channel_links` by owner_id and BatchDelete before tearing down ECS. |

### Tier downgrade

| Case | Behavior |
|---|---|
| User downgrades from Pro to Free | Container scales to zero (existing Free tier behavior). Channels stop responding because the container isn't on. Configs and link rows stay intact in EFS and DynamoDB. On re-upgrade, container starts again with existing config; bots resume; no relinking required. Documented in the upgrade/downgrade UI: "Channels stop working when you downgrade to Free." **Settings → My Channels page** still renders for downgraded users because the backend reads openclaw.json directly from EFS (independent of the container being up); bot rows show with raw accountId as the display name and a "Container scaled down — upgrade to reactivate" banner at the top. Link/unlink buttons are disabled in this state. |

### Channel-specific quirks

| Channel | Quirk | How we handle |
|---|---|---|
| Telegram | If admin deletes the bot in BotFather, OpenClaw long-poll fails with auth errors. | OpenClaw surfaces this in `channels.status` as `auth_error`. Wizard shows it on the agent's channels card. Admin re-creates the bot, gets a new token, edits config. |
| Discord | Discord apps need "Message Content Intent" enabled in the developer portal to read DMs. | Wizard step 1 includes a checklist: "Enable Message Content Intent in Discord developer portal." Status check after chokidar wait surfaces a clear error if intents are missing. |
| Slack | Slack apps need scopes added at install time. The Socket Mode app token (`xapp-...`) is separate from the bot token (`xoxb-...`). | Wizard for Slack has TWO token fields plus a **static manifest** the user copy/pastes into Slack's app creation flow. The manifest is hardcoded in the frontend wizard component (not generated server-side) — Slack accepts pasted YAML/JSON manifests at `https://api.slack.com/apps?new_app=1`. The manifest declares the required scopes (`im:history`, `chat:write`, `app_mentions:read`, plus Socket Mode `connections:write` on the app token). No `redirect_uri` is needed because Socket Mode is outbound-only. The manifest content is the same for every Isol8 install — there's no per-agent or per-user customization. |

### Concurrency

| Case | Behavior |
|---|---|
| Two members link to the same bot at the same time | Both `complete_link` calls acquire the same `fcntl.lockf` on `openclaw.json` via `append_to_openclaw_config_list`. Serialized. Both succeed. |
| Member self-unlinks while admin patches the bot config | Same lock serializes them. No corruption. |
| Backend writes config while frontend reads via `config.get` RPC | `config.get` reads in-memory config; chokidar reload happens out-of-band. Worst case: frontend sees stale config for ~1 second. Acceptable. |

---

## Testing strategy

### Backend unit tests (the only formal tests we write upfront)

#### `tests/unit/services/test_channel_link_service.py` (new)

| Test | Asserts |
|---|---|
| `test_complete_link_happy_path` | Mocks EFS pairing file with one entry; calls `complete_link`; asserts the config helper and DynamoDB writer were called with the right args |
| `test_complete_link_code_not_found` | Empty pairing file → `PairingCodeNotFoundError` |
| `test_complete_link_code_expired` | Entry with `createdAt` >1 hour ago → `PairingCodeNotFoundError` |
| `test_complete_link_pairing_file_missing` | EFS file ENOENT → `PairingCodeNotFoundError` |
| `test_complete_link_already_linked_same_member` | Idempotent — returns success |
| `test_complete_link_peer_already_linked_other_member` | Different member already owns the SK → `PeerAlreadyLinkedError` |
| `test_complete_link_wrong_channel_file` | Telegram code submitted on Discord wizard → `PairingCodeNotFoundError` |

#### `tests/unit/services/test_config_patcher.py` (extended)

| Test | Asserts |
|---|---|
| `test_append_to_list_creates_path_when_missing` | Empty config; appending populates the nested path correctly |
| `test_append_to_list_appends_to_existing` | Existing list grows by one |
| `test_append_to_list_dedups` | Re-appending the same value is a no-op |
| `test_remove_from_list_value_match` | Removes string entry where `predicate(v) == True` |
| `test_remove_from_list_predicate_match` | Removes dict entry where structural predicate matches |
| `test_remove_from_list_no_match_is_noop` | Predicate matches nothing → list unchanged |
| `test_delete_path_removes_nested_key` | Deletes the key at the path; siblings preserved |
| `test_delete_path_missing_key_is_noop` | Path doesn't exist → no error |

#### `tests/unit/gateway/test_session_key_parser.py` (new)

Pure-function tests covering all 10 session-key shapes from the Data model section, including the **critical regression test** that group keys produce `member_id == owner_id`, not the literal `"telegram"`.

#### `tests/unit/gateway/test_lifecycle_billing.py` (new)

| Test | Asserts |
|---|---|
| `test_lifecycle_end_triggers_billing` | Feed `agent` event with `stream:"lifecycle", phase:"end"`; assert `record_usage` called with the parsed member |
| `test_lifecycle_error_does_not_bill` | `phase:"error"` → no billing call |
| `test_lifecycle_end_for_org_webchat_uses_clerk_member` | `agent:main:bob_clerk_id` key → bills under `bob_clerk_id` |
| `test_lifecycle_end_for_unlinked_channel_dm_falls_back_to_owner` | Unlinked DM → bills under `owner_id` |
| `test_chat_final_no_longer_calls_billing` | `chat.final` event → `record_usage` NOT called from this path |
| `test_chat_final_still_forwards_done_to_frontend` | `chat.final` still emits `{type:"done"}` to frontend |

#### `tests/unit/repositories/test_channel_link_repo.py` (new)

`test_put_link`, `test_get_by_peer_miss`, `test_query_by_member`, `test_delete_link`, `test_sweep_by_owner_provider_account`, `test_sweep_by_owner`, `test_sweep_by_member`.

#### `tests/unit/routers/test_config_router.py` (new)

`test_patch_config_personal_user_succeeds`, `test_patch_config_org_admin_succeeds`, `test_patch_config_org_member_rejected`, `test_patch_config_free_tier_channels_rejected`, `test_patch_config_free_tier_non_channels_succeeds`, `test_patch_config_validation_rejects_garbage`.

#### `tests/unit/routers/test_channels_link_router.py` (new)

`test_link_complete_telegram_happy`, `test_link_complete_invalid_code`, `test_link_complete_peer_already_linked`, `test_get_links_me_returns_grouped_by_provider`, `test_get_links_me_filters_orphaned_rows`.

### Frontend unit tests

#### `apps/frontend/tests/unit/components/BotSetupWizard.test.tsx` (new)

`wizard_create_mode_shows_token_step`, `wizard_link_only_mode_skips_token_step`, `wizard_paste_token_calls_config_patch`, `wizard_paste_pairing_code_calls_link_complete`, `wizard_handles_404_invalid_code`, `wizard_handles_409_peer_already_linked`.

#### `apps/frontend/tests/unit/components/AgentChannelsSection.test.tsx` (new)

`renders_telegram_discord_slack_cards` (no whatsapp), `add_button_visible_for_admin`, `add_button_hidden_for_org_member`, `existing_bot_shows_linked_members_count`, `delete_bot_calls_endpoint_with_confirm`.

#### `apps/frontend/tests/unit/components/MyChannelsSection.test.tsx` (new)

`lists_bots_grouped_by_provider`, `link_button_for_unlinked_bot_opens_wizard`, `unlink_button_calls_delete_endpoint`, `empty_provider_section_shows_admin_cta`, `empty_provider_section_hides_admin_cta_for_member`.

### Manual verification checklist (run before merging the PR, in dev)

- [ ] Personal user signup → onboarding prompts for channel setup → wizard works end-to-end with real Telegram bot
- [ ] Personal user adds a second bot (Discord) to the same agent → link flow works
- [ ] Org admin sets up Telegram bots for two agents (`main`, `sales`) → DMing each bot routes to the correct agent → admin's DMs to each bill correctly
- [ ] Org member (Account B) → Settings → My Channels → sees both bots → links to one → DMs work, usage attributed to Account B
- [ ] Org member tries to access Agents → sales → Channels admin section → only sees the Link button, no Add bot button
- [ ] Free tier user opens an agent's Channels section → sees upgrade upsell, no token field
- [ ] Free tier user → upgrades via Stripe → returns → channels become editable
- [ ] Pro user → downgrades to Free → DMs to existing bots stop working → re-upgrades → DMs work again, no relinking
- [ ] Admin deletes a bot → linked members' Settings page no longer shows that bot → DynamoDB confirms link rows swept
- [ ] Member self-unlinks → openclaw.json `allowFrom` no longer contains their peer_id → next DM gets a fresh pairing code
- [ ] **Bug fix verification:** group message in a Telegram group with the bot → check usage records → confirm `member_id == owner_id` for the group session, NOT the literal `"telegram"` string
- [ ] **Org webchat per-member billing still works:** two org members chat via the in-app UI → each member's usage shows up under their own clerk_user_id
- [ ] **Concurrent member links:** two org members link to the same bot at roughly the same time → both peers end up in `allowFrom`, both DynamoDB rows exist, no lost write
- [ ] **Pairing code expired (1 hour):** start the link wizard, get a code from the bot, wait 65 minutes, paste → wizard shows the 404 "code expired" message gracefully
- [ ] **Peer collision (409 path):** Account A links peer 12345; manually insert a different `member_id` row for the same SK in DynamoDB; have Account B attempt to link a code that resolves to peer 12345 → wizard shows the 409 "peer already linked to another member" error
- [ ] **Container restart mid-link:** start the link wizard, paste the pairing code, while the EFS write is in flight kill and restart the container → verify final state (peer in allowFrom OR not, DynamoDB row present OR not, AND consistent: never one without the other after retrying the link)

### What we're NOT doing upfront

- **Integration tests** — `tests/integration/` is empty today; we're not introducing the first integration test as part of this work. After we've shipped to dev and verified manually, we can add integration tests for any flaky parts.
- **E2E gate updates** — the existing E2E gate stays as-is. Channel-specific E2E specs and the existing WS 500 fix are out of scope.
- **Concurrent-link locking test** — covered by the existing `fcntl.lockf` pattern; if it works in `patch_openclaw_config`, it works in the new helpers.

---

## File-level change list

### New files

**Backend:**
- `apps/backend/routers/config.py`
- `apps/backend/core/services/channel_link_service.py`
- `apps/backend/core/repositories/channel_link_repo.py`
- `apps/backend/models/channel_link.py`
- `apps/backend/tests/unit/services/test_channel_link_service.py`
- `apps/backend/tests/unit/gateway/test_session_key_parser.py`
- `apps/backend/tests/unit/gateway/test_lifecycle_billing.py`
- `apps/backend/tests/unit/repositories/test_channel_link_repo.py`
- `apps/backend/tests/unit/routers/test_config_router.py`
- `apps/backend/tests/unit/routers/test_channels_link_router.py`

**Frontend:**
- `apps/frontend/src/components/channels/BotSetupWizard.tsx`
- `apps/frontend/src/components/control/panels/AgentChannelsSection.tsx`
- `apps/frontend/src/components/settings/MyChannelsSection.tsx`
- `apps/frontend/tests/unit/components/BotSetupWizard.test.tsx`
- `apps/frontend/tests/unit/components/AgentChannelsSection.test.tsx`
- `apps/frontend/tests/unit/components/MyChannelsSection.test.tsx`

### Modified files

**Backend:**
- `apps/backend/core/containers/config.py` — set `session.dmScope`, drop `channels.whatsapp` from initial config, leave Telegram/Discord/Slack as scaffolding only (admin populates via wizard)
- `apps/backend/core/services/config_patcher.py` — add `append_to_openclaw_config_list`, `remove_from_openclaw_config_list`, and `delete_openclaw_config_path`
- `apps/backend/core/gateway/connection_pool.py` — new lifecycle/end branch in `_handle_message`, rewrite `_record_usage_from_session` and add `_parse_session_key` + `_resolve_member_from_session`, remove the `chat.final → _record_usage_from_session` call (keep UI signaling)
- `apps/backend/routers/channels.py` — add link endpoints, remove WhatsApp endpoints
- `apps/backend/routers/webhooks.py` — extend Clerk `user.deleted` handler to sweep `channel_links`
- `apps/backend/core/containers/ecs_manager.py` — extend `delete_user_service` to sweep `channel_links` by owner_id
- `apps/backend/main.py` — register new `routers/config.py`
- `apps/backend/tests/unit/services/test_config_patcher.py` — new tests for the list helpers

**Frontend:**
- `apps/frontend/src/components/control/ControlPanelRouter.tsx` — remove `ChannelsPanel` route
- `apps/frontend/src/components/control/ControlSidebar.tsx` — remove Channels nav entry
- `apps/frontend/src/components/control/panels/AgentsPanel.tsx` — render `AgentChannelsSection` inside agent detail
- `apps/frontend/src/app/settings/page.tsx` — render `MyChannelsSection`
- `apps/frontend/src/components/chat/ProvisioningStepper.tsx` — replace channel onboarding step to use the new wizard
- All call sites of `useGatewayRpcMutation("config.patch", ...)` — migrate to `useApi().patch("/config", ...)`

### Deleted files

- `apps/frontend/src/components/control/panels/ChannelsPanel.tsx`
- `apps/frontend/src/components/chat/ChannelCards.tsx`
- `apps/backend/core/services/__pycache__/usage_poller.cpython-312.pyc` (stale cache from removed source)

---

## Open questions answered during brainstorming

| Question | Answer |
|---|---|
| Does OpenClaw 4.5 support multi-tenant DM channels? | Yes, via `session.dmScope: "per-account-channel-peer"`. The default in code is `"main"` which is unsafe; `openclaw onboard` sets `"per-channel-peer"` automatically, but Isol8 writes openclaw.json directly and doesn't go through onboard. Setting it explicitly is the fix. |
| Does each org member need to create their own bot in BotFather? | No. The admin creates one bot per agent. Members are users of those bots. OpenClaw distinguishes them via `from.id`. |
| Are channel-driven runs billed today? | No. `chat.final` only fires for webchat. Channel usage is unbilled. Fixed by switching the billing trigger to lifecycle/end agent events. |
| Do we need to subscribe to anything to receive lifecycle events? | No. `broadcast("agent", ...)` reaches all operator-scoped clients automatically (`server-broadcast.ts:71-128`). Isol8 already receives `agent` events; we just add a new branch in the existing handler. |
| Do we need to track cumulative tokens to avoid double-billing? | No. OpenClaw's session store overwrites `inputTokens`/`outputTokens` per agent run (`session-store.ts:109`). Reading after each lifecycle/end gives that turn's tokens. Stateless. |
| What's the format of OpenClaw's `accountId`, and how does it relate to Isol8's `agent_id`? | Lowercase string matching `/^[a-z0-9][a-z0-9_-]{0,63}$/i`. Default is `"default"`. Isol8's `agent_id` uses the same regex. **In this design the OpenClaw `accountId` IS the Isol8 `agent_id` — same string, no translation.** Inside Isol8 code we always say `agent_id` (matching `useAgents.ts`, `agents.create`, etc.); the word `accountId` only appears when we're literally writing or reading the OpenClaw config field name. |
| Does the frontend use OpenClaw `config.patch` RPC today? | Yes, in `ChannelsPanel.tsx` and `ChannelCards.tsx`. We're unifying through a new `PATCH /api/v1/config` endpoint that wraps `patch_openclaw_config`. |
| Does deep-merge in `_deep_merge` concat or replace arrays? | Replaces. New helpers `append_to_openclaw_config_list` / `remove_from_openclaw_config_list` do locked read-modify-write for list semantics. |

