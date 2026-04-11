"use client";

import { Loader2, Boxes } from "lucide-react";
import { usePaperclipApi } from "@/hooks/usePaperclip";

interface Skill {
  id?: string;
  name?: string;
  description?: string;
}

export function SkillsPanel() {
  const { data, isLoading } = usePaperclipApi<Skill[]>("skills");

  const skills = Array.isArray(data) ? data : [];

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
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Skills</h1>
        <p className="text-sm text-[#8a8578]">{skills.length} skill{skills.length !== 1 ? "s" : ""}</p>
      </div>

      {skills.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <Boxes className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No skills found</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {skills.map((skill, idx) => (
            <div key={skill.id ?? idx} className="px-4 py-3">
              <div className="text-sm font-medium text-[#1a1a1a]">{skill.name ?? "Unnamed Skill"}</div>
              {skill.description && (
                <div className="text-xs text-[#8a8578] mt-0.5">{skill.description}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
