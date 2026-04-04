"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Copy, Loader2 } from "lucide-react";
import type { FileInfo } from "@/hooks/useWorkspaceFiles";

const REMARK_PLUGINS = [remarkGfm];

const LANGUAGE_MAP: Record<string, string> = {
  py: "python", js: "javascript", ts: "typescript", tsx: "tsx", jsx: "jsx",
  json: "json", yaml: "yaml", yml: "yaml", toml: "toml", sh: "bash",
  bash: "bash", css: "css", html: "html", xml: "xml", sql: "sql",
  rs: "rust", go: "go", java: "java", c: "c", cpp: "cpp", h: "c",
  hpp: "cpp", rb: "ruby", php: "php", swift: "swift", kt: "kotlin",
  r: "r", lua: "lua",
};

function CsvTable({ content }: { content: string }) {
  const rows = content.trim().split("\n").map((row) => row.split(","));
  if (rows.length === 0) return null;
  const headers = rows[0];
  const body = rows.slice(1);

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse border border-[#e0dbd0] text-sm">
        <thead className="bg-[#f3efe6]">
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="border border-[#e0dbd0] px-3 py-2 text-left font-medium">{h.trim()}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri} className="even:bg-[#f3efe6]">
              {row.map((cell, ci) => (
                <td key={ci} className="border border-[#e0dbd0] px-3 py-2">{cell.trim()}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface FileContentViewerProps {
  file: FileInfo | null;
  isLoading: boolean;
  error: Error | null;
}

export function FileContentViewer({ file, isLoading, error }: FileContentViewerProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-[#8a8578]">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        Loading file...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-500 text-sm">
        Could not load file.
      </div>
    );
  }

  if (!file) {
    return (
      <div className="flex items-center justify-center h-full text-[#8a8578] text-sm">
        Select a file to view its contents.
      </div>
    );
  }

  if (file.binary && file.mime_type.startsWith("image/") && file.content) {
    return (
      <div className="p-4 flex items-center justify-center">
        <img
          src={`data:${file.mime_type};base64,${file.content}`}
          alt={file.name}
          className="max-w-full max-h-[80vh] object-contain rounded border border-[#e0dbd0]"
        />
      </div>
    );
  }

  if (file.binary || file.content === null) {
    return (
      <div className="flex items-center justify-center h-full text-[#8a8578] text-sm">
        Binary file — preview not available.
      </div>
    );
  }

  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";

  if (ext === "csv") {
    return (
      <div className="p-4 overflow-auto h-full">
        <CsvTable content={file.content} />
      </div>
    );
  }

  if (ext === "md") {
    return (
      <div className="p-6 prose prose-sm max-w-none overflow-auto h-full">
        <ReactMarkdown remarkPlugins={REMARK_PLUGINS}>
          {file.content}
        </ReactMarkdown>
      </div>
    );
  }

  const language = LANGUAGE_MAP[ext];
  if (language) {
    return (
      <div className="overflow-auto h-full">
        <div className="flex items-center justify-between px-4 py-2 bg-[#f3efe6] border-b border-[#e0dbd0]">
          <span className="text-xs text-[#8a8578]">{language}</span>
          <button
            onClick={() => { navigator.clipboard.writeText(file.content!).catch(() => {}); }}
            className="text-xs text-[#8a8578] hover:text-[#1a1a1a] transition-colors flex items-center gap-1"
          >
            <Copy className="h-3 w-3" />
            Copy
          </button>
        </div>
        <SyntaxHighlighter
          style={oneDark}
          language={language}
          PreTag="div"
          customStyle={{ margin: 0, borderRadius: 0, background: "#f8f5f0" }}
        >
          {file.content}
        </SyntaxHighlighter>
      </div>
    );
  }

  return (
    <div className="p-4 overflow-auto h-full">
      <pre className="text-sm font-mono whitespace-pre-wrap text-[#1a1a1a]">
        {file.content}
      </pre>
    </div>
  );
}
