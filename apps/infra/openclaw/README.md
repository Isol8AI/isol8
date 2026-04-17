# Extended OpenClaw Image

Custom Docker image extending `alpine/openclaw:<UPSTREAM>` with Linux binaries for the bundled skills that need them.

Built and pushed to ECR `isol8/openclaw-extended` by `.github/workflows/build-openclaw-image.yml` on every push to `main` that touches `Dockerfile` or `openclaw-version.json`.

## Bumping the upstream OpenClaw version

1. Find the new tag at https://hub.docker.com/r/alpine/openclaw/tags
2. Edit `Dockerfile`:
   - Change `FROM alpine/openclaw:<old>` to `FROM alpine/openclaw:<new>`
3. Edit `<repo-root>/openclaw-version.json`:
   - Change `"upstream": "alpine/openclaw:<old>"` to `<new>`
4. Build locally to verify (`--platform linux/amd64` is required so the build matches what CI/Fargate run; ARM64 binaries like 1Password CLI's apt repo aren't available):
   ```bash
   docker build --platform linux/amd64 -t openclaw-extended:local apps/infra/openclaw/
   ```
5. PR the change; CI rebuilds and pushes a new tag (`{upstream}-{short-sha}`)
6. After CI completes, find the new tag in ECR (or in the workflow output) and bump `openclaw-version.json#dev.tag` in another PR
7. After dev verification, copy `dev.tag` to `prod.tag` via PR

## Adding a new skill binary

1. Find the install method (apt / pip / npm / `go install` / build-from-source)
2. Add a `RUN` line to the appropriate layer in `Dockerfile`. Layer order is intentional — least-to-most volatile so caching stays maximal
3. Build + verify locally per "Bumping" step 4
4. PR

## Skipped skills

Skills requiring macOS apps (`apple-notes`, `bear-notes`, `things-mac`, `peekaboo`, `imsg`, `model-usage`, `camsnap`, `sag`) are intentionally NOT installed — they need their host apps which only exist on macOS. These are deferred to the desktop app.
