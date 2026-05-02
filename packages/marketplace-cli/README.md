# @isol8/marketplace

CLI installer for the [Isol8 marketplace](https://marketplace.isol8.co). One
command to drop a purchased SKILL.md skill into Claude Desktop, Cursor, OpenClaw,
or Copilot CLI.

## Usage

```bash
npx @isol8/marketplace install <listing-slug>
```

Auto-detects your AI client and drops the skill into the matching directory:

| Client          | Install path                          |
|-----------------|---------------------------------------|
| Claude Desktop  | `~/.claude/skills/<slug>/`            |
| Cursor          | `~/.cursor/skills/<slug>/`            |
| OpenClaw        | `~/.openclaw/skills/<slug>/`          |
| Copilot CLI     | `~/.config/github-copilot/skills/<slug>/` |

## Flags

```
--license-key <key>   Reuse a known license key (otherwise device-code flow)
--client <name>       Override auto-detection (claude-code | cursor | openclaw | copilot | generic)
--ci                  Install into ./.isol8/skills/ instead of $HOME for CI environments
```

## Authentication

For paid skills, the CLI runs a device-code flow:

1. CLI starts a session at `POST /api/v1/marketplace/cli/auth/start`.
2. Browser opens to `https://marketplace.isol8.co/cli/authorize?code=<device_code>`.
3. You sign in with Clerk and click "Authorize this device".
4. CLI's poll completes and the install proceeds.

License keys are stored at `~/.isol8/marketplace/licenses.json` (chmod 600).

## Exit codes

| Code | Reason |
|------|--------|
| 0    | Success |
| 1    | Generic error |
| 2    | Manifest fetch failed |
| 3    | License invalid |
| 4    | License rate-limited |
| 5    | License revoked |
| 6    | Auth failed / cancelled |
| 7    | Tarball download failed |
| 8    | SHA-256 mismatch — fail-loud, license NOT saved |
| 9    | Filesystem write failed |

## Operational notes for releasing

Before tagging the first `marketplace-cli-v*` release:

1. **Add `NPM_TOKEN`** to the GitHub Actions repo secrets. The publish workflow
   (`.github/workflows/publish-marketplace-cli.yml`) requires it, otherwise the
   tagged release will not actually publish to npm and the CLI will still
   return "package not found" for buyers.
2. The storefront's browser handoff URL (`/cli/authorize`) is provisioned in the
   Plan 5 PR. Ensure that PR has merged before tagging.
