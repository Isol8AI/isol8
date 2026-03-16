"use client";

import { Check } from "lucide-react";
import { motion } from "framer-motion";
import { clsx } from "clsx";
import Link from "next/link";

const plans = [
  {
    name: "Starter",
    price: 25,
    description: "For individuals building their first pod.",
    features: [
      "1 personal pod",
      "Persistent memory & personality",
      "Core skills included",
      "Pay-per-use premium models",
      "Standard support",
    ],
    cta: "Get Started",
    highlight: false,
  },
  {
    name: "Pro",
    price: 75,
    description: "For power users who need the full toolkit.",
    features: [
      "Everything in Starter",
      "Higher usage budget",
      "All premium skills & tools",
      "All top-tier models",
      "Priority support",
    ],
    cta: "Upgrade to Pro",
    highlight: true,
  },
];

export function Pricing() {
  return (
    <section id="pricing" className="py-24 px-6 relative bg-black">
      {/* Background Glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[600px] bg-blue-900/10 rounded-full blur-[120px] pointer-events-none" />

      <div className="max-w-4xl mx-auto relative z-10">
        <div className="text-center mb-16 space-y-6">
          <h2 className="text-4xl md:text-5xl font-host text-white">Pricing</h2>
          <p className="text-white/60 font-dm max-w-xl mx-auto">
            Simple, transparent pricing. Pay a monthly fee for your pod,
            plus usage-based billing for premium models.
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-8 max-w-2xl mx-auto">
          {plans.map((plan, i) => (
            <motion.div
              key={plan.name}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.1 }}
              viewport={{ once: true }}
              className={clsx(
                "relative p-8 rounded-3xl border flex flex-col",
                plan.highlight
                  ? "bg-white/5 border-white/20 shadow-2xl shadow-blue-500/10"
                  : "bg-transparent border-white/10 hover:bg-white/5 transition-colors",
              )}
            >
              {plan.highlight && (
                <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 bg-white text-black text-xs font-bold rounded-full">
                  Popular
                </div>
              )}

              <div className="mb-8">
                <h3 className="text-lg font-bold text-white mb-2">
                  {plan.name}
                </h3>
                <div className="flex items-baseline gap-1">
                  <span className="text-4xl font-host text-white">
                    ${plan.price}
                  </span>
                  <span className="text-white/40 text-sm">/mo</span>
                </div>
                <p className="text-white/40 text-sm mt-4">
                  {plan.description}
                </p>
              </div>

              <ul className="space-y-4 mb-8 flex-1">
                {plan.features.map((feature, j) => (
                  <li
                    key={j}
                    className="flex items-start gap-3 text-sm text-white/80"
                  >
                    <Check className="w-4 h-4 text-white mt-0.5 shrink-0" />
                    {feature}
                  </li>
                ))}
              </ul>

              <Link href="/chat">
                <button
                  className={clsx(
                    "w-full py-3 rounded-full text-sm font-medium transition-transform active:scale-95",
                    plan.highlight
                      ? "bg-white text-black hover:bg-gray-100"
                      : "bg-white/10 text-white hover:bg-white/20",
                  )}
                >
                  {plan.cta}
                </button>
              </Link>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
