// No-op stub for Next.js `server-only` package under vitest (node env).
// In production, `server-only` throws when imported into a client bundle;
// in unit tests we're running in node with no such constraint, so it's safe
// to expose the module as empty.
export {};
