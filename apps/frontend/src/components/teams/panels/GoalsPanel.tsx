"use client";

import { Loader2, Target } from "lucide-react";
import { usePaperclipApi } from "@/hooks/usePaperclip";

interface Goal {
  id?: string;
  title?: string;
  status?: string;
  children?: Goal[];
}

function GoalTree({ goals, depth = 0 }: { goals: Goal[]; depth?: number }) {
  return (
    <div className={depth > 0 ? "ml-5 border-l border-[#e5e0d5] pl-3" : ""}>
      {goals.map((goal, idx) => (
        <div key={goal.id ?? idx}>
          <div className="flex items-center gap-2 py-2">
            <Target className="h-3.5 w-3.5 text-[#8a8578] flex-shrink-0" />
            <span className="text-sm text-[#1a1a1a]">{goal.title ?? "Untitled Goal"}</span>
            {goal.status && (
              <span className="text-xs text-[#b0a99a] ml-auto">{goal.status}</span>
            )}
          </div>
          {goal.children && goal.children.length > 0 && (
            <GoalTree goals={goal.children} depth={depth + 1} />
          )}
        </div>
      ))}
    </div>
  );
}

export function GoalsPanel() {
  const { data, isLoading } = usePaperclipApi<Goal[]>("goals");

  const goals = Array.isArray(data) ? data : [];

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
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Goals</h1>
        <p className="text-sm text-[#8a8578]">{goals.length} top-level goal{goals.length !== 1 ? "s" : ""}</p>
      </div>

      {goals.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <Target className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No goals found</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white px-4 py-2">
          <GoalTree goals={goals} />
        </div>
      )}
    </div>
  );
}
