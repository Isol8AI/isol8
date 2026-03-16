"use client";

import { motion } from "framer-motion";
import {
  Brain,
  Sparkles,
  Shield,
  Globe,
  FileText,
  PenTool,
  Code,
  Calendar,
  BarChart3,
} from "lucide-react";

const podHighlights = [
  {
    icon: Brain,
    title: "Persistent Memory",
    desc: "Conversations carry forward — your pod remembers everything.",
  },
  {
    icon: Sparkles,
    title: "Custom Personality",
    desc: "Shape how it thinks, speaks, and approaches problems.",
  },
  {
    icon: Shield,
    title: "Fully Isolated",
    desc: "Your own private environment. No one else has access.",
  },
];

const skillCards = [
  { icon: Globe, label: "Web Search" },
  { icon: FileText, label: "File Analysis" },
  { icon: PenTool, label: "Writing" },
  { icon: Code, label: "Code" },
  { icon: Calendar, label: "Calendar" },
  { icon: BarChart3, label: "Data" },
];

export function Features() {
  return (
    <section id="features" className="py-32 px-6 bg-black">
      <div className="max-w-6xl mx-auto space-y-32">
        {/* Section 1: What is a Pod? */}
        <div className="grid md:grid-cols-2 gap-16 items-center">
          {/* Left: Pod Illustration */}
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
            className="relative aspect-square rounded-3xl overflow-hidden border border-white/10 bg-white/5"
          >
            <div className="absolute inset-0 bg-noise opacity-20" />
            <div className="absolute inset-0 flex items-center justify-center">
              {/* Pulsing pod visualization */}
              <div className="relative">
                <div className="w-40 h-40 rounded-full bg-gradient-to-tr from-blue-500/20 to-purple-500/10 blur-3xl animate-[pulse_4s_ease-in-out_infinite]" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="w-24 h-24 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center backdrop-blur-sm">
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400/60 to-purple-400/60" />
                  </div>
                </div>
              </div>
            </div>
          </motion.div>

          {/* Right: Copy */}
          <div className="space-y-10">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              className="space-y-6"
            >
              <p className="text-sm font-medium tracking-widest text-white/40 uppercase font-dm">
                Your Pod
              </p>
              <h2 className="text-4xl md:text-6xl font-host text-white leading-tight">
                A private AI <br />
                <span className="text-white/40">that&apos;s entirely yours.</span>
              </h2>
              <p className="text-lg text-white/60 font-dm leading-relaxed">
                Your pod is an isolated container running your personal AI. It
                remembers your conversations, learns your preferences, and
                develops its own personality over time. No one else has access —
                it&apos;s yours alone.
              </p>
            </motion.div>

            <div className="space-y-4">
              {podHighlights.map((item, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: 20 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: i * 0.1 }}
                  className="flex items-start gap-4 p-4 rounded-xl bg-white/5 border border-white/5"
                >
                  <item.icon className="w-5 h-5 text-white/60 mt-0.5 shrink-0" />
                  <div>
                    <h3 className="text-sm font-bold text-white font-host">
                      {item.title}
                    </h3>
                    <p className="text-sm text-white/50 font-dm">{item.desc}</p>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        </div>

        {/* Section 2: Skills & Tools */}
        <div className="grid md:grid-cols-2 gap-16 items-center">
          {/* Left: Copy */}
          <div className="space-y-10 md:order-1">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              className="space-y-6"
            >
              <p className="text-sm font-medium tracking-widest text-white/40 uppercase font-dm">
                Skills & Tools
              </p>
              <h2 className="text-4xl md:text-6xl font-host text-white leading-tight">
                Teach it <br />
                <span className="text-white/40">anything.</span>
              </h2>
              <p className="text-lg text-white/60 font-dm leading-relaxed">
                Browse and add skills to your pod — from web search and file
                analysis to writing, coding, and custom workflows. The more you
                add, the more capable your agent becomes.
              </p>
            </motion.div>

            <ul className="space-y-4">
              {[
                "Browse a growing library of skills",
                "Connect tools to your workflows",
                "Your pod learns how you use them",
              ].map((item, i) => (
                <motion.li
                  key={i}
                  initial={{ opacity: 0, x: -20 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: i * 0.1 }}
                  className="flex items-center gap-4 text-white/80 font-dm border-b border-white/5 pb-4"
                >
                  <span className="flex items-center justify-center w-8 h-8 rounded-full bg-white/10 text-xs font-mono">
                    0{i + 1}
                  </span>
                  <span>{item}</span>
                </motion.li>
              ))}
            </ul>
          </div>

          {/* Right: Skill Cards Grid */}
          <motion.div
            initial={{ opacity: 0, x: 50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
            className="grid grid-cols-3 gap-3 md:order-2"
          >
            {skillCards.map((skill, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.05 }}
                className="flex flex-col items-center gap-3 p-6 rounded-2xl bg-white/5 border border-white/5 hover:border-white/10 hover:bg-white/[0.07] transition-all cursor-default"
              >
                <skill.icon className="w-6 h-6 text-white/60" />
                <span className="text-xs font-medium text-white/70 font-dm">
                  {skill.label}
                </span>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </div>
    </section>
  );
}
