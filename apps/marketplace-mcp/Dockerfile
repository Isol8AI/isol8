FROM oven/bun:1.1-alpine
WORKDIR /app
COPY package.json bun.lockb* ./
RUN bun install --production --frozen-lockfile
COPY . .
RUN bun build src/index.ts --target=bun --outfile=dist/index.js
EXPOSE 3000
CMD ["bun", "run", "dist/index.js"]
