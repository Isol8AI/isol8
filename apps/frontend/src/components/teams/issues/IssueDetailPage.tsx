// apps/frontend/src/components/teams/issues/IssueDetailPage.tsx

// Ported from upstream Paperclip's pages/IssueDetail.tsx top-level layout
// (paperclip/ui/src/pages/IssueDetail.tsx) (MIT, (c) 2025 Paperclip AI).
// v1: header + description + comments thread + read-only properties sidebar.
// Drops chat/activity/related-work tabs, run ledger, sub-issues, plugin slots,
// documents, feedback, file uploads, interactions, continuation handoff.
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

"use client";

import { IssueHeader } from "./IssueHeader";
import { IssueComments } from "./IssueComments";
import { IssueProperties } from "./IssueProperties";
import { useIssueDetail } from "./hooks/useIssueDetail";
import { useIssueMutations } from "./hooks/useIssueMutations";

export interface IssueDetailPageProps {
  issueId: string;
}

export function IssueDetailPage({ issueId }: IssueDetailPageProps) {
  const { issue, comments, isLoading, isError, error } = useIssueDetail(issueId);
  const mutations = useIssueMutations();

  if (isLoading && !issue) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (isError && !issue) {
    return (
      <div
        role="alert"
        className="flex h-full flex-col items-center justify-center p-8 text-sm text-destructive"
      >
        <p>Failed to load issue.</p>
        {error?.message && (
          <p className="text-muted-foreground mt-1">{error.message}</p>
        )}
      </div>
    );
  }

  if (!issue) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-muted-foreground">
        Issue not found.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_320px] gap-6 p-4 sm:p-6">
      <main className="flex flex-col gap-6 min-w-0">
        <IssueHeader
          issue={issue}
          onTitleSave={async (title) => {
            await mutations.update(issueId, { title });
          }}
          onStatusChange={async (status) => {
            await mutations.update(issueId, { status });
          }}
          onPriorityChange={async (priority) => {
            await mutations.update(issueId, { priority });
          }}
        />
        {issue.description && (
          <div className="text-sm whitespace-pre-wrap text-muted-foreground border-l-2 border-border pl-3">
            {issue.description}
          </div>
        )}
        <div className="border-t pt-4">
          <h2 className="text-sm font-medium mb-3">Conversation</h2>
          <IssueComments
            comments={comments}
            isLoading={isLoading}
            onSubmit={async (body) => {
              await mutations.addComment(issueId, body);
            }}
          />
        </div>
      </main>
      <aside className="lg:sticky lg:top-4 lg:self-start">
        <IssueProperties issue={issue} />
      </aside>
    </div>
  );
}
