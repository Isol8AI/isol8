"use client";

import Link from "next/link";
import { motion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";

export function Hero() {
  const containerRef = useRef(null);
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start start", "end start"],
  });

  const orbY = useTransform(scrollYProgress, [0, 1], ["0%", "30%"]);
  const orbScale = useTransform(scrollYProgress, [0, 1], [1, 1.2]);
  const opacity = useTransform(scrollYProgress, [0, 0.6], [1, 0]);

  return (
    <section
      ref={containerRef}
      className="relative flex flex-col items-center justify-center min-h-screen px-4 py-32 overflow-hidden bg-black"
    >
      {/* Animated Orb */}
      <motion.div
        style={{ y: orbY, scale: orbScale }}
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-0 pointer-events-none"
      >
        <div className="relative w-[500px] h-[500px] md:w-[600px] md:h-[600px]">
          {/* Outer glow */}
          <div className="absolute inset-0 rounded-full bg-gradient-to-tr from-blue-500/20 via-purple-500/15 to-cyan-500/10 blur-[100px] animate-pulse" />
          {/* Inner orb */}
          <div className="absolute inset-[15%] rounded-full bg-gradient-to-br from-blue-500/30 via-purple-600/20 to-indigo-500/30 blur-[60px] animate-[pulse_4s_ease-in-out_infinite]" />
          {/* Core */}
          <div className="absolute inset-[30%] rounded-full bg-gradient-to-tr from-white/10 via-blue-400/15 to-purple-400/10 blur-[40px] animate-[pulse_3s_ease-in-out_infinite]" />
        </div>
      </motion.div>

      {/* Content */}
      <motion.div style={{ opacity }} className="relative z-10 max-w-4xl mx-auto text-center space-y-8">
        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
          className="text-5xl md:text-8xl font-normal leading-[0.95] tracking-tighter text-white font-host"
        >
          Your AI <br />
          <span className="text-white/50">right hand.</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
          className="max-w-xl mx-auto text-lg text-white/60 font-dm leading-relaxed"
        >
          A personal AI agent that handles the tasks you don&apos;t want to —
          with persistent memory, custom personality, and real skills.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, delay: 0.4, ease: [0.16, 1, 0.3, 1] }}
          className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-4"
        >
          <Link
            href="/chat"
            className="px-8 py-3 text-base font-medium text-black bg-white rounded-full hover:scale-105 transition-transform duration-300 shadow-xl shadow-white/10"
          >
            Create Your Pod
          </Link>
          <Link
            href="#features"
            className="px-8 py-3 text-base font-medium text-white border border-white/20 rounded-full hover:bg-white/5 transition-colors backdrop-blur-sm"
          >
            See How It Works
          </Link>
        </motion.div>
      </motion.div>
    </section>
  );
}
