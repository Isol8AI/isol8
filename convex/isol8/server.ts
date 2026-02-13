/**
 * Isol8 shim for convex/server
 *
 * Provides no-op server function builders (query, mutation, action, etc.)
 * and type exports. These are used in convex/ server-side files that define
 * Convex functions. They typecheck but are never executed client-side -- our
 * shim just returns the config object unchanged.
 */

// ---------------------------------------------------------------------------
// Server function builders (no-ops — return the config as-is)
// ---------------------------------------------------------------------------

export function query(config: any): any {
  return config;
}

export function mutation(config: any): any {
  return config;
}

export function internalQuery(config: any): any {
  return config;
}

export function internalMutation(config: any): any {
  return config;
}

export function action(config: any): any {
  return config;
}

export function internalAction(config: any): any {
  return config;
}

export function httpAction(handler: any): any {
  return handler;
}

// ---------------------------------------------------------------------------
// Generic builders (used by _generated/server.js)
// ---------------------------------------------------------------------------

export const queryGeneric = query;
export const mutationGeneric = mutation;
export const internalQueryGeneric = internalQuery;
export const internalMutationGeneric = internalMutation;
export const actionGeneric = action;
export const internalActionGeneric = internalAction;
export const httpActionGeneric = httpAction;

// ---------------------------------------------------------------------------
// Schema helpers
// ---------------------------------------------------------------------------

export function defineSchema(tables: any): any {
  return tables;
}

export function defineTable(definition: any): any {
  return {
    ...definition,
    index(_name: string, _fields: string[]): any {
      return this;
    },
    searchIndex(_name: string, _config: any): any {
      return this;
    },
    vectorIndex(_name: string, _config: any): any {
      return this;
    },
  };
}

// ---------------------------------------------------------------------------
// Router helpers
// ---------------------------------------------------------------------------

export function httpRouter(): any {
  return {
    route(_config: any) {
      return this;
    },
  };
}

export function cronJobs(): any {
  return {
    interval(_name: string, _schedule: any, _fn: any) {
      return this;
    },
    daily(_name: string, _schedule: any, _fn: any) {
      return this;
    },
    hourly(_name: string, _schedule: any, _fn: any) {
      return this;
    },
    weekly(_name: string, _schedule: any, _fn: any) {
      return this;
    },
    monthly(_name: string, _schedule: any, _fn: any) {
      return this;
    },
    cron(_name: string, _schedule: string, _fn: any) {
      return this;
    },
  };
}

// ---------------------------------------------------------------------------
// anyApi — used by _generated/api.js as a Proxy that returns nested refs
// ---------------------------------------------------------------------------

function createAnyApiProxy(path: string[] = []): any {
  return new Proxy(() => {}, {
    get(_target, prop: string) {
      return createAnyApiProxy([...path, prop]);
    },
    apply() {
      return undefined;
    },
  });
}

export const anyApi: any = createAnyApiProxy();

// ---------------------------------------------------------------------------
// Type exports (all aliased to `any` — server types are not exercised client-side)
// ---------------------------------------------------------------------------

export type QueryBuilder<DM = any, V = any> = any;
export type MutationBuilder<DM = any, V = any> = any;
export type ActionBuilder<DM = any, V = any> = any;
export type HttpActionBuilder = any;

export type GenericQueryCtx<DM = any> = any;
export type GenericMutationCtx<DM = any> = any;
export type GenericActionCtx<DM = any> = any;

export type GenericDatabaseReader<DM = any> = any;
export type GenericDatabaseWriter<DM = any> = any;

export type ApiFromModules<M = any> = any;
export type FilterApi<A = any, F = any> = any;
export type FunctionReference<T = any, V = any> = any;
export type FunctionArgs<F = any> = any;

export type DataModelFromSchemaDefinition<S = any> = any;
export type DocumentByName<DM = any, TN = any> = any;
export type TableNamesInDataModel<DM = any> = any;
export type SystemTableNames = string;

export type DatabaseReader = any;
export type DatabaseWriter = any;
export type QueryCtx = any;
export type MutationCtx = any;
export type ActionCtx = any;
