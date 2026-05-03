"use client";

import { TeamsPanelRouter } from "@/components/teams/TeamsPanelRouter";
import { useParams } from "next/navigation";

export default function TeamsPanel() {
  const { panel } = useParams<{ panel: string }>();
  return <TeamsPanelRouter panel={panel ?? "dashboard"} />;
}
