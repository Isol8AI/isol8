import { describe, test, expect, beforeEach } from "vitest";
import {
  findPageSearchShortcutTarget,
  focusPageSearchShortcutTarget,
  hasBlockingShortcutDialog,
  isKeyboardShortcutTextInputTarget,
  resolveInboxUndoArchiveKeyAction,
  shouldBlurPageSearchOnEnter,
  shouldBlurPageSearchOnEscape,
} from "@/components/teams/shared/lib/keyboardShortcuts";

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("isKeyboardShortcutTextInputTarget", () => {
  test("true for <input>", () => {
    const el = document.createElement("input");
    document.body.appendChild(el);
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(true);
  });

  test("true for <textarea>", () => {
    const el = document.createElement("textarea");
    document.body.appendChild(el);
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(true);
  });

  test("true for <select>", () => {
    const el = document.createElement("select");
    document.body.appendChild(el);
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(true);
  });

  test("true for contenteditable div", () => {
    const el = document.createElement("div");
    el.setAttribute("contenteditable", "true");
    document.body.appendChild(el);
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(true);
  });

  test("true for contenteditable=plaintext-only", () => {
    const el = document.createElement("div");
    el.setAttribute("contenteditable", "plaintext-only");
    document.body.appendChild(el);
    // jsdom doesn't reflect contenteditable="plaintext-only" into
    // isContentEditable — but the selector match is what we care about here.
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(true);
  });

  test("true for role=textbox", () => {
    const el = document.createElement("div");
    el.setAttribute("role", "textbox");
    document.body.appendChild(el);
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(true);
  });

  test("true for role=combobox", () => {
    const el = document.createElement("div");
    el.setAttribute("role", "combobox");
    document.body.appendChild(el);
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(true);
  });

  test("true for child of contenteditable region", () => {
    const wrapper = document.createElement("div");
    wrapper.setAttribute("contenteditable", "true");
    const child = document.createElement("span");
    wrapper.appendChild(child);
    document.body.appendChild(wrapper);
    expect(isKeyboardShortcutTextInputTarget(child)).toBe(true);
  });

  test("false for plain div", () => {
    const el = document.createElement("div");
    document.body.appendChild(el);
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(false);
  });

  test("false for null", () => {
    expect(isKeyboardShortcutTextInputTarget(null)).toBe(false);
  });

  test("false for non-HTMLElement EventTarget", () => {
    // Plain EventTarget object is not an HTMLElement.
    const target = new EventTarget();
    expect(isKeyboardShortcutTextInputTarget(target)).toBe(false);
  });
});

describe("hasBlockingShortcutDialog", () => {
  test("false when no dialog in DOM", () => {
    expect(hasBlockingShortcutDialog()).toBe(false);
  });

  test("true when alertdialog is open", () => {
    const d = document.createElement("div");
    d.setAttribute("role", "alertdialog");
    document.body.appendChild(d);
    expect(hasBlockingShortcutDialog()).toBe(true);
  });

  test("true when dialog is open", () => {
    const d = document.createElement("div");
    d.setAttribute("role", "dialog");
    document.body.appendChild(d);
    expect(hasBlockingShortcutDialog()).toBe(true);
  });

  test("scoped to provided root", () => {
    const outer = document.createElement("div");
    outer.setAttribute("role", "dialog");
    document.body.appendChild(outer);

    const scope = document.createElement("section");
    document.body.appendChild(scope);
    // outer dialog is outside scope → false within scope
    expect(hasBlockingShortcutDialog(scope)).toBe(false);
    // but visible at document scope
    expect(hasBlockingShortcutDialog(document)).toBe(true);
  });
});

describe("findPageSearchShortcutTarget / focusPageSearchShortcutTarget", () => {
  test("finds element with data-page-search attribute", () => {
    const input = document.createElement("input");
    input.setAttribute("data-page-search", "");
    document.body.appendChild(input);
    expect(findPageSearchShortcutTarget()).toBe(input);
  });

  test("returns null when no [data-page-search] in DOM", () => {
    expect(findPageSearchShortcutTarget()).toBeNull();
  });

  test("focuses element with data-page-search attribute", () => {
    const input = document.createElement("input");
    input.setAttribute("data-page-search", "");
    document.body.appendChild(input);
    expect(focusPageSearchShortcutTarget()).toBe(true);
    expect(document.activeElement).toBe(input);
  });

  test("selects existing text on input when focused", () => {
    const input = document.createElement("input");
    input.setAttribute("data-page-search", "");
    input.value = "hello";
    document.body.appendChild(input);
    focusPageSearchShortcutTarget();
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(5);
  });

  test("returns false when no [data-page-search] in DOM", () => {
    expect(focusPageSearchShortcutTarget()).toBe(false);
  });

  test("skips disabled inputs", () => {
    const disabled = document.createElement("input");
    disabled.setAttribute("data-page-search", "");
    disabled.disabled = true;
    document.body.appendChild(disabled);

    const enabled = document.createElement("input");
    enabled.setAttribute("data-page-search", "");
    document.body.appendChild(enabled);

    expect(findPageSearchShortcutTarget()).toBe(enabled);
  });

  test("skips elements inside aria-hidden subtree", () => {
    const wrapper = document.createElement("div");
    wrapper.setAttribute("aria-hidden", "true");
    const hidden = document.createElement("input");
    hidden.setAttribute("data-page-search", "");
    wrapper.appendChild(hidden);
    document.body.appendChild(wrapper);

    expect(findPageSearchShortcutTarget()).toBeNull();
  });
});

