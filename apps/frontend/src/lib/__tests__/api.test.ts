import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { deriveWebSocketUrl } from '../api';

describe('deriveWebSocketUrl', () => {
  const originalEnv = process.env.NEXT_PUBLIC_WS_URL;

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_WS_URL;
  });

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.NEXT_PUBLIC_WS_URL;
    } else {
      process.env.NEXT_PUBLIC_WS_URL = originalEnv;
    }
  });

  it('rewrites prod apex hostname: api.isol8.co → ws.isol8.co', () => {
    // Regression: before the fix this returned `wss://api.isol8.co` because the
    // old `.replace("api-", "ws-")` only matched env-prefixed hostnames. Prod
    // silently routed WebSocket traffic to the ALB and failed.
    expect(deriveWebSocketUrl('https://api.isol8.co/api/v1')).toBe(
      'wss://ws.isol8.co',
    );
  });

  it('rewrites dev env-prefixed hostname: api-dev.isol8.co → ws-dev.isol8.co', () => {
    expect(deriveWebSocketUrl('https://api-dev.isol8.co/api/v1')).toBe(
      'wss://ws-dev.isol8.co',
    );
  });

  it('rewrites staging env-prefixed hostname', () => {
    expect(deriveWebSocketUrl('https://api-staging.isol8.co/api/v1')).toBe(
      'wss://ws-staging.isol8.co',
    );
  });

  it('leaves localhost untouched and strips /api/v1', () => {
    expect(deriveWebSocketUrl('http://localhost:8000/api/v1')).toBe(
      'ws://localhost:8000',
    );
  });

  it('downgrades https→wss and http→ws', () => {
    expect(deriveWebSocketUrl('http://api-dev.isol8.co/api/v1')).toBe(
      'ws://ws-dev.isol8.co',
    );
  });

  it('NEXT_PUBLIC_WS_URL override short-circuits derivation', () => {
    process.env.NEXT_PUBLIC_WS_URL = 'wss://custom.example.com';
    expect(deriveWebSocketUrl('https://api.isol8.co/api/v1')).toBe(
      'wss://custom.example.com',
    );
  });

  it('does not rewrite an unrelated hostname that happens to start with "api"', () => {
    // "apiary.com" must not become "wsary.com" — the lookahead guards against
    // matching substrings of longer labels.
    expect(deriveWebSocketUrl('https://apiary.com/api/v1')).toBe(
      'wss://apiary.com',
    );
  });
});
