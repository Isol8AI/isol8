"use client";

import { Loader2, FolderOpen } from "lucide-react";
import Link from "next/link";
import { usePaperclipApi } from "@/hooks/usePaperclip";

interface Project {
  id?: string;
  name?: string;
  description?: string;
}

export function ProjectsPanel() {
  const { data, isLoading } = usePaperclipApi<Project[]>("projects");

  const projects = Array.isArray(data) ? data : [];

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
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Projects</h1>
        <p className="text-sm text-[#8a8578]">{projects.length} project{projects.length !== 1 ? "s" : ""}</p>
      </div>

      {projects.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <FolderOpen className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No projects found</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {projects.map((project, idx) => (
            <Link key={project.id ?? idx} href={`/teams/projects/${project.id}`}>
              <div className="px-4 py-3 flex items-center gap-3 hover:bg-[#faf8f4] transition-colors cursor-pointer">
                <FolderOpen className="h-4 w-4 text-[#8a8578] flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-[#1a1a1a] truncate">
                    {project.name ?? "Unnamed Project"}
                  </div>
                  {project.description && (
                    <div className="text-xs text-[#8a8578] truncate">{project.description}</div>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
