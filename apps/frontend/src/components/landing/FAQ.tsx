"use client";

import { useCallback, useState } from "react";

const faqs = [
  {
    q: "What is an agent?",
    a: "An agent is an AI that doesn\u2019t just chat \u2014 it takes action. It can read your emails, update your CRM, schedule meetings, search the web, and run multi-step tasks on its own. Think of it like a digital employee that works 24/7 and gets smarter the more you use it.",
  },
  {
    q: "What is a pod, and is my data safe?",
    a: "A pod is your own private, isolated container in the cloud \u2014 it\u2019s where your agents live and run. No other user can access your pod, your conversations, or your files. Your data never leaves your container and is never used to train models. It\u2019s your workspace, fully locked down.",
  },
  {
    q: "How is this different from ChatGPT or Claude?",
    a: "ChatGPT and Claude are chat interfaces \u2014 you ask a question, you get an answer, and it forgets you. isol8 gives you persistent agents that connect to your actual tools, remember your preferences, and take real actions across your workflows. It\u2019s less of a chatbot and more of an AI team embedded in how you work.",
  },
  {
    q: "Can I talk to my agents on Slack, WhatsApp, or Discord?",
    a: "Yes. You can connect your agents to channels like Slack, WhatsApp, Discord, and Telegram. Message them the same way you\u2019d message a coworker \u2014 they\u2019ll respond, take action, and follow up, all from the app you\u2019re already in.",
  },
  {
    q: "Can my agents run tasks on a schedule?",
    a: "Absolutely. You can set up recurring tasks \u2014 like sending a daily report, checking your inbox every morning, or syncing data between tools on a weekly basis. Your agents handle it automatically in the background, no manual work required.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes, cancel anytime with no penalty. Your pod and data are preserved for 30 days after cancellation.",
  },
];

function FaqItem({ faq, isOpen, onToggle }: { faq: typeof faqs[number]; isOpen: boolean; onToggle: () => void }) {
  const handleKeydown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onToggle();
    }
  }, [onToggle]);

  return (
    <div
      className={`faq-item${isOpen ? " open" : ""}`}
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={handleKeydown}
    >
      <h3 className="faq-q">
        {faq.q}
        <span className="faq-icon" />
      </h3>
      <div className="faq-a-wrapper" aria-hidden={!isOpen}>
        <div className="faq-a-inner">
          <p className="faq-a">{faq.a}</p>
        </div>
      </div>
    </div>
  );
}

export function FAQ() {
  const [openIndex, setOpenIndex] = useState<number>(0);

  return (
    <section className="landing-faq" id="faq">
      <div className="section-inner">
        <p className="section-eyebrow reveal">FAQ</p>
        <h2 className="section-h2 reveal">
          Questions you probably <em>have.</em>
        </h2>

        <div className="faq-list">
          {faqs.map((faq, i) => (
            <FaqItem
              key={i}
              faq={faq}
              isOpen={openIndex === i}
              onToggle={() => setOpenIndex(openIndex === i ? -1 : i)}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
