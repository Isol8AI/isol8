/**
 * Isol8 data model types — replaces the Convex-generated dataModel.d.ts
 *
 * IDs are plain strings at runtime. These type aliases keep existing
 * type annotations (Id<'worlds'>, Doc<'messages'>, etc.) compiling.
 */

export type Id<T extends string = string> = string;
export type Doc<T extends string = string> = Record<string, any>;
export type TableNames = string;
export type DataModel = any;
