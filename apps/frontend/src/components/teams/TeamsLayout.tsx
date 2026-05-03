"use client";

import { TeamsSidebar } from "./TeamsSidebar";

export function TeamsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <TeamsSidebar />
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}
