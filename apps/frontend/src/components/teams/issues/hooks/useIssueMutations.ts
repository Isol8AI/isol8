// Ported from upstream Paperclip's pages/IssueDetail.tsx mutations + the
// NewIssueDialog form submit (paperclip/ui/src/pages/IssueDetail.tsx,
// components/NewIssueDialog.tsx) (MIT, (c) 2025 Paperclip AI).
// v1: create + update + addComment. Defers checkout/feedback/interactions/etc.
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

import { useCallback } from "react";
import { useSWRConfig } from "swr";
import { useTeamsApi } from "@/hooks/useTeamsApi";
import { teamsQueryKeys } from "@/components/teams/shared/queryKeys";
import type {
  Issue,
  IssueComment,
  IssueCreateInput,
  IssueUpdateInput,
} from "@/components/teams/shared/types";

const SWR_PREFIX = "/teams";
const swrKey = (path: string) => `${SWR_PREFIX}${path}`;

export interface UseIssueMutationsResult {
  create: (input: IssueCreateInput) => Promise<Issue>;
  update: (issueId: string, input: IssueUpdateInput) => Promise<Issue>;
  addComment: (issueId: string, body: string) => Promise<IssueComment>;
}

function toBackendIssueBody(input: IssueCreateInput | IssueUpdateInput): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if ("title" in input && input.title !== undefined) body.title = input.title;
  if ("description" in input && input.description !== undefined) body.description = input.description;
  if (input.status !== undefined) body.status = input.status;
  if (input.priority !== undefined) body.priority = input.priority;
  if (input.projectId !== undefined) body.project_id = input.projectId;
  if (input.assigneeAgentId !== undefined) body.assignee_agent_id = input.assigneeAgentId;
  return body;
}

export function useIssueMutations(): UseIssueMutationsResult {
  const { post, patch } = useTeamsApi();
  const { mutate } = useSWRConfig();

  const create = useCallback(async (input: IssueCreateInput): Promise<Issue> => {
    const created = await post<Issue>("/issues", toBackendIssueBody(input));
    // Invalidate inbox lists (any tab) so the new issue appears.
    mutate((key) => typeof key === "string" && key.startsWith("/teams/inbox?"));
    return created;
  }, [post, mutate]);

  const update = useCallback(
    async (issueId: string, input: IssueUpdateInput): Promise<Issue> => {
      const updated = await patch<Issue>(`/issues/${issueId}`, toBackendIssueBody(input));
      // Invalidate the detail key + inbox lists.
      mutate(swrKey(teamsQueryKeys.issues.detail(issueId)));
      mutate((key) => typeof key === "string" && key.startsWith("/teams/inbox?"));
      return updated;
    },
    [patch, mutate],
  );

  const addComment = useCallback(
    async (issueId: string, body: string): Promise<IssueComment> => {
      const created = await post<IssueComment>(`/issues/${issueId}/comments`, { body });
      mutate(swrKey(teamsQueryKeys.issues.comments(issueId)));
      return created;
    },
    [post, mutate],
  );

  return { create, update, addComment };
}
