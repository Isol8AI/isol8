"use client";

import { Loader2, Repeat } from "lucide-react";
import { usePaperclipApi } from "@/hooks/usePaperclip";
import { cn } from "@/lib/utils";

interface Routine {
  id?: string;
  title?: string;
  cron?: string;
  timezone?: string;
  active?: boolean;
}

export function RoutinesPanel() {
  const { data, isLoading } = usePaperclipApi<Routine[]>("routines");

  const routines = Array.isArray(data) ? data : [];

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Routines</h1>
        <p className="text-sm text-[#8a8578]">{routines.length} routine{routines.length !== 1 ? "s" : ""}</p>
      </div>

      {routines.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <Repeat className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No routines found</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {routines.map((routine, idx) => (
            <div key={routine.id ?? idx} className="px-4 py-3 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-[#1a1a1a] truncate">
                  {routine.title ?? "Untitled Routine"}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  {routine.cron && (
                    <span className="text-xs font-mono text-[#8a8578]">{routine.cron}</span>
                  )}
                  {routine.timezone && (
                    <span className="text-xs text-[#b0a99a]">{routine.timezone}</span>
                  )}
                </div>
              </div>
              <span
                className={cn(
                  "text-xs px-2 py-0.5 rounded-full flex-shrink-0",
                  routine.active
                    ? "bg-[#e8f5e9] text-[#2d8a4e]"
                    : "bg-[#f5f3ee] text-[#b0a99a]",
                )}
              >
                {routine.active ? "Active" : "Paused"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
