import { describe, it, expect } from 'vitest';
import { decideAdminHostRouting } from '@/middleware';

const ADMIN_HOSTS = new Set([
  'admin.isol8.co',
  'admin-dev.isol8.co',
  'admin.localhost:3000',
]);

describe('decideAdminHostRouting (admin host gate)', () => {
  it('passes through when an admin host hits an /admin path', () => {
    expect(
      decideAdminHostRouting('admin.isol8.co', '/admin/users', ADMIN_HOSTS),
    ).toEqual({ kind: 'passthrough' });
  });

  it('returns 404 for an /admin path on a non-admin host', () => {
    expect(
      decideAdminHostRouting('app.isol8.co', '/admin/users', ADMIN_HOSTS),
    ).toEqual({ kind: 'not_found' });
  });

  it('redirects to /admin when an admin host requests a non-admin path', () => {
    expect(
      decideAdminHostRouting('admin.isol8.co', '/chat', ADMIN_HOSTS),
    ).toEqual({ kind: 'redirect', to: '/admin' });
  });

  it('returns 404 for /admin on an unknown random host (defense in depth)', () => {
    expect(
      decideAdminHostRouting('attacker.example.com', '/admin', ADMIN_HOSTS),
    ).toEqual({ kind: 'not_found' });
  });

  it('allows admin.localhost:3000 (default admin host) for local dev', () => {
    expect(
      decideAdminHostRouting('admin.localhost:3000', '/admin/users', ADMIN_HOSTS),
    ).toEqual({ kind: 'passthrough' });
  });

  it('treats null/missing host as non-admin (404 on /admin)', () => {
    expect(
      decideAdminHostRouting(null, '/admin/users', ADMIN_HOSTS),
    ).toEqual({ kind: 'not_found' });
  });

  it('passes through public hosts on public paths', () => {
    expect(
      decideAdminHostRouting('app.isol8.co', '/chat', ADMIN_HOSTS),
    ).toEqual({ kind: 'passthrough' });
  });

  it('matches /admin exactly (not just prefix-with-extra-letters)', () => {
    // /administrator should NOT be treated as an admin path
    expect(
      decideAdminHostRouting('app.isol8.co', '/administrator', ADMIN_HOSTS),
    ).toEqual({ kind: 'passthrough' });
  });

  it('is case-insensitive on host comparison', () => {
    expect(
      decideAdminHostRouting('ADMIN.ISOL8.CO', '/admin/users', ADMIN_HOSTS),
    ).toEqual({ kind: 'passthrough' });
  });
});
