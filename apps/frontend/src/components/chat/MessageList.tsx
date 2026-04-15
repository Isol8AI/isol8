import * as React from "react";
import { cn } from "@/lib/utils";
import { linkifyFilePaths, isWorkspaceFileLink, extractFilePath } from "@/lib/filePathDetection";
import { Copy, RefreshCw, Share2, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useScrollToBottom } from "@/hooks/useScrollToBottom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

interface ToolUse {
  tool: string;
  toolCallId?: string;
  status: "running" | "done" | "error";
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  model?: string;
  toolUses?: ToolUse[];
}

interface MessageListProps {
  messages: Message[];
  isTyping?: boolean;
  agentName?: string;
  onRetry?: (assistantMsgId: string) => void;
  onOpenFile?: (path: string) => void;
  /**
   * Whether the list should automatically scroll to the bottom when new
   * messages arrive. Defaults to `true` to preserve existing live-chat
   * behavior. Set to `false` for read-only transcript views (e.g. cron run
   * detail panel) where auto-scroll would fight the user reading from the top.
   */
  autoScroll?: boolean;
}

function CodeBlock({ className, children, ...props }: React.HTMLAttributes<HTMLElement> & { children?: React.ReactNode }) {
  const match = /language-(\w+)/.exec(className || "");
  const codeString = String(children).replace(/\n$/, "");

  if (!match) {
    // Inline code
    return (
      <code className="bg-[#e8e3d9] rounded px-1.5 py-0.5 text-sm text-[#1a1a1a]" {...props}>
        {children}
      </code>
    );
  }

  // Fenced code block
  return (
    <div className="relative group/code my-4 rounded-lg overflow-hidden border border-[#e0dbd0]">
      <div className="flex items-center justify-between px-4 py-2 bg-[#f3efe6] border-b border-[#e0dbd0]">
        <span className="text-xs text-[#8a8578]">{match[1]}</span>
        <button
          onClick={() => { navigator.clipboard.writeText(codeString).catch(() => {}); }}
          className="text-xs text-[#8a8578] hover:text-[#1a1a1a] transition-colors flex items-center gap-1"
        >
          <Copy className="h-3 w-3" />
          Copy
        </button>
      </div>
      <SyntaxHighlighter
        style={oneDark}
        language={match[1]}
        PreTag="div"
        customStyle={{ margin: 0, borderRadius: 0, background: "#f8f5f0" }}
      >
        {codeString}
      </SyntaxHighlighter>
    </div>
  );
}

const MarkdownContent = React.memo(function MarkdownContent({
  content,
  onOpenFile,
}: {
  content: string;
  onOpenFile?: (path: string) => void;
}) {
  const processedContent = React.useMemo(() => linkifyFilePaths(content), [content]);
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code: CodeBlock,
        h1: ({ children }) => <h1 className="text-lg font-semibold mt-4 mb-2">{children}</h1>,
        h2: ({ children }) => <h2 className="text-base font-semibold mt-3 mb-2">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-semibold mt-3 mb-1">{children}</h3>,
        h4: ({ children }) => <h4 className="text-sm font-medium mt-2 mb-1">{children}</h4>,
        p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
        a: ({ href, children }) => {
          if (href && isWorkspaceFileLink(href) && onOpenFile) {
            const filePath = extractFilePath(href);
            return (
              <button
                onClick={() => onOpenFile(filePath)}
                className="text-[#06402B] hover:underline cursor-pointer bg-transparent border-none p-0 font-inherit text-inherit inline"
              >
                {children}
              </button>
            );
          }
          const isSafe = !href?.match(/^(javascript|data|vbscript):/i);
          return (
            <a href={isSafe ? href : '#'} target="_blank" rel="noopener noreferrer" className="text-[#06402B] hover:underline">
              {children}
            </a>
          );
        },
        ul: ({ children }) => <ul className="list-disc list-inside mb-3 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside mb-3 space-y-1">{children}</ol>,
        li: ({ children }) => <li className="ml-2">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-[#e0dbd0] pl-4 text-[#8a8578] my-3">{children}</blockquote>
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto my-4">
            <table className="w-full border-collapse border border-[#e0dbd0] text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-[#f3efe6]">{children}</thead>,
        th: ({ children }) => <th className="border border-[#e0dbd0] px-3 py-2 text-left font-medium">{children}</th>,
        td: ({ children }) => <td className="border border-[#e0dbd0] px-3 py-2">{children}</td>,
        tr: ({ children }) => <tr className="even:bg-[#f3efe6]">{children}</tr>,
        hr: () => <hr className="border-[#e0dbd0] my-4" />,
        pre: ({ children }) => <>{children}</>,
      }}
    >
      {processedContent}
    </ReactMarkdown>
  );
});

