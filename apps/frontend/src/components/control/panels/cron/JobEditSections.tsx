"use client";

import { useState, type ReactNode, type KeyboardEvent } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface JobEditSection {
  id: string;
  title: string;
  defaultOpen: boolean;
  children: ReactNode;
}

function Accordion({
  section,
}: {
  section: JobEditSection;
}) {
  const [open, setOpen] = useState(section.defaultOpen);

  const toggle = () => setOpen((o) => !o);
  const handleKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle();
    }
  };

  const bodyId = `job-edit-section-${section.id}`;

  return (
    <div className="rounded-md border border-[#e0dbd0] bg-white/60" data-section-id={section.id}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={toggle}
        onKeyDown={handleKey}
        className={cn(
          "w-full flex items-center gap-2 px-3 py-2 text-left",
          "text-sm font-medium text-[#2b2a27] hover:bg-[#f5f1e8]",
          "focus:outline-none focus-visible:ring-1 focus-visible:ring-[#06402B]/30 rounded-md",
        )}
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-[#8a8578]" aria-hidden />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-[#8a8578]" aria-hidden />
        )}
        <span>{section.title}</span>
      </button>
      {open && (
        <div id={bodyId} className="px-3 pb-3 pt-1">
          {section.children}
        </div>
      )}
    </div>
  );
}

export function JobEditSections({ sections }: { sections: JobEditSection[] }) {
  return (
    <div className="space-y-2">
      {sections.map((section) => (
        <Accordion key={section.id} section={section} />
      ))}
    </div>
  );
}