describe("resolveInboxUndoArchiveKeyAction", () => {
  test("returns 'undo' on Cmd+Z", () => {
    const e = new KeyboardEvent("keydown", { key: "z", metaKey: true });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBe("undo");
  });

  test("returns 'undo' on Ctrl+Z", () => {
    const e = new KeyboardEvent("keydown", { key: "z", ctrlKey: true });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBe("undo");
  });

  test("returns 'undo' on uppercase Z with metaKey", () => {
    const e = new KeyboardEvent("keydown", { key: "Z", metaKey: true });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBe("undo");
  });

  test("returns null on plain z (no modifier)", () => {
    const e = new KeyboardEvent("keydown", { key: "z" });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBeNull();
  });

  test("returns null on Shift+Cmd+Z (redo, not undo)", () => {
    const e = new KeyboardEvent("keydown", { key: "z", metaKey: true, shiftKey: true });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBeNull();
  });

  test("returns null on Shift+Ctrl+Z (redo, not undo)", () => {
    const e = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, shiftKey: true });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBeNull();
  });

  test("returns null on Alt+Cmd+Z", () => {
    const e = new KeyboardEvent("keydown", { key: "z", metaKey: true, altKey: true });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBeNull();
  });

  test("returns null on Cmd+other-key", () => {
    const e = new KeyboardEvent("keydown", { key: "x", metaKey: true });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBeNull();
  });

  test("returns null when defaultPrevented", () => {
    const e = new KeyboardEvent("keydown", { key: "z", metaKey: true, cancelable: true });
    e.preventDefault();
    expect(resolveInboxUndoArchiveKeyAction(e)).toBeNull();
  });
});

describe("shouldBlurPageSearchOnEnter", () => {
  test("true when Enter pressed on page-search input", () => {
    const input = document.createElement("input");
    input.setAttribute("data-page-search", "");
    document.body.appendChild(input);
    const e = new KeyboardEvent("keydown", { key: "Enter" });
    Object.defineProperty(e, "target", { value: input });
    expect(shouldBlurPageSearchOnEnter(e)).toBe(true);
  });

  test("false when Enter pressed on a non-page-search element", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    const e = new KeyboardEvent("keydown", { key: "Enter" });
    Object.defineProperty(e, "target", { value: input });
    expect(shouldBlurPageSearchOnEnter(e)).toBe(false);
  });

  test("false on non-Enter key", () => {
    const input = document.createElement("input");
    input.setAttribute("data-page-search", "");
    document.body.appendChild(input);
    const e = new KeyboardEvent("keydown", { key: "a" });
    Object.defineProperty(e, "target", { value: input });
    expect(shouldBlurPageSearchOnEnter(e)).toBe(false);
  });

  test("false when isComposing (IME)", () => {
    const input = document.createElement("input");
    input.setAttribute("data-page-search", "");
    document.body.appendChild(input);
    const e = new KeyboardEvent("keydown", { key: "Enter", isComposing: true });
    Object.defineProperty(e, "target", { value: input });
    expect(shouldBlurPageSearchOnEnter(e)).toBe(false);
  });
});

describe("shouldBlurPageSearchOnEscape", () => {
  test("true when Escape pressed on page-search input", () => {
    const input = document.createElement("input");
    input.setAttribute("data-page-search", "");
    document.body.appendChild(input);
    const e = new KeyboardEvent("keydown", { key: "Escape" });
    Object.defineProperty(e, "target", { value: input });
    expect(shouldBlurPageSearchOnEscape(e)).toBe(true);
  });

  test("false when Escape pressed on a non-page-search element", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    const e = new KeyboardEvent("keydown", { key: "Escape" });
    Object.defineProperty(e, "target", { value: input });
    expect(shouldBlurPageSearchOnEscape(e)).toBe(false);
  });

  test("false on non-Escape key", () => {
    const input = document.createElement("input");
    input.setAttribute("data-page-search", "");
    document.body.appendChild(input);
    const e = new KeyboardEvent("keydown", { key: "a" });
    Object.defineProperty(e, "target", { value: input });
    expect(shouldBlurPageSearchOnEscape(e)).toBe(false);
  });

  test("false when isComposing (IME)", () => {
    const input = document.createElement("input");
    input.setAttribute("data-page-search", "");
    document.body.appendChild(input);
    const e = new KeyboardEvent("keydown", { key: "Escape", isComposing: true });
    Object.defineProperty(e, "target", { value: input });
    expect(shouldBlurPageSearchOnEscape(e)).toBe(false);
  });
});
