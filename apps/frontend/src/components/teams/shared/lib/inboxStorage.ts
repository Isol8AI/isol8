// apps/frontend/src/components/teams/shared/lib/inboxStorage.ts

// Ported from upstream Paperclip's lib/inbox.ts (loadInbox*/saveInbox*) and
// hooks/useInboxBadge.ts (loadReadInboxItems/saveReadInboxItems).
// (paperclip/ui/src/lib/inbox.ts, hooks/useInboxBadge.ts) (MIT, (c) 2025 Paperclip AI).
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

import type { InboxFilterPreferences } from "@/components/teams/shared/lib/inbox";
import type { InboxTab } from "@/components/teams/shared/queryKeys";
import { defaultIssueFilterState } from "@/components/teams/shared/lib/issueFilters";

const KNOWN_INBOX_TABS: readonly InboxTab[] = [
  "mine",
  "recent",
  "all",
  "unread",
  "approvals",
  "runs",
  "joins",
] as const;

/**
 * Build the namespaced localStorage key for a per-company inbox preference.
 * Exported for tests + cross-tab `storage` event filtering.
 */
export function inboxStorageKey(companyId: string, key: string): string {
  return `paperclip:inbox:${companyId}:${key}`;
}

function buildDefaultFilterPreferences(
  defaults?: Partial<InboxFilterPreferences>,
): InboxFilterPreferences {
  return {
    issueFilters: { ...defaultIssueFilterState, ...(defaults?.issueFilters ?? {}) },
  };
}

/**
 * Read the per-company inbox filter preferences from localStorage. Returns
 * `defaults` (merged with `defaultIssueFilterState`) when the key is missing,
 * the JSON is malformed, or `localStorage` access throws (private browsing).
 */
export function loadInboxFilterPreferences(
  companyId: string,
  defaults?: Partial<InboxFilterPreferences>,
): InboxFilterPreferences {
  const fallback = buildDefaultFilterPreferences(defaults);
  let raw: string | null;
  try {
    raw = localStorage.getItem(inboxStorageKey(companyId, "filters"));
  } catch {
    return fallback;
  }
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw) as Partial<InboxFilterPreferences> | null;
    if (!parsed || typeof parsed !== "object") return fallback;
    return {
      issueFilters: {
        ...defaultIssueFilterState,
        ...(defaults?.issueFilters ?? {}),
        ...(parsed.issueFilters ?? {}),
      },
    };
  } catch {
    return fallback;
  }
}

/** Persist the per-company inbox filter preferences. Swallows storage errors. */
export function saveInboxFilterPreferences(
  companyId: string,
  prefs: InboxFilterPreferences,
): void {
  try {
    localStorage.setItem(inboxStorageKey(companyId, "filters"), JSON.stringify(prefs));
  } catch {
    // Ignore localStorage failures (private browsing, quota, etc.).
  }
}

/** Persist the last-active inbox tab for this company. Swallows storage errors. */
export function saveLastInboxTab(companyId: string, tab: InboxTab): void {
  try {
    localStorage.setItem(inboxStorageKey(companyId, "tab"), tab);
  } catch {
    // Ignore localStorage failures.
  }
}

/**
 * Read + validate the last-active inbox tab. Returns `null` when the key is
 * missing, the stored value isn't a known InboxTab, or storage access throws.
 */
export function loadLastInboxTab(companyId: string): InboxTab | null {
  let raw: string | null;
  try {
    raw = localStorage.getItem(inboxStorageKey(companyId, "tab"));
  } catch {
    return null;
  }
  if (!raw) return null;
  return (KNOWN_INBOX_TABS as readonly string[]).includes(raw) ? (raw as InboxTab) : null;
}

/**
 * Read the set of read-marked inbox item IDs for this company. Returns an
 * empty Set when the key is missing, the JSON is malformed, or storage access
 * throws.
 */
export function loadReadInboxItems(companyId: string): Set<string> {
  let raw: string | null;
  try {
    raw = localStorage.getItem(inboxStorageKey(companyId, "read-items"));
  } catch {
    return new Set();
  }
  if (!raw) return new Set();
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((value): value is string => typeof value === "string"));
  } catch {
    return new Set();
  }
}

/** Persist the read-marked inbox item IDs as a JSON array. Swallows storage errors. */
export function saveReadInboxItems(companyId: string, ids: Set<string>): void {
  try {
    localStorage.setItem(
      inboxStorageKey(companyId, "read-items"),
      JSON.stringify([...ids]),
    );
  } catch {
    // Ignore localStorage failures.
  }
}
