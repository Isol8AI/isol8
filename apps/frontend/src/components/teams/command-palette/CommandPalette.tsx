"use client";

// Ported from upstream Paperclip's CommandPalette
// (paperclip/ui/src/components/CommandPalette.tsx) (MIT, (c) 2025 Paperclip AI).
// Vanilla shadcn Dialog + Input + result list (no cmdk dep). v1: navigate +
// search across agents/issues/projects. Drops "create" actions until #3d
// (NewIssueDialog) merges.
// See spec at docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { filterNavActions, type CommandPaletteAction } from "./commandPaletteActions";
import { useFilteredCommandResults } from "./useFilteredCommandResults";

type FlatItem = {
  kind: "nav" | "agent" | "issue" | "project";
  id: string;
  label: string;
  path: string;
};

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Inner component is mounted only while the dialog is open. Remounting on
// every open transition is what gives us "reset query + selectedIndex on
// reopen" without needing a setState-in-effect.
export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="p-0 max-w-xl gap-0 overflow-hidden">
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        {open ? <CommandPaletteContent open={open} onOpenChange={onOpenChange} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function CommandPaletteContent({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [rawSelectedIndex, setSelectedIndex] = useState(0);

  const navResults = useMemo(() => filterNavActions(query), [query]);
  const { agents, issues, projects } = useFilteredCommandResults(query, open);

  const flatItems = useMemo<FlatItem[]>(() => {
    const items: FlatItem[] = [];
    navResults.forEach((a) => items.push({ kind: "nav", id: a.id, label: a.label, path: a.path }));
    agents.forEach((a) => items.push({ kind: "agent", id: a.id, label: a.name, path: `/teams/agents/${a.id}` }));
    issues.forEach((i) => items.push({ kind: "issue", id: i.id, label: i.title, path: `/teams/issues/${i.id}` }));
    projects.forEach((p) => items.push({ kind: "project", id: p.id, label: p.name, path: `/teams/projects/${p.id}` }));
    return items;
  }, [navResults, agents, issues, projects]);

  // Derive a clamped index from raw state — no setState-in-effect needed.
  const selectedIndex = Math.min(rawSelectedIndex, Math.max(0, flatItems.length - 1));

  const select = (item: FlatItem) => {
    onOpenChange(false);
    router.push(item.path);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, flatItems.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = flatItems[selectedIndex];
      if (item) select(item);
    }
  };

  return (
    <>
      <div className="flex items-center gap-2 border-b border-border px-3">
        <Search className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
        <Input
          autoFocus
          placeholder="Search agents, issues, projects, or jump to..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          className="border-0 shadow-none focus-visible:ring-0 px-0 h-11"
        />
      </div>
      <div className="max-h-[60vh] overflow-y-auto py-2">
          {flatItems.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">No results.</div>
          ) : (
            <>
              {navResults.length > 0 && (
                <Group label="Navigate">
                  {navResults.map((a) => {
                    const idx = flatItems.findIndex((it) => it.kind === "nav" && it.id === a.id);
                    return (
                      <Row
                        key={a.id}
                        Icon={a.Icon}
                        label={a.label}
                        selected={selectedIndex === idx}
                        onMouseEnter={() => setSelectedIndex(idx)}
                        onClick={() => select(flatItems[idx])}
                      />
                    );
                  })}
                </Group>
              )}
              {agents.length > 0 && (
                <Group label="Agents">
                  {agents.map((a) => {
                    const idx = flatItems.findIndex((it) => it.kind === "agent" && it.id === a.id);
                    return (
                      <Row
                        key={a.id}
                        label={a.name}
                        sublabel="Agent"
                        selected={selectedIndex === idx}
                        onMouseEnter={() => setSelectedIndex(idx)}
                        onClick={() => select(flatItems[idx])}
                      />
                    );
                  })}
                </Group>
              )}
              {issues.length > 0 && (
                <Group label="Issues">
                  {issues.map((i) => {
                    const idx = flatItems.findIndex((it) => it.kind === "issue" && it.id === i.id);
                    return (
                      <Row
                        key={i.id}
                        label={i.title}
                        sublabel={i.identifier ?? "Issue"}
                        selected={selectedIndex === idx}
                        onMouseEnter={() => setSelectedIndex(idx)}
                        onClick={() => select(flatItems[idx])}
                      />
                    );
                  })}
                </Group>
              )}
              {projects.length > 0 && (
                <Group label="Projects">
                  {projects.map((p) => {
                    const idx = flatItems.findIndex((it) => it.kind === "project" && it.id === p.id);
                    return (
                      <Row
                        key={p.id}
                        label={p.name}
                        sublabel="Project"
                        selected={selectedIndex === idx}
                        onMouseEnter={() => setSelectedIndex(idx)}
                        onClick={() => select(flatItems[idx])}
                      />
                    );
                  })}
                </Group>
              )}
            </>
          )}
        </div>
    </>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="py-1">
      <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <ul role="listbox" className="flex flex-col">
        {children}
      </ul>
    </div>
  );
}

function Row({
  Icon,
  label,
  sublabel,
  selected,
  onMouseEnter,
  onClick,
}: {
  Icon?: CommandPaletteAction["Icon"];
  label: string;
  sublabel?: string;
  selected: boolean;
  onMouseEnter: () => void;
  onClick: () => void;
}) {
  return (
    <li
      role="option"
      aria-selected={selected}
      data-cmd-row
      onMouseEnter={onMouseEnter}
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer transition-colors",
        selected && "bg-amber-700/10 dark:bg-amber-400/10"
      )}
    >
      {Icon && <Icon className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />}
      <span className="flex-1 truncate">{label}</span>
      {sublabel && <span className="text-xs text-muted-foreground shrink-0">{sublabel}</span>}
    </li>
  );
}
