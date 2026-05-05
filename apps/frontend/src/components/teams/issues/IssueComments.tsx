// apps/frontend/src/components/teams/issues/IssueComments.tsx

// Ported from upstream Paperclip's pages/IssueDetail.tsx chat tab
// (paperclip/ui/src/pages/IssueDetail.tsx) (MIT, (c) 2025 Paperclip AI).
// v1: thread list + plaintext composer with Cmd+Enter submit.
// Drops markdown editor, @mentions, file upload, action flags, edit/delete.
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { IssueComment } from "@/components/teams/shared/types";

export interface IssueCommentsProps {
  comments: IssueComment[];
  isLoading?: boolean;
  onSubmit: (body: string) => Promise<void>;
}

function authorLabel(c: IssueComment): string {
  if (c.authorKind === "agent") return "Agent";
  if (c.authorKind === "user") return "User";
  if (c.authorAgentId) return "Agent";
  if (c.authorUserId) return "User";
  return "Comment";
}

export function IssueComments({
  comments,
  isLoading,
  onSubmit,
}: IssueCommentsProps) {
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const trimmed = body.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(trimmed);
      setBody("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to post comment");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* List */}
      {isLoading && comments.length === 0 ? (
        <p className="text-sm text-muted-foreground">Loading comments…</p>
      ) : comments.length === 0 ? (
        <p className="text-sm text-muted-foreground">No comments yet.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {comments.map((c) => (
            <li
              key={c.id}
              className="flex flex-col gap-1 border-l-2 border-border pl-3"
            >
              <div className="flex items-baseline gap-2 text-xs text-muted-foreground">
                <span>{authorLabel(c)}</span>
                <span aria-hidden="true">·</span>
                <time dateTime={c.createdAt}>
                  {new Date(c.createdAt).toLocaleString()}
                </time>
              </div>
              <div className="text-sm whitespace-pre-wrap">{c.body}</div>
            </li>
          ))}
        </ul>
      )}

      {/* Composer */}
      <div className="flex flex-col gap-2 border-t pt-4">
        <Textarea
          rows={3}
          placeholder="Add a comment..."
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void submit();
            }
          }}
          disabled={submitting}
        />
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button
            onClick={submit}
            disabled={!body.trim() || submitting}
          >
            {submitting ? "Posting…" : "Comment"}
          </Button>
        </div>
      </div>
    </div>
  );
}
