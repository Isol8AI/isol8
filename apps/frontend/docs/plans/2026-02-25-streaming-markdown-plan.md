# Streaming Markdown Rendering — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render LLM streaming responses as formatted markdown (code blocks, tables, lists, headings, links) instead of plain text.

**Architecture:** Single-file change in `MessageList.tsx`. Add a memoized `MarkdownContent` component wrapping `react-markdown` with dark-theme component overrides. Streaming hooks are untouched — they already pass `msg.content` as a string.

**Tech Stack:** react-markdown, remark-gfm, react-syntax-highlighter

---

### Task 1: Install Dependencies

**Files:**
- Modify: `frontend/package.json`

**Step 1: Install the three packages**

Run from `frontend/`:
```bash
npm install react-markdown remark-gfm react-syntax-highlighter
```

**Step 2: Install TypeScript types**

```bash
npm install -D @types/react-syntax-highlighter
```

**Step 3: Verify installation**

```bash
node -e "require('react-markdown'); require('remark-gfm'); require('react-syntax-highlighter'); console.log('OK')"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add package.json package-lock.json
git commit -m "feat: add react-markdown, remark-gfm, react-syntax-highlighter dependencies"
```

---

### Task 2: Build the `MarkdownContent` Component

**Files:**
- Modify: `frontend/src/components/chat/MessageList.tsx` (lines 1-6 for imports, add component after line 44)

**Step 1: Add imports to `MessageList.tsx`**

Add these imports at the top of the file, after the existing imports (line 5):

```tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
```

**Step 2: Add the `CodeBlock` helper component**

Add after the `ThinkingBlock` component (after line 44):

```tsx
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
          onClick={() => navigator.clipboard.writeText(codeString)}
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
```

**Step 3: Add the `MarkdownContent` component**

Add directly after `CodeBlock`:

```tsx
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
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
            {children}
          </a>
        ),
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
```

**Step 4: Verify the file still compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors (warnings are OK)

**Step 5: Commit**

```bash
git add src/components/chat/MessageList.tsx
git commit -m "feat: add MarkdownContent and CodeBlock components"
```

---

### Task 3: Wire `MarkdownContent` into Message Rendering

**Files:**
- Modify: `frontend/src/components/chat/MessageList.tsx` (lines 117-133)

**Step 1: Update `ThinkingBlock` to use `MarkdownContent`**

Replace line 38-39 (inside `ThinkingBlock`):

```tsx
// OLD:
        <div className="px-3 py-2 text-sm text-white/50 whitespace-pre-wrap border-t border-white/10">
          {content}
        </div>

// NEW:
        <div className="px-3 py-2 text-sm text-white/50 border-t border-white/10">
          <MarkdownContent content={content} />
        </div>
```

**Step 2: Update assistant message rendering**

Replace lines 120-133 (the content `<div>` inside the message loop):

```tsx
// OLD:
              <div className={cn(
                "whitespace-pre-wrap",
                msg.role === "assistant" && msg.content.startsWith("Error: ") && "text-red-400/80"
              )}>
                {msg.role === "assistant" && msg.content.startsWith("Error: ")
                  ? msg.content.slice(7)
                  : msg.content || (isTyping && msg.role === "assistant" && !msg.thinking ? (
                      <span className="inline-flex gap-1 items-center h-5">
                        <span className="w-1.5 h-1.5 rounded-full bg-white/40 animate-bounce" style={{ animationDelay: '0ms' }} />
                        <span className="w-1.5 h-1.5 rounded-full bg-white/40 animate-bounce" style={{ animationDelay: '150ms' }} />
                        <span className="w-1.5 h-1.5 rounded-full bg-white/40 animate-bounce" style={{ animationDelay: '300ms' }} />
                      </span>
                    ) : null)}
              </div>

// NEW:
              <div className={cn(
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
```

Key changes:
- `whitespace-pre-wrap` only applied to user messages (markdown handles its own whitespace)
- Assistant messages with content route through `<MarkdownContent>`
- Error messages and loading spinner unchanged

**Step 3: Verify the file still compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors

**Step 4: Commit**

```bash
git add src/components/chat/MessageList.tsx
git commit -m "feat: render assistant messages and thinking blocks as markdown"
```

---

### Task 4: Write Tests

**Files:**
- Create: `frontend/src/__tests__/MarkdownContent.test.tsx`

**Step 1: Write tests for markdown rendering**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageList } from "@/components/chat/MessageList";

describe("MessageList markdown rendering", () => {
  it("renders plain assistant text", () => {
    render(
      <MessageList
        messages={[{ id: "1", role: "assistant", content: "Hello world" }]}
      />
    );
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("renders bold text in assistant messages", () => {
    render(
      <MessageList
        messages={[{ id: "1", role: "assistant", content: "This is **bold** text" }]}
      />
    );
    const bold = screen.getByText("bold");
    expect(bold.tagName).toBe("STRONG");
  });

  it("renders inline code in assistant messages", () => {
    render(
      <MessageList
        messages={[{ id: "1", role: "assistant", content: "Use `console.log`" }]}
      />
    );
    const code = screen.getByText("console.log");
    expect(code.tagName).toBe("CODE");
  });

  it("renders links with target _blank", () => {
    render(
      <MessageList
        messages={[{ id: "1", role: "assistant", content: "Visit [Google](https://google.com)" }]}
      />
    );
    const link = screen.getByText("Google");
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders unordered lists", () => {
    render(
      <MessageList
        messages={[{ id: "1", role: "assistant", content: "- item one\n- item two" }]}
      />
    );
    expect(screen.getByText("item one")).toBeInTheDocument();
    expect(screen.getByText("item two")).toBeInTheDocument();
  });

  it("does NOT render markdown in user messages", () => {
    render(
      <MessageList
        messages={[{ id: "1", role: "user", content: "This is **not bold**" }]}
      />
    );
    // Should render as literal text with asterisks
    expect(screen.getByText("This is **not bold**")).toBeInTheDocument();
  });

  it("renders error messages as plain text", () => {
    render(
      <MessageList
        messages={[{ id: "1", role: "assistant", content: "Error: something broke" }]}
      />
    );
    expect(screen.getByText("something broke")).toBeInTheDocument();
  });
});
```

**Step 2: Run the tests**

```bash
cd frontend && npm test -- --reporter verbose src/__tests__/MarkdownContent.test.tsx
```
Expected: all 7 tests pass

**Step 3: Commit**

```bash
git add src/__tests__/MarkdownContent.test.tsx
git commit -m "test: add markdown rendering tests for MessageList"
```

---

### Task 5: Build Verification

**Step 1: Run full type check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors

**Step 2: Run linter**

```bash
cd frontend && npm run lint
```
Expected: no new errors

**Step 3: Run production build**

```bash
cd frontend && npm run build
```
Expected: build succeeds

**Step 4: Run full test suite**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird && ./run_tests.sh
```
Expected: all tests pass (including new markdown tests)

**Step 5: Commit if any lint fixes were needed**

```bash
git add -A && git commit -m "fix: lint fixes for markdown rendering"
```
(Skip if no changes)
