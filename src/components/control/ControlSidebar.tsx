"use client";

import {
  LayoutDashboard,
  Bot,
  MessageSquare,
  Link2,
  Clock,
  BarChart3,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface ControlSidebarProps {
  activePanel?: string;
  onPanelChange?: (panel: string) => void;
}

const NAV_ITEMS = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "agents", label: "Agents", icon: Bot },
  { key: "sessions", label: "Sessions", icon: MessageSquare },
  { key: "channels", label: "Channels", icon: Link2 },
  { key: "cron", label: "Cron Jobs", icon: Clock },
  { key: "usage", label: "Usage", icon: BarChart3 },
  { key: "actions", label: "Pairing", icon: ShieldCheck },
];

export function ControlSidebar({ activePanel, onPanelChange }: ControlSidebarProps) {
  return (
    <ScrollArea className="flex-1 px-3 py-2">
      <div className="space-y-1">
        {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
          <Button
            key={key}
            variant="ghost"
            className={cn(
              "w-full justify-start gap-2 font-normal transition-all h-auto py-1.5",
              activePanel === key
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
            )}
            onClick={() => onPanelChange?.(key)}
          >
            <Icon className="h-4 w-4 flex-shrink-0 opacity-70" />
            <span className="truncate">{label}</span>
          </Button>
        ))}
      </div>
    </ScrollArea>
  );
}
