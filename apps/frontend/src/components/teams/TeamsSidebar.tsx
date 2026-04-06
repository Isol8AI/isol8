"use client";

import {
  LayoutDashboard,
  Inbox,
  CircleDot,
  Repeat,
  Target,
  FolderOpen,
  Bot,
  CheckCircle2,
  Network,
  Boxes,
  DollarSign,
  History,
  Settings,
  ArrowLeft,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface NavItem {
  key: string;
  label: string;
  icon: React.ElementType;
  href: string;
}

interface NavSection {
  label?: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { key: "dashboard", label: "Dashboard", icon: LayoutDashboard, href: "/teams" },
      { key: "inbox", label: "Inbox", icon: Inbox, href: "/teams/inbox" },
    ],
  },
  {
    label: "Work",
    items: [
      { key: "issues", label: "Issues", icon: CircleDot, href: "/teams/issues" },
      { key: "routines", label: "Routines", icon: Repeat, href: "/teams/routines" },
      { key: "goals", label: "Goals", icon: Target, href: "/teams/goals" },
    ],
  },
  {
    label: "Manage",
    items: [
      { key: "projects", label: "Projects", icon: FolderOpen, href: "/teams/projects" },
      { key: "agents", label: "Agents", icon: Bot, href: "/teams/agents" },
      { key: "approvals", label: "Approvals", icon: CheckCircle2, href: "/teams/approvals" },
    ],
  },
  {
    label: "Company",
    items: [
      { key: "org", label: "Org Chart", icon: Network, href: "/teams/org" },
      { key: "skills", label: "Skills", icon: Boxes, href: "/teams/skills" },
      { key: "costs", label: "Costs", icon: DollarSign, href: "/teams/costs" },
      { key: "activity", label: "Activity", icon: History, href: "/teams/activity" },
      { key: "settings", label: "Settings", icon: Settings, href: "/teams/settings" },
    ],
  },
];

export function TeamsSidebar() {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/teams") {
      return pathname === "/teams";
    }
    return pathname === href || pathname.startsWith(href + "/");
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-3 border-b border-[#e5e0d5]">
        <Link
          href="/chat"
          className="flex items-center gap-2 text-xs text-[#8a8578] hover:text-[#1a1a1a] transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Chat
        </Link>
        <div className="mt-2 px-1">
          <span className="text-sm font-semibold text-[#1a1a1a]">Teams</span>
        </div>
      </div>

      {/* Nav */}
      <ScrollArea className="flex-1 px-3 py-2">
        <div className="space-y-4">
          {NAV_SECTIONS.map((section, sectionIdx) => (
            <div key={sectionIdx} className="space-y-0.5">
              {section.label && (
                <div className="px-2 pb-1 text-xs font-medium text-[#b0a99a] uppercase tracking-wider">
                  {section.label}
                </div>
              )}
              {section.items.map(({ key, label, icon: Icon, href }) => (
                <Link key={key} href={href}>
                  <div
                    className={cn(
                      "flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-all cursor-pointer",
                      isActive(href)
                        ? "bg-white text-[#1a1a1a] shadow-sm"
                        : "text-[#8a8578] hover:text-[#1a1a1a] hover:bg-white/60",
                    )}
                  >
                    <Icon className="h-4 w-4 flex-shrink-0 opacity-70" />
                    <span className="truncate">{label}</span>
                  </div>
                </Link>
              ))}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
