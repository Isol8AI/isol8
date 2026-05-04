# Mobile Responsive Fix — Implementation Plan

**Status:** In progress

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the entire isol8 frontend (landing page + chat app + settings) fully usable on mobile devices.

**Architecture:** CSS media queries in `globals.css` for all landing page sections (stack grids, reduce padding, hamburger nav). Minimal JS state additions in `Navbar.tsx` (hamburger toggle) and `ChatLayout.tsx` (sidebar drawer toggle). Settings page gets CSS-only stacking.

**Tech Stack:** CSS media queries, React state for interactive toggles, existing Tailwind utilities where already used.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `apps/frontend/src/app/globals.css` | Modify (lines 138–586) | Add mobile breakpoints for all landing sections |
| `apps/frontend/src/components/landing/Navbar.tsx` | Modify | Add hamburger button + mobile menu state |
| `apps/frontend/src/components/chat/ChatLayout.tsx` | Modify (inline styles + JSX) | Add hamburger button in header, sidebar drawer overlay on mobile |
| `apps/frontend/src/app/settings/page.tsx` | Modify (inline styles) | Add mobile breakpoints for settings layout |

---

### Task 1: Landing Navbar — Mobile Hamburger Menu

**Files:**
- Modify: `apps/frontend/src/components/landing/Navbar.tsx`
- Modify: `apps/frontend/src/app/globals.css` (add after line 196, before `/* ── HERO ── */`)

**Why:** On mobile, the 3-column grid navbar overflows. We collapse nav links behind a hamburger, keep logo + "Sign up" visible.

- [ ] **Step 1: Add hamburger state and button to Navbar.tsx**

Replace the entire `Navbar` component in `apps/frontend/src/components/landing/Navbar.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

export function Navbar() {
  const linksRef = useRef<HTMLDivElement>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const linksEl = linksRef.current;
    if (!linksEl) return;

    const links = linksEl.querySelectorAll<HTMLAnchorElement>("a[data-section]");

    const clickHandlers: Array<() => void> = [];
    links.forEach((link) => {
      const handler = () => {
        links.forEach((l) => l.classList.remove("active"));
        link.classList.add("active");
        setMobileOpen(false);
      };
      link.addEventListener("click", handler);
      clickHandlers.push(handler);
    });

    const sections = [
      { id: "home", el: document.querySelector(".landing-hero") },
      { id: "features", el: document.getElementById("features") },
      { id: "pricing", el: document.getElementById("pricing") },
      { id: "faq", el: document.getElementById("faq") },
      { id: "goosetown", el: document.getElementById("goosetown") },
    ].filter((s) => s.el);

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const id = entry.target.id || "home";
            links.forEach((l) => {
              l.classList.toggle("active", l.dataset.section === id);
            });
          }
        });
      },
      { threshold: 0.35 }
    );

    sections.forEach((s) => observer.observe(s.el!));

    return () => {
      observer.disconnect();
      links.forEach((link, i) => {
        link.removeEventListener("click", clickHandlers[i]);
      });
    };
  }, []);

  // Close mobile menu on resize to desktop
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 769px)");
    const handler = () => { if (mq.matches) setMobileOpen(false); };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return (
    <nav className="landing-nav" aria-label="Main navigation">
      <Link href="/" className="nav-logo">
        8
      </Link>
      <div className={`nav-links${mobileOpen ? " mobile-open" : ""}`} ref={linksRef}>
        <Link href="/" data-section="home" className="active">
          Home
        </Link>
        <Link href="#features" data-section="features">
          Features
        </Link>
        <Link href="#pricing" data-section="pricing">
          Pricing
        </Link>
        <Link href="#faq" data-section="faq">
          FAQ
        </Link>
        <Link href="#goosetown" data-section="goosetown">
          GooseTown<span className="nav-alpha">alpha</span>
        </Link>
        <Link href="/sign-in" className="nav-mobile-login">
          Log in
        </Link>
      </div>
      <div className="nav-right">
        <Link href="/sign-in" className="nav-login">
          Log in
        </Link>
        <Link href="/sign-up" className="btn-primary">
          Sign up
        </Link>
        <button
          className="nav-hamburger"
          onClick={() => setMobileOpen((v) => !v)}
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          aria-expanded={mobileOpen}
        >
          <span className={`hamburger-line${mobileOpen ? " open" : ""}`} />
          <span className={`hamburger-line${mobileOpen ? " open" : ""}`} />
          <span className={`hamburger-line${mobileOpen ? " open" : ""}`} />
        </button>
      </div>
      {mobileOpen && <div className="nav-mobile-backdrop" onClick={() => setMobileOpen(false)} />}
    </nav>
  );
}
```

