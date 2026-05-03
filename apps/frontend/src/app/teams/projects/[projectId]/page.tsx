"use client";

import { useParams } from "next/navigation";
import { ProjectDetailPanel } from "@/components/teams/panels/ProjectDetailPanel";

export default function Page() {
  const { projectId } = useParams<{ projectId: string }>();
  return <ProjectDetailPanel projectId={projectId!} />;
}
