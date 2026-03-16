"use client";

import { useState, useCallback, useRef, useMemo } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const LEVELS = ["trace", "debug", "info", "warn", "error", "fatal"] as const;

const LEVEL_COLORS: Record<string, string> = {
  trace: "text-muted-foreground/40",
  debug: "text-muted-foreground",
  info: "text-blue-400",
  warn: "text-yellow-400",
  error: "text-red-400",
  fatal: "text-red-500 font-bold",
};

const LEVEL_BADGE_COLORS: Record<string, string> = {
  trace: "bg-muted/30 text-muted-foreground/60",
  debug: "bg-muted/50 text-muted-foreground",
  info: "bg-blue-500/10 text-blue-400",
  warn: "bg-yellow-500/10 text-yellow-400",
  error: "bg-red-500/10 text-red-400",
  fatal: "bg-red-500/20 text-red-500",
};

const MAX_BUFFER = 2000;

interface LogsResponse {
  file?: string;
  cursor?: number;
  size?: number;
  lines?: unknown[];
  truncated?: boolean;
  reset?: boolean;
}

interface LogEntry {
  time?: string;
  date?: string;
  logLevelName?: string;
  level?: string | number;
  name?: string;
  msg?: string;
  message?: string;
  [key: string]: unknown;
}

interface ParsedLog {
  time: string;
  level: string;
  source: string;
  message: string;
}

function parseLogLine(line: unknown): ParsedLog {
  if (typeof line === "string") {
    try {
      const parsed = JSON.parse(line) as LogEntry;
      return extractLogFields(parsed);
    } catch {
      return { time: "", level: "info", source: "", message: line };
    }
  }
  if (typeof line === "object" && line !== null) {
    return extractLogFields(line as LogEntry);
  }
  return { time: "", level: "info", source: "", message: String(line) };
}

function extractLogFields(entry: LogEntry): ParsedLog {
  const time = entry.time || entry.date || "";
  const timeStr = time ? new Date(time).toLocaleTimeString() : "";

  let level = "info";
  if (entry.logLevelName) level = entry.logLevelName.toLowerCase();
  else if (typeof entry.level === "string") level = entry.level.toLowerCase();
  else if (typeof entry.level === "number") {
    if (entry.level <= 10) level = "trace";
    else if (entry.level <= 20) level = "debug";
    else if (entry.level <= 30) level = "info";
    else if (entry.level <= 40) level = "warn";
    else if (entry.level <= 50) level = "error";
    else level = "fatal";
  }

  const source = entry.name || "";
  const message = entry.msg || entry.message || JSON.stringify(entry);

  return { time: timeStr, level, source, message };
}

export function LogsPanel() {
  const [level, setLevel] = useState<string>("info");
  const [cursor, setCursor] = useState<number | undefined>(undefined);
  const [logs, setLogs] = useState<ParsedLog[]>([]);
  const [file, setFile] = useState<string | undefined>();
  const [initialLoadDone, setInitialLoadDone] = useState(false);

  // Track last processed SWR key to avoid re-processing same data
  const lastProcessedKey = useRef<string>("");

  const params = useMemo(
    () =>
      cursor != null
        ? { cursor, limit: 200, maxBytes: 524288 }
        : { limit: 200 },
    [cursor],
  );

  // Use SWR's onSuccess to accumulate log lines without useEffect
  const onSuccess = useCallback(
    (incoming: LogsResponse | unknown[]) => {
      // Deduplicate by checking a simple key
      const key = JSON.stringify(incoming).slice(0, 200);
      if (key === lastProcessedKey.current) return;
      lastProcessedKey.current = key;

      const response = incoming as LogsResponse;

      // Check if we should reset
      if (response.reset) {
        setLogs([]);
        setCursor(undefined);
        setInitialLoadDone(false);
        return;
      }

      // Extract lines
      const rawLines: unknown[] = Array.isArray(incoming)
        ? incoming
        : response.lines ?? [];

      if (rawLines.length === 0 && initialLoadDone) return;

      // Update cursor for next poll
      if (response.cursor != null) {
        setCursor(response.cursor);
      }

      // Update file name
      if (!Array.isArray(incoming) && response.file) {
        setFile(response.file);
      }

      // Parse new lines
      const newParsed = rawLines.map(parseLogLine);

      if (!initialLoadDone) {
        setLogs(newParsed.slice(-MAX_BUFFER));
        setInitialLoadDone(true);
      } else {
        setLogs((prev) => [...prev, ...newParsed].slice(-MAX_BUFFER));
      }
    },
    [initialLoadDone],
  );

  const { error, isLoading, mutate } = useGatewayRpc<LogsResponse | unknown[]>(
    "logs.tail",
    params,
    { refreshInterval: 5000, onSuccess },
  );

  const handleReset = useCallback(() => {
    setCursor(undefined);
    setLogs([]);
    setInitialLoadDone(false);
    lastProcessedKey.current = "";
    mutate();
  }, [mutate]);

  if (isLoading && !initialLoadDone) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error && !initialLoadDone) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  const levelIndex = LEVELS.indexOf(level as typeof LEVELS[number]);
  const filtered = logs.filter((entry) => {
    const entryIndex = LEVELS.indexOf(entry.level as typeof LEVELS[number]);
    return entryIndex >= levelIndex;
  });

  return (
    <div className="p-6 space-y-4 flex flex-col h-full">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Logs</h2>
          <p className="text-xs text-muted-foreground">
            {file ? `File: ${file}` : "Gateway file logs."}
          </p>
        </div>
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" onClick={handleReset} title="Reset and re-fetch all logs">
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="flex gap-1 flex-wrap">
        {LEVELS.map((l) => (
          <button
            key={l}
            className={cn(
              "px-2.5 py-1 text-xs rounded-md transition-colors",
              level === l
                ? LEVEL_BADGE_COLORS[l]
                : "bg-muted/30 text-muted-foreground/40 hover:bg-muted/50 hover:text-muted-foreground"
            )}
            onClick={() => setLevel(l)}
          >
            {l}
          </button>
        ))}
        <span className="text-xs text-muted-foreground/40 self-center ml-2">
          {filtered.length} entries (buffer: {logs.length}/{MAX_BUFFER})
        </span>
      </div>

      <div className="flex-1 min-h-0 bg-muted/20 rounded-lg border border-border overflow-auto">
        <div className="p-2 space-y-0.5 font-mono text-xs">
          {filtered.length > 0 ? (
            filtered.map((entry, i) => (
              <div key={i} className="flex gap-2 px-1 py-0.5 rounded hover:bg-muted/30">
                {entry.time && (
                  <span className="text-muted-foreground/40 flex-shrink-0 w-20">{entry.time}</span>
                )}
                <span className={cn("flex-shrink-0 w-12 text-right", LEVEL_COLORS[entry.level] || "text-muted-foreground")}>
                  {entry.level}
                </span>
                {entry.source && (
                  <span className="text-muted-foreground/60 flex-shrink-0 max-w-24 truncate">{entry.source}</span>
                )}
                <span className="text-foreground/80 break-all">{entry.message}</span>
              </div>
            ))
          ) : (
            <span className="text-muted-foreground p-2">No logs at this level.</span>
          )}
        </div>
      </div>
    </div>
  );
}
