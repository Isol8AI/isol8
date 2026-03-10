"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { SendHorizontal, Paperclip, X, FileIcon, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface PendingFile {
  file: File;
  id: string;
}

interface ChatInputProps {
  onSend: (message: string, files?: File[]) => void;
  disabled?: boolean;
  centered?: boolean;
  isUploading?: boolean;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

export function ChatInput({ onSend, disabled, centered, isUploading }: ChatInputProps) {
  const [input, setInput] = React.useState("");
  const [pendingFiles, setPendingFiles] = React.useState<PendingFile[]>([]);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleSend = () => {
    if (input.trim() || pendingFiles.length > 0) {
      const files = pendingFiles.map((pf) => pf.file);
      onSend(input, files.length > 0 ? files : undefined);
      setInput("");
      setPendingFiles([]);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files;
    if (!selected) return;

    const newFiles: PendingFile[] = Array.from(selected).map((file) => ({
      file,
      id: crypto.randomUUID(),
    }));
    setPendingFiles((prev) => [...prev, ...newFiles].slice(0, 10));

    // Reset input so the same file can be selected again
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const removeFile = (id: string) => {
    setPendingFiles((prev) => prev.filter((pf) => pf.id !== id));
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const dropped = e.dataTransfer.files;
    if (!dropped.length) return;

    const newFiles: PendingFile[] = Array.from(dropped).map((file) => ({
      file,
      id: crypto.randomUUID(),
    }));
    setPendingFiles((prev) => [...prev, ...newFiles].slice(0, 10));
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const isDisabled = disabled || isUploading;

  return (
    <div className={cn("p-4", !centered && "bg-black/40 backdrop-blur-md")}>
      <div
        className="relative flex flex-col max-w-3xl mx-auto"
        onDrop={handleDrop}
        onDragOver={handleDragOver}
      >
        {pendingFiles.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-2 px-1">
            {pendingFiles.map((pf) => (
              <div
                key={pf.id}
                className="flex items-center gap-1.5 bg-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white/70"
              >
                <FileIcon className="h-3.5 w-3.5 shrink-0 text-white/40" />
                <span className="truncate max-w-37.5">{pf.file.name}</span>
                <span className="text-white/30">{formatFileSize(pf.file.size)}</span>
                <button
                  type="button"
                  onClick={() => removeFile(pf.id)}
                  className="ml-0.5 text-white/30 hover:text-white/60 transition-colors"
                  aria-label={`Remove ${pf.file.name}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="relative flex items-end gap-2 border border-white/15 rounded-full bg-white/5 px-3 py-2 focus-within:ring-1 focus-within:ring-white/20 focus-within:bg-white/10 transition-all">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleFileSelect}
            aria-label="Attach files"
          />
          <Button
            size="icon"
            variant="ghost"
            className="shrink-0 h-8 w-8 rounded-full text-white/40 hover:text-white/70 hover:bg-white/10"
            onClick={() => fileInputRef.current?.click()}
            disabled={isDisabled}
            aria-label="Attach file"
          >
            <Paperclip className="h-4 w-4" />
          </Button>

          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything"
            rows={1}
            className="flex-1 min-h-6 max-h-50 resize-none bg-transparent text-white placeholder:text-white/30 focus:outline-none text-sm leading-6 py-1"
            disabled={isDisabled}
            style={{ fieldSizing: "content" } as React.CSSProperties}
          />

          <Button
            size="icon"
            className="shrink-0 h-8 w-8 rounded-full"
            onClick={handleSend}
            disabled={(!input.trim() && pendingFiles.length === 0) || isDisabled}
            data-testid="send-button"
            aria-label="Send message"
          >
            {isUploading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <SendHorizontal className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
