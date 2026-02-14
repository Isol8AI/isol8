/**
 * Isol8 endpoint mapping types — replaces the Convex-generated api.d.ts
 *
 * Typed as `any` so that backend-only code (convex/agent/, convex/engine/)
 * can reference arbitrary namespaces without type errors. The runtime Proxy
 * in api.js returns stubs for unknown paths.
 */

export interface FunctionRef {
  _type: 'query' | 'mutation' | 'stub';
  endpoint: string;
}

export declare const api: any;
export declare const internal: any;
