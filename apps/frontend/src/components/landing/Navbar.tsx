"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

export function Navbar() {
  const linksRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const linksEl = linksRef.current;
    if (!linksEl) return;

    const links = linksEl.querySelectorAll<HTMLAnchorElement>("a[data-section]");

    // Click: set active immediately
    const clickHandlers: Array<() => void> = [];
    links.forEach((link) => {
      const handler = () => {
        links.forEach((l) => l.classList.remove("active"));
        link.classList.add("active");
      };
      link.addEventListener("click", handler);
      clickHandlers.push(handler);
    });

    // Scroll: highlight whichever section is most in view
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
              l.classList.toggle(
                "active",
                l.dataset.section === id
              );
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

  return (
    <nav className="landing-nav" aria-label="Main navigation">
      <Link href="/" className="nav-logo">
        8
      </Link>
      <div className="nav-links" ref={linksRef}>
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
      </div>
      <div className="nav-right">
        <Link href="/sign-in" className="nav-login">
          Log in
        </Link>
        <Link href="/sign-up" className="btn-primary">
          Sign up
        </Link>
      </div>
    </nav>
  );
}
