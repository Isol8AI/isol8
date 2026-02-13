/**
 * Isol8 server types — replaces the Convex-generated server.d.ts
 *
 * Re-exports from the isol8 shim so that convex/ server files
 * (world.ts, messages.ts, testing.ts, etc.) typecheck.
 */

export {
  query,
  mutation,
  internalMutation,
  internalQuery,
  action,
  internalAction,
  httpAction,
} from '../isol8/server';

export type QueryCtx = any;
export type MutationCtx = any;
export type ActionCtx = any;
export type DatabaseReader = any;
export type DatabaseWriter = any;