- [ ] **Step 2: Add navbar mobile CSS to globals.css**

Add the following CSS block in `globals.css` after the `.btn-large:active` rule (after line 221) and before `/* ── HERO ── */`:

```css
/* ── NAV MOBILE ── */
.nav-hamburger {
  display: none;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  flex-direction: column;
  gap: 5px;
  z-index: 60;
}
.hamburger-line {
  display: block;
  width: 20px;
  height: 2px;
  background: #1a1a1a;
  border-radius: 1px;
  transition: transform 0.25s ease, opacity 0.25s ease;
}
.hamburger-line.open:nth-child(1) { transform: translateY(7px) rotate(45deg); }
.hamburger-line.open:nth-child(2) { opacity: 0; }
.hamburger-line.open:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }
.nav-mobile-login { display: none; }
.nav-mobile-backdrop { display: none; }

@media (max-width: 768px) {
  .landing-nav {
    grid-template-columns: 1fr auto;
    padding: 12px 16px;
  }
  .nav-links {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: rgba(250,247,242,0.98);
    backdrop-filter: blur(12px);
    flex-direction: column;
    padding: 16px;
    gap: 4px;
    border-bottom: 1px solid #e0dbd0;
    box-shadow: 0 8px 24px rgba(0,0,0,0.08);
    z-index: 55;
  }
  .nav-links.mobile-open { display: flex; }
  .nav-links a { padding: 12px 16px; font-size: 15px; border-radius: 8px; }
  .nav-mobile-login { display: block; }
  .nav-login { display: none; }
  .nav-hamburger { display: flex; }
  .nav-mobile-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 49;
    background: rgba(0,0,0,0.2);
  }
}
```

- [ ] **Step 3: Verify navbar renders on desktop and mobile**

Run: `cd apps/frontend && pnpm run dev`

Open in browser at `localhost:3000`:
- Desktop (>768px): navbar should look identical to current — logo, centered links, login + sign up
- Mobile (≤768px): logo on left, sign up + hamburger on right. Tapping hamburger shows dropdown with all links + "Log in"

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/landing/Navbar.tsx apps/frontend/src/app/globals.css
git commit -m "feat: add mobile hamburger menu to landing navbar"
```

---

### Task 2: Landing Hero — Stack on Mobile

**Files:**
- Modify: `apps/frontend/src/app/globals.css` (lines 224–258)

**Why:** Hero uses a 2-column grid that squishes the workflow animation on mobile. We stack it vertically and reduce padding.

- [ ] **Step 1: Add hero mobile breakpoint**

Add after the `.hero-right::before` rule (after line 258) in `globals.css`:

```css
@media (max-width: 768px) {
  .landing-hero {
    grid-template-columns: 1fr;
    min-height: auto;
  }
  .hero-left {
    padding: 48px 24px;
    border-right: none;
    border-bottom: 1px solid #e0dbd0;
  }
  .hero-h1 { font-size: 36px; }
  .hero-sub { font-size: 15px; margin-bottom: 32px; }
  .hero-right { padding: 24px 16px; }
}
```

- [ ] **Step 2: Verify hero stacks on mobile**

Resize browser to ≤768px:
- Hero should stack: text on top, workflow animation below
- Padding should be reasonable, text readable
- Desktop layout unchanged

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/globals.css
git commit -m "feat: stack hero section on mobile"
```

---

### Task 3: Landing Features — Stack on Mobile

**Files:**
- Modify: `apps/frontend/src/app/globals.css` (after line 340)

**Why:** 3-column feature grid overflows on mobile.

- [ ] **Step 1: Add features mobile breakpoint**

Add after the `.feat-desc` rule (line 340):

```css
@media (max-width: 768px) {
  .landing-features { padding: 64px 20px; }
  .feat-grid { grid-template-columns: 1fr; gap: 0; }
  .feat-card { padding: 32px 24px; }
  .section-h2 { margin-bottom: 40px; }
}
```

- [ ] **Step 2: Verify features stack**