function ThinkingBlock({ content }: { content: string }) {
  const [isExpanded, setIsExpanded] = React.useState(false);

  return (
    <div className="mb-4 border border-[#e0dbd0] rounded-lg overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-[#f3efe6] hover:bg-[#ece7dc] transition-colors text-left"
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 text-[#8a8578]" />
        ) : (
          <ChevronRight className="h-4 w-4 text-[#8a8578]" />
        )}
        <span className="text-sm text-[#8a8578] italic">Thinking...</span>
      </button>
      {isExpanded && (
        <div className="px-3 py-2 text-sm text-[#8a8578] border-t border-[#e0dbd0]">
          <MarkdownContent content={content} />
        </div>
      )}
    </div>
  );
}

const TOOL_STYLES = {
  running: {
    pill: "bg-[#e8f5e9] text-[#2d8a4e] border-[#c8e6c9]",
    dot: "bg-[#2d8a4e] animate-pulse",
  },
  done: {
    pill: "bg-[#f3efe6] text-[#8a8578] border-[#e0dbd0]",
    dot: "bg-[#cdc7ba]",
  },
  error: {
    pill: "bg-[#fce4ec] text-[#a5311f] border-[#f8bbd0]",
    dot: "bg-[#c62828]",
  },
} as const;

function ToolUseIndicator({ toolUses }: { toolUses: ToolUse[] }) {
  if (toolUses.length === 0) return null;
  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {toolUses.map((t, i) => {
        const s = TOOL_STYLES[t.status];
        return (
          <span
            key={t.toolCallId ?? `${t.tool}-${i}`}
            className={cn(
              "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border",
              s.pill,
            )}
          >
            <span className={cn("w-1.5 h-1.5 rounded-full", s.dot)} />
            {t.tool}
            {t.status === "error" && " failed"}
          </span>
        );
      })}
    </div>
  );
}

const AGENT_GLYPH_PATH =
    "M11.2 6 C10.4 4.2 8.8 2.5 7 2.5 C5.2 2.5 4 4 4 6 C4 8 5.2 9.5 7 9.5 C8.8 9.5 10.4 7.8 11.2 6 C12 4.2 13.6 2.5 15.4 2.5 C17.2 2.5 18.4 4 18.4 6 C18.4 8 17.2 9.5 15.4 9.5 C13.6 9.5 12 7.8 11.2 6Z";

