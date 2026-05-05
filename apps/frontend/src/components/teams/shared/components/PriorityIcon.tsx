// apps/frontend/src/components/teams/shared/components/PriorityIcon.tsx

// Ported from upstream Paperclip's PriorityIcon.tsx
// (paperclip/ui/src/components/PriorityIcon.tsx) (MIT, (c) 2025 Paperclip AI).
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

import { useState } from "react";
import { ArrowUp, ArrowDown, Minus, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import type { IssuePriority } from "@/components/teams/shared/types";

// Inlined copy of the upstream `priorityColor` map from
// `paperclip/ui/src/lib/status-colors.ts` with the retheme mapping applied:
//   `text-blue-{400,600}` for `low`  ->  `text-amber-700 dark:text-amber-400`
// Critical / high / medium hues are priority-semantic (red / orange / yellow)
// and pass through unchanged.
const priorityColor: Record<IssuePriority, string> = {
  critical: "text-red-600 dark:text-red-400",
  high: "text-orange-600 dark:text-orange-400",
  medium: "text-yellow-600 dark:text-yellow-400",
  low: "text-amber-700 dark:text-amber-400",
};

const priorityConfig: Record<IssuePriority, { icon: typeof ArrowUp; color: string; label: string }> = {
  critical: { icon: AlertTriangle, color: priorityColor.critical, label: "Critical" },
  high: { icon: ArrowUp, color: priorityColor.high, label: "High" },
  medium: { icon: Minus, color: priorityColor.medium, label: "Medium" },
  low: { icon: ArrowDown, color: priorityColor.low, label: "Low" },
};

const allPriorities: IssuePriority[] = ["critical", "high", "medium", "low"];

interface PriorityIconProps {
  priority: IssuePriority;
  onChange?: (priority: IssuePriority) => void;
  className?: string;
  showLabel?: boolean;
}

export function PriorityIcon({ priority, onChange, className, showLabel }: PriorityIconProps) {
  const [open, setOpen] = useState(false);
  const config = priorityConfig[priority] ?? priorityConfig.medium;
  const Icon = config.icon;

  const icon = (
    <span
      className={cn(
        "inline-flex items-center justify-center shrink-0",
        config.color,
        onChange && !showLabel && "cursor-pointer",
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5" />
    </span>
  );

  if (!onChange)
    return showLabel ? (
      <span className="inline-flex items-center gap-1.5">
        {icon}
        <span className="text-sm">{config.label}</span>
      </span>
    ) : (
      icon
    );

  const trigger = showLabel ? (
    <button className="inline-flex items-center gap-1.5 cursor-pointer hover:bg-accent/50 rounded px-1 -mx-1 py-0.5 transition-colors">
      {icon}
      <span className="text-sm">{config.label}</span>
    </button>
  ) : (
    icon
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent className="w-36 p-1" align="start">
        {allPriorities.map((p) => {
          const c = priorityConfig[p];
          const PIcon = c.icon;
          return (
            <Button
              key={p}
              variant="ghost"
              size="sm"
              className={cn("w-full justify-start gap-2 text-xs", p === priority && "bg-accent")}
              onClick={() => {
                onChange(p);
                setOpen(false);
              }}
            >
              <PIcon className={cn("h-3.5 w-3.5", c.color)} />
              {c.label}
            </Button>
          );
        })}
      </PopoverContent>
    </Popover>
  );
}
