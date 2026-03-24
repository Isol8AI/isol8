"use client";

import { useEffect } from "react";

const faqs = [
  {
    q: "What exactly is a pod?",
    a: "A pod is your own isolated AI container — a private environment running a Claude-powered agent that belongs only to you. It stores your memory, runs your skills, and connects to your tools.",
  },
  {
    q: "How is this different from ChatGPT or Claude.ai?",
    a: "Those are shared, stateless interfaces. Your isol8 pod is a dedicated environment with persistent memory, customizable personality, real integrations, and a running process that's always on.",
  },
  {
    q: "Is my data private?",
    a: "Yes. Your pod is fully isolated — no other user has access to your container, memory, or conversations. Your data doesn't train models.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes, cancel anytime with no penalty. Your pod and data are preserved for 30 days after cancellation.",
  },
];

export function FAQ() {
  useEffect(() => {
    const items = document.querySelectorAll(".faq-item");
    if (!items.length) return;

    // Open first FAQ by default
    items[0].classList.add("open");

    const cleanups: Array<() => void> = [];

    items.forEach((item) => {
      const toggle = () => {
        const wasOpen = item.classList.contains("open");
        items.forEach((i) => i.classList.remove("open"));
        if (!wasOpen) item.classList.add("open");
      };
      const onKeydown = (e: Event) => {
        const key = (e as KeyboardEvent).key;
        if (key === "Enter" || key === " ") {
          e.preventDefault();
          toggle();
        }
      };
      item.addEventListener("click", toggle);
      item.addEventListener("keydown", onKeydown);
      cleanups.push(() => {
        item.removeEventListener("click", toggle);
        item.removeEventListener("keydown", onKeydown);
      });
    });

    return () => {
      cleanups.forEach((fn) => fn());
    };
  }, []);

  return (
    <section className="landing-faq" id="faq">
      <div className="section-inner">
        <p className="section-eyebrow reveal">FAQ</p>
        <h2 className="section-h2 reveal">
          Questions you probably <em>have.</em>
        </h2>

        <div className="faq-list">
          {faqs.map((faq, i) => (
            <div className="faq-item" role="button" tabIndex={0} key={i}>
              <h3 className="faq-q">{faq.q}</h3>
              <p className="faq-a">{faq.a}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