At ≤768px: cards should stack vertically, full width, with readable padding. Desktop unchanged.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/globals.css
git commit -m "feat: stack feature cards on mobile"
```

---

### Task 4: Landing Skills — Stack on Mobile

**Files:**
- Modify: `apps/frontend/src/app/globals.css` (after line 360)

**Why:** 2-column skills layout with 3x3 card grid gets cramped on mobile.

- [ ] **Step 1: Add skills mobile breakpoint**

Add after the `.skill-card.highlight-card .skill-card-label` rule (line 360):

```css
@media (max-width: 768px) {
  .landing-skills { padding: 64px 20px; }
  .skills-inner { grid-template-columns: 1fr; gap: 40px; }
  .skill-grid { grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .skill-card { padding: 20px 12px; }
}
@media (max-width: 480px) {
  .skill-grid { grid-template-columns: repeat(2, 1fr); }
}
```

- [ ] **Step 2: Verify skills section stacks**

At ≤768px: text and skill grid stack vertically. Grid stays 3-col but narrower.
At ≤480px: grid becomes 2-col for tighter screens.
Desktop unchanged.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/globals.css
git commit -m "feat: stack skills section on mobile"
```

---

### Task 5: Landing Pricing — Stack on Mobile

**Files:**
- Modify: `apps/frontend/src/app/globals.css` (after line 385)

**Why:** 2-column pricing grid squishes cards on mobile.

- [ ] **Step 1: Add pricing mobile breakpoint**

Add after the `.plan-cta.featured:active` rule (line 385):

```css
@media (max-width: 768px) {
  .landing-pricing { padding: 64px 20px; }
  .price-grid { grid-template-columns: 1fr; max-width: 100%; }
}
```

- [ ] **Step 2: Verify pricing stacks**

At ≤768px: pricing cards stack vertically, full width. Desktop unchanged.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/globals.css
git commit -m "feat: stack pricing cards on mobile"
```

---

### Task 6: Landing FAQ — Mobile Padding

**Files:**
- Modify: `apps/frontend/src/app/globals.css` (after line 408)

**Why:** FAQ has generous desktop padding that wastes space on mobile.

- [ ] **Step 1: Add FAQ mobile breakpoint**

Add after the `.faq-item.open .faq-a` rule (line 408):

```css
@media (max-width: 768px) {
  .landing-faq { padding: 64px 20px; }
  .faq-q { font-size: 16px; }
}
```

- [ ] **Step 2: Verify FAQ padding**

At ≤768px: FAQ has tighter padding, slightly smaller question font. Desktop unchanged.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/globals.css
git commit -m "feat: adjust FAQ padding on mobile"
```

---

### Task 7: Landing GooseTown + Transition — Stack on Mobile

**Files:**
- Modify: `apps/frontend/src/app/globals.css` (after line 554)

**Why:** GooseTown uses a 2-column grid with a complex pixel art game window that becomes unusable on small screens.

- [ ] **Step 1: Add GooseTown mobile breakpoints**

Add after the `.px-char` rule block (after line 554), before `/* ── SCROLL PROGRESS ── */`:

```css
@media (max-width: 768px) {
  .landing-goosetown { padding: 64px 20px; }
  .gt-inner { grid-template-columns: 1fr; gap: 40px; }
  .gt-game-wrap { max-width: 100%; overflow-x: hidden; }
  .gt-game-body { flex-direction: column; }
  .gt-sidebar { width: 100%; border-right: none; border-bottom: 2px solid #18283a; }
  .gt-viewport { min-height: 200px; }
  .gt-warp-title { font-size: 18px; letter-spacing: 2px; }
}
```

- [ ] **Step 2: Verify GooseTown stacks**

At ≤768px: text and game window stack vertically. Game sidebar goes above viewport. Desktop unchanged.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/globals.css
git commit -m "feat: stack GooseTown section on mobile"
```

---

### Task 8: Landing Footer — Mobile Layout

**Files:**
- Modify: `apps/frontend/src/app/globals.css` (after line 568)

**Why:** Footer flexbox wraps awkwardly on mobile.

- [ ] **Step 1: Add footer mobile breakpoint**

Add after the `.footer-copy` rule (line 568):

```css
@media (max-width: 768px) {
  .landing-footer { padding: 32px 20px; }
  .footer-inner { flex-direction: column; text-align: center; gap: 16px; }
  .footer-links { justify-content: center; gap: 20px; flex-wrap: wrap; }
}
```

- [ ] **Step 2: Verify footer stacks**

At ≤768px: footer items center and stack vertically. Desktop unchanged.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/globals.css
git commit -m "feat: stack footer on mobile"
```

---

### Task 9: Chat App — Mobile Hamburger Sidebar Drawer

**Files:**
- Modify: `apps/frontend/src/components/chat/ChatLayout.tsx`

**Why:** On mobile, the 260px sidebar is hidden via `display:none` with no replacement. Users can't switch agents or access control panels. We add a hamburger icon in the header that opens the sidebar as a slide-in drawer overlay.

- [ ] **Step 1: Add mobile drawer state and hamburger button**

In `ChatLayout.tsx`, add `Menu, X` to the lucide-react import:

```tsx
import { Settings, Plus, Bot, CheckCircle, CreditCard, Menu, X } from "lucide-react";
```

Add state inside the `ChatLayout` function, after the `recoveryTriggered` state:

```tsx
const [sidebarOpen, setSidebarOpen] = useState(false);
```

- [ ] **Step 2: Update the mobile CSS breakpoint in the inline styles**

Replace the existing `@media (max-width: 768px)` block (lines 384–391) in the inline `<style>` with:

```css
@media (max-width: 768px) {
  .app-shell {
    grid-template-columns: 1fr;
  }
  .cream-sidebar {
    display: none;
  }
  .cream-sidebar.mobile-open {
    display: flex;
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 280px;
    z-index: 50;
    box-shadow: 4px 0 24px rgba(0,0,0,0.15);
  }
  .sidebar-backdrop {
    display: none;
  }
  .sidebar-backdrop.visible {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.3);
    z-index: 49;
  }
  .mobile-hamburger {
    display: flex;
  }
}
```

Also add this rule in the main (non-media-query) section of the inline styles, after `.main-content`:

```css
.mobile-hamburger {
  display: none;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  color: #8a8578;
  transition: color 0.15s;
}
.mobile-hamburger:hover {
  color: #1a1a1a;
}
.sidebar-backdrop {
  display: none;
}
```

- [ ] **Step 3: Update JSX for sidebar drawer + hamburger**

Replace the `<div className="cream-sidebar">` opening tag with:

```tsx
<div className={`cream-sidebar${sidebarOpen ? " mobile-open" : ""}`}>
```

Add the backdrop div right after `<div className="app-shell">` (before `<div className="cream-sidebar ...`):

```tsx
<div className={`sidebar-backdrop${sidebarOpen ? " visible" : ""}`} onClick={() => setSidebarOpen(false)} />
```

Add a hamburger button in the `main-header` div, before the `<UserButton>`:

```tsx
<div className="main-header">
  <button className="mobile-hamburger" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
    <Menu size={22} />
  </button>
  <div style={{ flex: 1 }} />
  <UserButton
```

Update the sidebar header to include a close button on mobile. Replace the sidebar-header div:

```tsx
<div className="sidebar-header">
  <div className="sidebar-logo">
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="3" width="18" height="18" rx="4" fill="#1a1a1a"/>
      <rect x="7" y="7" width="4" height="4" rx="1" fill="#f3efe6"/>
      <rect x="13" y="7" width="4" height="4" rx="1" fill="#f3efe6"/>
      <rect x="7" y="13" width="4" height="4" rx="1" fill="#f3efe6"/>
      <rect x="13" y="13" width="4" height="4" rx="1" fill="#2d8a4e"/>
    </svg>
    <span>isol8</span>
  </div>
  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
    <Link href="/settings" className="sidebar-settings-link">
      <Settings size={18} />
    </Link>
    <button className="mobile-hamburger" onClick={() => setSidebarOpen(false)} aria-label="Close menu" style={{ display: sidebarOpen ? "flex" : undefined }}>
      <X size={18} />
    </button>
  </div>
</div>
```

- [ ] **Step 4: Close sidebar on agent selection and navigation**

Update `handleSelectAgent` to also close the sidebar:

```tsx
function handleSelectAgent(agentId: string): void {
  setUserSelectedId(agentId);
  dispatchSelectAgentEvent(agentId);
  setSidebarOpen(false);
}
```

Update the `onViewChange` callback usage — when the user taps Chat/Control tabs, close the drawer:

```tsx
<button
  className={`tab-btn${activeView === "chat" ? " active" : ""}`}
  onClick={() => { onViewChange("chat"); setSidebarOpen(false); }}
>
  Chat
</button>
<button
  className={`tab-btn${activeView === "control" ? " active" : ""}`}
  onClick={() => { onViewChange("control"); setSidebarOpen(false); }}
>
  Control
</button>
```

- [ ] **Step 5: Verify chat mobile drawer**

Run: `cd apps/frontend && pnpm run dev`

At ≤768px:
- Sidebar hidden by default
- Hamburger icon visible in header bar
- Tapping hamburger slides sidebar in from left with backdrop
- Selecting an agent closes drawer
- Tapping backdrop closes drawer
- Close button (X) inside sidebar header closes drawer
- Desktop: identical to current

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/chat/ChatLayout.tsx
git commit -m "feat: add mobile hamburger drawer for chat sidebar"
```

---

### Task 10: Chat App — Mobile Banner Button Wrapping

**Files:**
- Modify: `apps/frontend/src/components/chat/AgentChatWindow.tsx`

**Why:** The update banner has 3 buttons in a row that overflow on mobile.

- [ ] **Step 1: Add flex-wrap to update banner buttons**

In the `UpdateBanner` component, find the button container div (around line 386):

```tsx
<div className="flex items-center gap-2 mt-2 ml-7">
```

Replace with:

```tsx
<div className="flex items-center gap-2 mt-2 ml-7 flex-wrap">
```

- [ ] **Step 2: Verify buttons wrap on mobile**

At narrow widths, the 3 update buttons ("Update Now", "Tonight at 2 AM", "Remind Me Later") should wrap to a second line rather than overflowing.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/chat/AgentChatWindow.tsx
git commit -m "fix: wrap update banner buttons on mobile"
```

---

### Task 11: Settings Page — Mobile Layout

**Files:**
- Modify: `apps/frontend/src/app/settings/page.tsx` (inline styles)

**Why:** Settings uses a 2-column grid (240px sidebar + content) that doesn't adapt on mobile.

- [ ] **Step 1: Add settings mobile breakpoint**

In the `settingsStyles` template literal in `settings/page.tsx`, find the end of the styles (before the closing backtick). Add:

```css
/* Mobile */
@media (max-width: 768px) {
  .settings-topbar { padding: 12px 16px; }
  .settings-btn-back-chat span { display: none; }
  .settings-layout {
    grid-template-columns: 1fr;
    min-height: auto;
  }
  .settings-nav {
    position: static;
    padding: 16px 16px 0;
    border-right: none;
    border-bottom: 1px solid #e0dbd0;
  }
  .settings-nav-items {
    flex-direction: row;
    gap: 4px;
  }
  .settings-nav-item {
    padding: 8px 14px;
    min-height: 36px;
    font-size: 13px;
  }
  .settings-main {
    padding: 24px 16px;
  }
  .settings-page-title { font-size: 22px; }
  .settings-card { padding: 20px 16px; }
  .settings-card-header { flex-direction: column; align-items: flex-start; gap: 12px; }
  .settings-tier-grid { grid-template-columns: 1fr; }
  .settings-profile-row { flex-direction: column; text-align: center; }
  .settings-profile-avatar-lg { margin: 0 auto; }
}
```

- [ ] **Step 2: Verify settings page on mobile**

At ≤768px:
- Sidebar nav becomes a horizontal tab row above content
- Content has tighter padding
- Plan tier cards stack vertically
- Profile avatar centers above name
- Desktop: identical to current

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/settings/page.tsx
git commit -m "feat: add mobile responsive layout to settings page"
```

---

### Task 12: Final Visual QA Pass

**Files:** All modified files

**Why:** Ensure no regressions on desktop and everything looks good on mobile.

- [ ] **Step 1: Run the dev server**

```bash
cd apps/frontend && pnpm run dev
```

- [ ] **Step 2: Check landing page at 375px width (iPhone SE)**

Verify each section in order:
1. Navbar: logo + sign up + hamburger. Hamburger opens dropdown with all links
2. Hero: stacked, readable text, workflow animation visible below
3. Features: single column cards
4. Skills: stacked, 3-col (or 2-col at 375px) skill grid
5. Pricing: single column cards
6. FAQ: readable, proper padding
7. GooseTown: stacked, game window usable
8. Footer: centered, stacked

- [ ] **Step 3: Check chat app at 375px width**

1. No sidebar visible by default
2. Hamburger in header opens sidebar drawer from left
3. Agent list accessible, selecting agent closes drawer
4. Chat input stays at bottom
5. Messages render with no horizontal overflow
6. Update banner buttons wrap

- [ ] **Step 4: Check settings page at 375px width**

1. Nav tabs horizontal above content
2. Profile and billing panels readable
3. Plan tier cards stacked

- [ ] **Step 5: Check all pages at desktop (1440px)**

Everything should look identical to the current production layout.

- [ ] **Step 6: Run linter**

```bash
cd apps/frontend && pnpm run lint
```

Expected: no new lint errors

- [ ] **Step 7: Commit any final fixes**

```bash
git add -A
git commit -m "fix: visual QA adjustments for mobile responsive"
```
