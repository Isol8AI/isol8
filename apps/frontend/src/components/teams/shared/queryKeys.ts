// apps/frontend/src/components/teams/shared/queryKeys.ts

// Ported from upstream Paperclip's queryKeys.ts (paperclip/ui/src/lib/queryKeys.ts)
// (MIT, © 2025 Paperclip AI). Translated from React Query tuple keys to SWR
// string keys. See spec at
// docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

export type InboxTab = "mine" | "recent" | "all" | "unread" | "approvals" | "runs" | "joins";

export interface InboxFilters {
  status?: string;
  project?: string;
  assignee?: string;
  creator?: string;
  search?: string;
  limit?: number;
}

function qs(filters: InboxFilters): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(filters)) {
    if (v === undefined || v === null || v === "") continue;
    parts.push(`${k}=${encodeURIComponent(String(v))}`);
  }
  return parts.join("&");
}

export const teamsQueryKeys = {
  inbox: {
    list: (tab: InboxTab, filters: InboxFilters) => {
      const tail = qs(filters);
      return tail ? `/teams/inbox?tab=${tab}&${tail}` : `/teams/inbox?tab=${tab}`;
    },
    approvals: () => `/teams/inbox/approvals`,
    runs: () => `/teams/inbox/runs`,
    liveRuns: () => `/teams/inbox/live-runs`,
  },
  issues: {
    detail: (id: string) => `/teams/issues/${id}`,
    comments: (id: string) => `/teams/issues/${id}/comments`,
  },
  approvals: { detail: (id: string) => `/teams/approvals/${id}` },
  runs: { detail: (id: string) => `/teams/runs/${id}` },
  members: () => `/teams/members`,
  projects: () => `/teams/projects`,
} as const;