function AgentHead({ name, state }: { name: string; state: "idle" | "thinking" }) {
    return (
        <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-semibold text-[#302d28] tracking-tight">
                {name}
            </span>
            <span className="inline-flex items-center justify-center w-5 h-5">
                <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 12"
                    fill="none"
                    className={cn("agent-glyph", state === "thinking" && "agent-glyph--thinking")}
                >
                    <path
                        className="agent-glyph-base"
                        d={AGENT_GLYPH_PATH}
                        strokeWidth="1.6"
                        fill="none"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                    />
                    <path
                        className="agent-glyph-tracer"
                        d={AGENT_GLYPH_PATH}
                        strokeWidth="1.6"
                        fill="none"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                    />
                </svg>
            </span>
            <Button variant="ghost" size="icon" className="h-6 w-6 text-[#8a8578] hover:text-[#1a1a1a] hover:bg-[#f3efe6] opacity-0 group-hover:opacity-100 transition-opacity ml-1">
                <Copy className="h-3 w-3" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6 text-[#8a8578] hover:text-[#1a1a1a] hover:bg-[#f3efe6] opacity-0 group-hover:opacity-100 transition-opacity">
                <RefreshCw className="h-3 w-3" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6 text-[#8a8578] hover:text-[#1a1a1a] hover:bg-[#f3efe6] opacity-0 group-hover:opacity-100 transition-opacity">
                <Share2 className="h-3 w-3" />
            </Button>
        </div>
    );
}

function ErrorToolbar({ messageId, onRetry }: { messageId: string; onRetry?: (id: string) => void }) {
    return (
        <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium text-[#dc2626]">Failed to generate</span>
            {onRetry && (
                <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-[#dc2626] hover:text-[#1a1a1a] hover:bg-[#f3efe6]"
                    onClick={() => onRetry(messageId)}
                >
                    <RefreshCw className="h-3 w-3" />
                </Button>
            )}
        </div>
    );
}

export interface MessageListHandle {
  scrollToBottom: () => void;
}

export const MessageList = React.forwardRef<MessageListHandle, MessageListProps>(
  function MessageList({ messages, isTyping, agentName, onRetry, onOpenFile, autoScroll = true }, ref) {
    const { containerRef, endRef, scrollToBottom } = useScrollToBottom();

    React.useImperativeHandle(ref, () => ({
      scrollToBottom,
    }));

    // Auto-scroll to the bottom whenever new messages arrive, unless the
    // caller has opted out (e.g. read-only transcript views).
    React.useEffect(() => {
      if (!autoScroll) return;
      scrollToBottom();
    }, [messages, autoScroll, scrollToBottom]);

    return (
      <div
        ref={containerRef}
        className="flex-1 min-h-0 overflow-y-auto p-4 md:px-8"
        data-lenis-prevent
      >
        <div className="max-w-3xl mx-auto space-y-10 py-8">
          {messages.map((msg, idx) => {
            const isLastAssistant = msg.role === "assistant" && (
              idx === messages.length - 1 ||
              messages.slice(idx + 1).every((m) => m.role !== "assistant")
            );
            return (
            <div
              key={msg.id}
              data-role={msg.role}
              className={cn(
                "flex w-full group relative",
                msg.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              <div className="flex flex-col min-w-0 max-w-[85%]">
                {msg.role === "assistant" && (
                  msg.content.startsWith("Error: ")
                    ? <ErrorToolbar messageId={msg.id} onRetry={onRetry} />
                    : <AgentHead
                        name={agentName || "Assistant"}
                        state={isTyping && isLastAssistant ? "thinking" : "idle"}
                      />
                )}

                <div
                  className={cn(
                    "relative text-sm leading-7",
                    msg.role === "user"
                      ? "bg-[#f0ebe2] text-[#1a1a1a] rounded-2xl rounded-br-md px-4 py-2.5"
                      : "text-[#302d28] w-full"
                  )}
                >
                {msg.role === "assistant" && msg.thinking && (
                   <ThinkingBlock content={msg.thinking} />
                )}

                {msg.role === "assistant" && msg.toolUses && msg.toolUses.length > 0 && (
                  <ToolUseIndicator toolUses={msg.toolUses} />
                )}

                <div className={cn(
                  "wrap-break-word",
                  msg.role === "user" && "whitespace-pre-wrap",
                  msg.role === "assistant" && msg.content.startsWith("Error: ") && "text-[#dc2626]"
                )}>
                  {msg.role === "assistant" && msg.content.startsWith("Error: ")
                    ? msg.content.slice(7)
                    : msg.role === "assistant" && msg.content
                      ? <MarkdownContent content={msg.content} onOpenFile={onOpenFile} />
                      : msg.content || null}
                </div>
                </div>
              </div>
            </div>
          );
          })}
          <div ref={endRef} />
        </div>
      </div>
    );
  }
);
