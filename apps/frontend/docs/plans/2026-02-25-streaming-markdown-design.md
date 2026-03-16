# Streaming Markdown Rendering for Chat Messages

**Date:** 2026-02-25
**Status:** Approved

## Problem

LLM responses stream markdown (code blocks, lists, tables, headings, etc.) but the frontend renders everything as plain text via `whitespace-pre-wrap`. Users see raw markdown syntax instead of formatted content.

## Solution

Use `react-markdown` + `remark-gfm` + `react-syntax-highlighter` to render assistant messages as formatted markdown in real-time as chunks stream in.

## Approach

**Approach A (chosen):** `react-markdown` with component overrides. Takes a string prop, outputs React components. No `dangerouslySetInnerHTML`, safe by default, re-renders naturally as `msg.content` grows with each streaming chunk.

**Rejected alternatives:**
- `marked` + `DOMPurify` — outputs HTML strings, requires `dangerouslySetInnerHTML`, security risk
- MDX ecosystem — overkill for rendering dynamic LLM output

## Architecture

Single-file change in `MessageList.tsx`. Streaming hooks (`useChatWebSocket`, `useChat`) are unchanged — they already accumulate content as a string.

### New Component: `MarkdownContent`

A wrapper around `react-markdown` with custom component overrides, defined in `MessageList.tsx`.

### Rendering Rules

- **Assistant messages**: rendered through `MarkdownContent`
- **User messages**: remain plain text (users don't write markdown)
- **Thinking blocks**: rendered through `MarkdownContent`
- **Error messages**: remain plain text with red styling

### Component Overrides

| Element | Styling |
|---------|---------|
| Code blocks | `bg-white/5`, syntax highlighting (oneDark), copy button, language label |
| Inline code | `bg-white/10 rounded px-1` |
| Links | `text-blue-400 hover:underline`, `target="_blank"`, `rel="noopener noreferrer"` |
| Tables | `border-white/10` borders, `bg-white/5` alternating rows |
| Headings | Sized down (h1=text-lg, h2=text-base, h3=text-sm font-semibold) |
| Lists | Proper indentation, bullets/numbers (override Tailwind reset) |
| Blockquotes | `border-l-2 border-white/20 pl-4 text-white/60` |
| Horizontal rules | `border-white/10` |

### Streaming Behavior

- `react-markdown` handles unclosed blocks gracefully mid-stream
- No debouncing needed — WebSocket hook updates per chunk, React batches renders
- `MarkdownContent` memoized so completed messages don't re-parse

### Dependencies

- `react-markdown` — core markdown-to-React renderer
- `remark-gfm` — GitHub Flavored Markdown (tables, strikethrough, task lists)
- `react-syntax-highlighter` — code block syntax highlighting
- `@types/react-syntax-highlighter` — TypeScript types

### Files Changed

- `frontend/src/components/chat/MessageList.tsx` — add `MarkdownContent`, use for assistant messages + thinking blocks

### Files NOT Changed

- `useChat.ts`, `useChatWebSocket.ts`, `useAgentChat.ts` — streaming hooks unchanged
- `ChatWindow.tsx`, `ChatInput.tsx` — no changes needed
