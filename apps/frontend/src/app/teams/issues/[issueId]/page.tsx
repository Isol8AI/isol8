"use client";

import { useParams } from "next/navigation";
import { IssueDetailPanel } from "@/components/teams/panels/IssueDetailPanel";

export default function Page() {
  const { issueId } = useParams<{ issueId: string }>();
  return <IssueDetailPanel issueId={issueId!} />;
}
