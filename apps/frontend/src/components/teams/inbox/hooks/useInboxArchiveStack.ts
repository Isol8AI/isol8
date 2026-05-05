// apps/frontend/src/components/teams/inbox/hooks/useInboxArchiveStack.ts

// Ported from upstream Paperclip's pages/Inbox.tsx archiveIssueMutation +
// unarchiveIssueMutation + archive-stack state (paperclip/ui/src/pages/Inbox.tsx:1407-1582)
// (MIT, (c) 2025 Paperclip AI). Translated from React Query mutations to SWR
// cache mutations via useSWRConfig().mutate. See spec at
// docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

import { useState, useCallback, useRef, useEffect } from "react";
import { useSWRConfig } from "swr";
import { useTeamsApi } from "@/hooks/useTeamsApi";
import { teamsQueryKeys } from "@/components/teams/shared/queryKeys";
import type { Issue } from "@/components/teams/shared/types";

const INBOX_KEYS = [
  teamsQueryKeys.inbox.list("mine", {}),
  teamsQueryKeys.inbox.list("recent", {}),
  teamsQueryKeys.inbox.list("all", {}),
];

// SWR cache keys are stored with a "/teams" prefix (useTeamsApi composes them).
// We use the same composition when calling mutate() so the cache lookup hits.
const SWR_PREFIX = "/teams";
const swrKey = (path: string) => `${SWR_PREFIX}${path}`;

type IssueListData = { items: Issue[] } | Issue[];

function withoutId(
  data: IssueListData | undefined,
  id: string,
): IssueListData | undefined {
  if (!data) return data;
  if (Array.isArray(data)) return data.filter((i) => i.id !== id);
  return { ...data, items: (data.items ?? []).filter((i) => i.id !== id) };
}

export interface UseInboxArchiveStackResult {
  /** Set of issue IDs currently being archived (for fade-out CSS class). */
  archivingIssueIds: Set<string>;
  /** Whether at least one undoable archive exists (drives `u`-key gating in keyboard hook). */
  hasUndoableArchive: boolean;
  /**
   * Optimistic-archive an issue. Removes from all 3 inbox SWR caches,
   * fires server POST. On success pushes onto undo stack. On error rolls
   * back the cache snapshot.
   */
  archive: (issueId: string) => Promise<void>;
  /**
   * Pop the most recent archived id off the undo stack and unarchive it
   * server-side. Re-validates inbox SWR caches. Caller wires this to
   * `useInboxKeyboardNav`'s `onUndoArchive` callback.
   */
  undoArchive: () => Promise<void>;
  /** Mark a single issue as read (server POST + cache update via useReadInboxItems pattern). */
  markRead: (issueId: string) => Promise<void>;
  /** Mark a single issue as unread. */
  markUnread: (issueId: string) => Promise<void>;
}

export function useInboxArchiveStack(): UseInboxArchiveStackResult {
  const { post } = useTeamsApi();
  const { cache, mutate } = useSWRConfig();
  const [archivingIssueIds, setArchivingIssueIds] = useState<Set<string>>(
    new Set(),
  );
  const [undoStack, setUndoStack] = useState<string[]>([]);
  // Mirror undoStack into a ref so async paths (undoArchive) can read the
  // current value synchronously without depending on a stale closure capture
  // and without racing the React state-update commit.
  const undoStackRef = useRef<string[]>(undoStack);
  useEffect(() => {
    undoStackRef.current = undoStack;
  }, [undoStack]);

  const archive = useCallback(
    async (issueId: string) => {
      setArchivingIssueIds((prev) => {
        if (prev.has(issueId)) return prev;
        const next = new Set(prev);
        next.add(issueId);
        return next;
      });

      // Snapshot for rollback on error.
      const snapshots = INBOX_KEYS.map((key) => {
        const fullKey = swrKey(key);
        return {
          key,
          fullKey,
          prev: cache.get(fullKey)?.data as IssueListData | undefined,
        };
      });

      // Optimistic update — remove the issue from each cached array.
      for (const { key } of snapshots) {
        mutate(
          swrKey(key),
          (prev?: IssueListData) => withoutId(prev, issueId),
          { revalidate: false },
        );
      }

      try {
        // BFF: POST /teams/inbox/{id}/archive (path here without "/teams" prefix; useTeamsApi adds it)
        await post(`/inbox/${issueId}/archive`, {});
        // Success: push onto undo stack
        const pushed = [...undoStackRef.current, issueId];
        undoStackRef.current = pushed;
        setUndoStack(pushed);
      } catch (err) {
        // Rollback the cache snapshots
        for (const { key, prev } of snapshots) {
          mutate(swrKey(key), prev, { revalidate: false });
        }
        throw err;
      } finally {
        setArchivingIssueIds((prev) => {
          if (!prev.has(issueId)) return prev;
          const next = new Set(prev);
          next.delete(issueId);
          return next;
        });
        // Settle: revalidate to pull fresh server state
        for (const key of INBOX_KEYS) {
          mutate(swrKey(key));
        }
      }
    },
    [cache, mutate, post],
  );

  const undoArchive = useCallback(async () => {
    const stack = undoStackRef.current;
    if (stack.length === 0) return;
    const issueId = stack[stack.length - 1];
    // Pop optimistically. On error we restore.
    const nextStack = stack.slice(0, -1);
    undoStackRef.current = nextStack;
    setUndoStack(nextStack);

    try {
      await post(`/inbox/${issueId}/unarchive`, {});
    } catch (err) {
      // Restore the popped id back onto the stack
      const restored = [...undoStackRef.current, issueId];
      undoStackRef.current = restored;
      setUndoStack(restored);
      throw err;
    } finally {
      // Settle
      for (const key of INBOX_KEYS) {
        mutate(swrKey(key));
      }
    }
  }, [mutate, post]);

  const markRead = useCallback(
    async (issueId: string) => {
      await post(`/inbox/${issueId}/mark-read`, {});
      for (const key of INBOX_KEYS) mutate(swrKey(key));
    },
    [mutate, post],
  );

  const markUnread = useCallback(
    async (issueId: string) => {
      await post(`/inbox/${issueId}/mark-unread`, {});
      for (const key of INBOX_KEYS) mutate(swrKey(key));
    },
    [mutate, post],
  );

  return {
    archivingIssueIds,
    hasUndoableArchive: undoStack.length > 0,
    archive,
    undoArchive,
    markRead,
    markUnread,
  };
}
