"use client";

import { Loader2, History } from "lucide-react";
import { usePaperclipApi } from "@/hooks/usePaperclip";

interface ActivityItem {
  id?: string;
  description?: string;
  timestamp?: string;
}

function formatTime(ts?: string) {
  if (!ts) return "—";
  const date = new Date(ts);
  const ago = Date.now() - date.getTime();
  const minutes = Math.floor(ago / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function ActivityPanel() {
  const { data, isLoading } = usePaperclipApi<ActivityItem[]>("activity");

  const items = Array.isArray(data) ? data : [];

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
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Activity</h1>
        <p className="text-sm text-[#8a8578]">Recent team activity</p>
      </div>

      {items.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <History className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No activity yet</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {items.map((item, idx) => (
            <div key={item.id ?? idx} className="px-4 py-3 flex items-center justify-between">
              <span className="text-sm text-[#1a1a1a]">{item.description ?? "—"}</span>
              <span className="text-xs text-[#b0a99a] flex-shrink-0 ml-4">{formatTime(item.timestamp)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
