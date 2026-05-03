"use client";

import { useParams } from "next/navigation";
import { RunDetailPanel } from "@/components/teams/panels/RunDetailPanel";

export default function Page() {
  const { runId } = useParams<{ runId: string }>();
  return <RunDetailPanel runId={runId!} />;
}
