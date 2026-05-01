"use client";

import useSWR from "swr";
import { useApi } from "@/lib/api";
import { OverviewPanel } from "./panels/OverviewPanel";
import { InstancesPanel } from "./panels/InstancesPanel";
import { SessionsPanel } from "./panels/SessionsPanel";
import { UsagePanel } from "./panels/UsagePanel";
import { CronPanel } from "./panels/CronPanel";
import { AgentsPanel } from "./panels/AgentsPanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { NodesPanel } from "./panels/NodesPanel";
import { ConfigPanel } from "./panels/ConfigPanel";
import { DebugPanel } from "./panels/DebugPanel";
import { LogsPanel } from "./panels/LogsPanel";
import { LLMPanel } from "./panels/LLMPanel";
import { CreditsPanel } from "./panels/CreditsPanel";


interface ControlPanelRouterProps {
  panel: string;
  onPanelChange?: (panel: string) => void;
}

type UserMeResponse = {
  provider_choice?: "chatgpt_oauth" | "byo_key" | "bedrock_claude" | null;
};

const PANELS: Record<string, React.ComponentType> = {
  overview: OverviewPanel,
  instances: InstancesPanel,
  sessions: SessionsPanel,
  usage: UsagePanel,
  cron: CronPanel,
  agents: AgentsPanel,
  skills: SkillsPanel,
  nodes: NodesPanel,
  config: ConfigPanel,
  debug: DebugPanel,
  logs: LogsPanel,
  llm: LLMPanel,
  credits: CreditsPanel,
};

export function ControlPanelRouter({ panel, onPanelChange }: ControlPanelRouterProps) {
  const api = useApi();
  const { data: me } = useSWR<UserMeResponse>(
    "/users/me",
    () => api.get("/users/me") as Promise<UserMeResponse>,
  );

  // Defense-in-depth: the sidebar already hides the Credits item for
  // non-Bedrock users, but if the parent's panel state still reads
  // "credits" (URL param, stale prop), fall back to the overview rather
  // than render a panel the user isn't supposed to see.
  let resolvedPanel = panel;
  if (resolvedPanel === "credits" && me !== undefined && me.provider_choice !== "bedrock_claude") {
    resolvedPanel = "overview";
  }

  // LLMPanel needs the panel-switch callback for its "Manage credits →" deep-link;
  // every other panel takes no props.
  if (resolvedPanel === "llm") {
    return <LLMPanel onPanelChange={onPanelChange} />;
  }

  const Panel = PANELS[resolvedPanel] || PANELS.overview;
  return <Panel />;
}
