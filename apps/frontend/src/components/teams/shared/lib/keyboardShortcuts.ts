// apps/frontend/src/components/teams/shared/lib/keyboardShortcuts.ts

// Ported (subset) from upstream Paperclip's lib/keyboardShortcuts.ts
// (paperclip/ui/src/lib/keyboardShortcuts.ts) (MIT, (c) 2025 Paperclip AI).
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

// Subset: pure DOM helpers used by the Inbox keyboard-nav hook (Task 6).
// Skipped from upstream: issue-detail chord shortcuts (g i / g c) and the
// resolveInboxQuickArchiveKeyAction / resolveIssueDetailGoKeyAction object-
// signature helpers — Isol8 doesn't yet have those routes/flows. The remaining
// helpers also use simpler raw-KeyboardEvent signatures (matching the consumer
// hook's call sites) rather than upstream's destructured-object signatures.

const KEYBOARD_SHORTCUT_TEXT_INPUT_SELECTOR = [
  "input",
  "textarea",
  "select",
  "[contenteditable='true']",
  "[contenteditable='plaintext-only']",
  "[role='textbox']",
  "[role='combobox']",
].join(", ");

const PAGE_SEARCH_SHORTCUT_SELECTOR = "[data-page-search]";

/**
 * True if the event target is a text-input-like element (input, textarea,
 * contenteditable, etc.). Used by keyboard-shortcut handlers to skip handling
 * single-letter shortcuts while the user is typing in a field.
 */
export function isKeyboardShortcutTextInputTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return !!target.closest(KEYBOARD_SHORTCUT_TEXT_INPUT_SELECTOR);
}

/**
 * True if there is an open Radix-style modal dialog in the DOM. Keyboard
 * shortcuts should be suppressed while a dialog is in front.
 */
export function hasBlockingShortcutDialog(root: ParentNode = document): boolean {
  return !!root.querySelector("[role='alertdialog'], [role='dialog']");
}

function isVisibleShortcutTarget(element: HTMLElement): boolean {
  if (!element.isConnected) return false;
  if ("disabled" in element && typeof (element as HTMLInputElement).disabled === "boolean" && (element as HTMLInputElement).disabled) {
    return false;
  }
  if (element.closest("[hidden], [aria-hidden='true'], [inert]")) return false;
  if (element.closest("[role='dialog'][aria-modal='true']")) return false;

  // jsdom doesn't implement layout, so getComputedStyle/getClientRects are
  // unreliable there. We fall through to a "connected and not hidden" check.
  if (typeof window !== "undefined" && typeof window.getComputedStyle === "function") {
    try {
      const style = window.getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden") return false;
    } catch {
      // ignore — jsdom edge cases
    }
  }

  return true;
}

/**
 * Find the page-search input (element annotated with `data-page-search`) in
 * the given root. Returns the first visible candidate, or null if none.
 */
export function findPageSearchShortcutTarget(root: ParentNode = document): HTMLElement | null {
  const candidates = Array.from(root.querySelectorAll<HTMLElement>(PAGE_SEARCH_SHORTCUT_SELECTOR));
  return candidates.find((candidate) => isVisibleShortcutTarget(candidate)) ?? null;
}

/**
 * Focus the page-search input. Returns true if a target was found and
 * focused, false otherwise. Selects existing text on inputs/textareas so the
 * user can immediately overwrite it.
 */
export function focusPageSearchShortcutTarget(root: ParentNode = document): boolean {
  const target = findPageSearchShortcutTarget(root);
  if (!target) return false;

  target.focus();
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
    target.select();
  }
  return true;
}

/**
 * Returns "undo" for Ctrl+Z / Cmd+Z (without Shift — Shift+Z is redo), null
 * otherwise. Used by the Inbox keyboard-nav hook to undo the last archive.
 */
export function resolveInboxUndoArchiveKeyAction(event: KeyboardEvent): "undo" | null {
  if (event.defaultPrevented) return null;
  if (event.shiftKey) return null; // Shift+Cmd+Z is redo, not undo
  if (!(event.metaKey || event.ctrlKey)) return null;
  if (event.altKey) return null;
  if (event.key.toLowerCase() !== "z") return null;
  return "undo";
}

/**
 * True if Enter pressed (and not composing) while focus is on a
 * `data-page-search` element. Caller blurs the input on true.
 */
export function shouldBlurPageSearchOnEnter(event: KeyboardEvent): boolean {
  if (event.key !== "Enter") return false;
  if (event.isComposing) return false;
  const target = event.target;
  if (!(target instanceof HTMLElement)) return false;
  return target.hasAttribute("data-page-search");
}

/**
 * True if Escape pressed (and not composing) while focus is on a
 * `data-page-search` element. Caller blurs the input on true.
 */
export function shouldBlurPageSearchOnEscape(event: KeyboardEvent): boolean {
  if (event.key !== "Escape") return false;
  if (event.isComposing) return false;
  const target = event.target;
  if (!(target instanceof HTMLElement)) return false;
  return target.hasAttribute("data-page-search");
}
