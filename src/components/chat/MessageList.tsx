import * as React from "react";
import { cn } from "@/lib/utils";
import { Copy, RefreshCw, Share2, Bot, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useScrollToBottom } from "@/hooks/useScrollToBottom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

interface ToolUse {
  tool: string;
  status: "running" | "done";
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
  onRetry?: (assistantMsgId: string) => void;
}

function CodeBlock({ className, children, ...props }: React.HTMLAttributes<HTMLElement> & { children?: React.ReactNode }) {
  const match = /language-(\w+)/.exec(className || "");
  const codeString = String(children).replace(/\n$/, "");

  if (!match) {
    // Inline code
    return (
      <code className="bg-white/10 rounded px-1.5 py-0.5 text-sm" {...props}>
        {children}
      </code>
    );
  }

  // Fenced code block
  return (
    <div className="relative group/code my-4 rounded-lg overflow-hidden border border-white/10">
      <div className="flex items-center justify-between px-4 py-2 bg-white/5 border-b border-white/10">
        <span className="text-xs text-white/40">{match[1]}</span>
        <button
          onClick={() => { navigator.clipboard.writeText(codeString).catch(() => {}); }}
          className="text-xs text-white/40 hover:text-white transition-colors flex items-center gap-1"
        >
          <Copy className="h-3 w-3" />
          Copy
        </button>
      </div>
      <SyntaxHighlighter
        style={oneDark}
        language={match[1]}
        PreTag="div"
        customStyle={{ margin: 0, borderRadius: 0, background: "rgba(255,255,255,0.03)" }}
      >
        {codeString}
      </SyntaxHighlighter>
    </div>
  );
}

const MarkdownContent = React.memo(function MarkdownContent({ content }: { content: string }) {
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
          const isSafe = !href?.match(/^(javascript|data|vbscript):/i);
          return (
            <a href={isSafe ? href : '#'} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
              {children}
            </a>
          );
        },
        ul: ({ children }) => <ul className="list-disc list-inside mb-3 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside mb-3 space-y-1">{children}</ol>,
        li: ({ children }) => <li className="ml-2">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-white/20 pl-4 text-white/60 my-3">{children}</blockquote>
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto my-4">
            <table className="w-full border-collapse border border-white/10 text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-white/5">{children}</thead>,
        th: ({ children }) => <th className="border border-white/10 px-3 py-2 text-left font-medium">{children}</th>,
        td: ({ children }) => <td className="border border-white/10 px-3 py-2">{children}</td>,
        tr: ({ children }) => <tr className="even:bg-white/5">{children}</tr>,
        hr: () => <hr className="border-white/10 my-4" />,
        pre: ({ children }) => <>{children}</>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
});

function ThinkingBlock({ content }: { content: string }) {
  const [isExpanded, setIsExpanded] = React.useState(false);

  return (
    <div className="mb-4 border border-white/10 rounded-lg overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 transition-colors text-left"
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 text-white/60" />
        ) : (
          <ChevronRight className="h-4 w-4 text-white/60" />
        )}
        <span className="text-sm text-white/60 italic">Thinking...</span>
      </button>
      {isExpanded && (
        <div className="px-3 py-2 text-sm text-white/50 border-t border-white/10">
          <MarkdownContent content={content} />
        </div>
      )}
    </div>
  );
}

function ToolUseIndicator({ toolUses }: { toolUses: ToolUse[] }) {
  if (toolUses.length === 0) return null;
  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {toolUses.map((t, i) => (
        <span
          key={`${t.tool}-${i}`}
          className={cn(
            "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border",
            t.status === "running"
              ? "bg-blue-500/10 text-blue-300 border-blue-500/20"
              : "bg-white/5 text-white/50 border-white/10",
          )}
        >
          {t.status === "running" ? (
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
          ) : (
            <span className="w-1.5 h-1.5 rounded-full bg-white/30" />
          )}
          {t.tool}
        </span>
      ))}
    </div>
  );
}

function MessageToolbar({ modelName }: { modelName?: string }) {
    return (
        <div className="flex items-center gap-1 mb-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <span className="text-xs font-medium text-white/40 mr-2 flex items-center gap-1">
                <Bot className="h-3 w-3" />
                {modelName || "Assistant"}
            </span>
            <Button variant="ghost" size="icon" className="h-6 w-6 text-white/40 hover:text-white hover:bg-white/10">
                <Copy className="h-3 w-3" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6 text-white/40 hover:text-white hover:bg-white/10">
                <RefreshCw className="h-3 w-3" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6 text-white/40 hover:text-white hover:bg-white/10">
                <Share2 className="h-3 w-3" />
            </Button>
        </div>
    );
}

function ErrorToolbar({ messageId, onRetry }: { messageId: string; onRetry?: (id: string) => void }) {
    return (
        <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium text-red-400">Failed to generate</span>
            {onRetry && (
                <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-red-400 hover:text-white hover:bg-white/10"
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
  function MessageList({ messages, isTyping, onRetry }, ref) {
    const { containerRef, endRef, scrollToBottom } = useScrollToBottom();

    React.useImperativeHandle(ref, () => ({
      scrollToBottom,
    }));

    return (
      <div
        ref={containerRef}
        className="flex-1 min-h-0 overflow-y-auto p-4 md:px-8"
        data-lenis-prevent
      >
        <div className="max-w-3xl mx-auto space-y-10 py-8">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "flex w-full flex-col group relative",
                msg.role === "user" ? "items-end" : "items-start"
              )}
            >
              {msg.role === "assistant" && (
                msg.content.startsWith("Error: ")
                  ? <ErrorToolbar messageId={msg.id} onRetry={onRetry} />
                  : <MessageToolbar modelName={msg.model} />
              )}

              <div
                className={cn(
                  "relative text-sm leading-7",
                  msg.role === "user"
                    ? "text-white max-w-[85%] text-right"
                    : "text-white/90 w-full pl-0"
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
                  msg.role === "assistant" && msg.content.startsWith("Error: ") && "text-red-400/80"
                )}>
                  {msg.role === "assistant" && msg.content.startsWith("Error: ")
                    ? msg.content.slice(7)
                    : msg.role === "assistant" && msg.content
                      ? <MarkdownContent content={msg.content} />
                      : msg.content || (isTyping && msg.role === "assistant" && !msg.thinking ? (
                          <span className="inline-flex gap-1 items-center h-5">
                            <span className="w-1.5 h-1.5 rounded-full bg-white/40 animate-bounce" style={{ animationDelay: '0ms' }} />
                            <span className="w-1.5 h-1.5 rounded-full bg-white/40 animate-bounce" style={{ animationDelay: '150ms' }} />
                            <span className="w-1.5 h-1.5 rounded-full bg-white/40 animate-bounce" style={{ animationDelay: '300ms' }} />
                          </span>
                        ) : null)}
                </div>
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>
      </div>
    );
  }
);
