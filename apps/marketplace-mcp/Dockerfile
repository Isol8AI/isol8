FROM oven/bun:1.3-alpine
WORKDIR /app
# Bun 1.2+ writes text-format `bun.lock`; older versions wrote `bun.lockb`.
# Glob both so the build works against either format.
COPY package.json bun.lock* bun.lockb* ./
RUN bun install --production --frozen-lockfile
COPY . .
RUN bun build src/index.ts --target=bun --outfile=dist/index.js
EXPOSE 3000
CMD ["bun", "run", "dist/index.js"]
