"use client";

import { useEffect } from "react";

export function ScrollManager() {
  useEffect(() => {
    // Scroll progress bar
    const progressBar = document.getElementById("scrollProgress");
    const scrollHandler = () => {
      if (!progressBar) return;
      const scrollTop = document.documentElement.scrollTop;
      const scrollHeight =
        document.documentElement.scrollHeight - window.innerHeight;
      progressBar.style.width = (scrollTop / scrollHeight) * 100 + "%";
    };
    window.addEventListener("scroll", scrollHandler, { passive: true });

    // Scroll reveal
    const revealObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("visible");
            revealObserver.unobserve(e.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -40px 0px" }
    );
    document
      .querySelectorAll(".reveal")
      .forEach((el) => revealObserver.observe(el));

    // Console easter egg
    console.log(
      "%c🏝️ isol8 %c— Your private AI pod",
      "font-size:20px;font-weight:900;color:#06402B;",
      "font-size:14px;color:#888;"
    );
    console.log(
      "%cCurious? We like that. → https://isol8.co",
      "font-size:11px;color:#4a9e74;"
    );

    return () => {
      window.removeEventListener("scroll", scrollHandler);
      revealObserver.disconnect();
    };
  }, []);

  return <div className="scroll-progress" id="scrollProgress" />;
}
