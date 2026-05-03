"use client";

import { useParams } from "next/navigation";
import { AgentDetailPanel } from "@/components/teams/panels/AgentDetailPanel";

export default function Page() {
  const { agentId } = useParams<{ agentId: string }>();
  return <AgentDetailPanel agentId={agentId!} />;
}
