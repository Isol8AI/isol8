"use client";

import { Loader2, Inbox } from "lucide-react";
import { usePaperclipApi } from "@/hooks/usePaperclip";
import { cn } from "@/lib/utils";

interface InboxItem {
  id?: string;
  title?: string;
  body?: string;
  read?: boolean;
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

export function InboxPanel() {
  const { data, isLoading } = usePaperclipApi<InboxItem[]>("inbox");

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
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Inbox</h1>
        <p className="text-sm text-[#8a8578]">{items.filter((i) => !i.read).length} unread</p>
      </div>

      {items.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <Inbox className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">Inbox is empty</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {items.map((item, idx) => (
            <div key={item.id ?? idx} className="px-4 py-3 flex items-start gap-3">
              <div className="mt-1.5 flex-shrink-0">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full block",
                    !item.read ? "bg-blue-500" : "bg-transparent",
                  )}
                />
              </div>
              <div className="flex-1 min-w-0">
                <div className={cn("text-sm truncate", !item.read ? "font-medium text-[#1a1a1a]" : "text-[#1a1a1a]")}>
                  {item.title ?? "No title"}
                </div>
                {item.body && (
                  <div className="text-xs text-[#8a8578] truncate mt-0.5">{item.body}</div>
                )}
              </div>
              <span className="text-xs text-[#b0a99a] flex-shrink-0">{formatTime(item.timestamp)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
