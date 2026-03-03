"use client";

import { Settings } from "lucide-react";

interface ControlSidebarProps {
  activePanel?: string;
  onPanelChange?: (panel: string) => void;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function ControlSidebar(props: ControlSidebarProps) {
  return (
    <div className="flex-1 flex flex-col px-3 py-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Settings className="h-4 w-4 opacity-70" />
        <span>Control Panel</span>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground/50 leading-relaxed">
        Navigate using the embedded panel.
      </p>
    </div>
  );
}
