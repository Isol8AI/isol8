"use client";

import { TeamsSidebar } from "@/components/teams/TeamsSidebar";
import { PaperclipGuard } from "@/components/teams/PaperclipGuard";

export default function TeamsLayout({ children }: { children: React.ReactNode }) {
  return (
    <PaperclipGuard>
      <div className="flex h-screen bg-[#f5f3ee]">
        <aside className="w-60 flex-shrink-0 border-r border-[#e5e0d5] bg-[#faf8f4] flex flex-col">
          <TeamsSidebar />
        </aside>
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </PaperclipGuard>
  );
}
