"use client";

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
}

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

export function ControlPanelRouter({ panel }: ControlPanelRouterProps) {
  const Panel = PANELS[panel] || PANELS.overview;
  return <Panel />;
}
