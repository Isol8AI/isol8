/**
 * Isol8 shim for convex/values
 *
 * Provides ConvexError, v (validator builder), GenericId, and type exports
 * used throughout the convex/ server-side code. The validator builder returns
 * simple marker objects -- they define schemas at module scope but are never
 * actually validated client-side.
 */

// ---------------------------------------------------------------------------
// ConvexError
// ---------------------------------------------------------------------------

export class ConvexError<T = any> extends Error {
  data: T;

  constructor(messageOrData: T) {
    const msg = typeof messageOrData === 'string' ? messageOrData : JSON.stringify(messageOrData);
    super(msg);
    this.name = 'ConvexError';
    this.data = messageOrData;
  }
}

// ---------------------------------------------------------------------------
// GenericId  (type-level only -- IDs are strings at runtime)
// ---------------------------------------------------------------------------

export type GenericId<T extends string = string> = string & { __tableName?: T };

// ---------------------------------------------------------------------------
// Validator marker types
// ---------------------------------------------------------------------------

interface Validator<T = any> {
  __isValidator: true;
  __type?: T;
}

function marker(): Validator {
  return { __isValidator: true } as Validator;
}

// ---------------------------------------------------------------------------
// v — validator builder
// ---------------------------------------------------------------------------

export const v = {
  id: (_tableName: string): Validator<string> => marker(),
  string: (): Validator<string> => marker(),
  number: (): Validator<number> => marker(),
  boolean: (): Validator<boolean> => marker(),
  bigint: (): Validator<bigint> => marker(),
  bytes: (): Validator<ArrayBuffer> => marker(),
  float64: (): Validator<number> => marker(),
  int64: (): Validator<bigint> => marker(),
  null: (): Validator<null> => marker(),
  any: (): Validator<any> => marker(),
  optional: (_inner: any): Validator => marker(),
  union: (..._members: any[]): Validator => marker(),
  literal: (_value: any): Validator => marker(),
  object: (_shape: Record<string, any>): Validator => marker(),
  array: (_element: any): Validator => marker(),
};

// ---------------------------------------------------------------------------
// Value-level type aliases used as TypeScript types in convex/ files
// ---------------------------------------------------------------------------

/** Infer the TypeScript type from a validator. Since our validators are stubs, this is `any`. */
export type Infer<V> = any;

/** Object shape from a validators record. */
export type ObjectType<V> = any;

/** A generic Convex value. */
export type Value = any;

/** Record of property validators. */
export type PropertyValidators = Record<string, any>;
