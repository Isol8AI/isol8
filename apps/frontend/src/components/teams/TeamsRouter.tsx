"use client";

import { DashboardPanel } from "./panels/DashboardPanel";
import { InboxPanel } from "./panels/InboxPanel";
import { IssuesPanel } from "./panels/IssuesPanel";
import { IssueDetailPanel } from "./panels/IssueDetailPanel";
import { RoutinesPanel } from "./panels/RoutinesPanel";
import { GoalsPanel } from "./panels/GoalsPanel";
import { ProjectsPanel } from "./panels/ProjectsPanel";
import { AgentsPanel } from "./panels/AgentsPanel";
import { AgentDetailPanel } from "./panels/AgentDetailPanel";
import { ApprovalsPanel } from "./panels/ApprovalsPanel";
import { OrgChartPanel } from "./panels/OrgChartPanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { CostsPanel } from "./panels/CostsPanel";
import { ActivityPanel } from "./panels/ActivityPanel";
import { SettingsPanel } from "./panels/SettingsPanel";

interface TeamsRouterProps {
  slug: string[];
}

export function TeamsRouter({ slug }: TeamsRouterProps) {
  const [section, id] = slug;

  if (!section) return <DashboardPanel />;

  switch (section) {
    case "inbox":
      return <InboxPanel />;
    case "issues":
      if (id) return <IssueDetailPanel issueId={id} />;
      return <IssuesPanel />;
    case "routines":
      return <RoutinesPanel />;
    case "goals":
      return <GoalsPanel />;
    case "projects":
      return <ProjectsPanel />;
    case "agents":
      if (id === "new") return <AgentDetailPanel isNew />;
      if (id) return <AgentDetailPanel agentId={id} />;
      return <AgentsPanel />;
    case "approvals":
      return <ApprovalsPanel />;
    case "org":
      return <OrgChartPanel />;
    case "skills":
      return <SkillsPanel />;
    case "costs":
      return <CostsPanel />;
    case "activity":
      return <ActivityPanel />;
    case "settings":
      return <SettingsPanel />;
    default:
      return <DashboardPanel />;
  }
}
