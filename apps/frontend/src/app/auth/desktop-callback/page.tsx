"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

const STEPS = [
  {
    title: "Signing you in",
    desc: "Authenticating with your isol8 account",
  },
  {
    title: "Opening your pod",
    desc: "Spinning up your isolated container",
  },
  {
    title: "Connecting to gateway",
    desc: "Establishing a secure tunnel to your agent",
  },
  {
    title: "You\u2019re all set",
    desc: "Redirecting to your dashboard",
  },
];

export default function DesktopCallback() {
  const { isSignedIn, getToken } = useAuth();
  const [currentStep, setCurrentStep] = useState(0);
  const [fading, setFading] = useState(false);
  const [podOpen, setPodOpen] = useState(false);
  const [gateOpening, setGateOpening] = useState(false);
  const redirectedRef = useRef(false);

  const goToStep = useCallback((n: number) => {
    setFading(true);
    setTimeout(() => {
      setCurrentStep(n);
      setFading(false);
      // Trigger step-specific animations after a short delay
      if (n === 1) {
        setTimeout(() => setPodOpen(true), 300);
      } else if (n === 2) {
        setTimeout(() => setGateOpening(true), 300);
      }
    }, 150);
  }, []);

  // Timer-based progression for steps 1-3
  useEffect(() => {
    const t1 = setTimeout(() => goToStep(1), 2200);
    const t2 = setTimeout(() => goToStep(2), 4400);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [goToStep]);

  // Auth flow — triggers step 4 on successful redirect
  useEffect(() => {
    if (!isSignedIn) return;

    getToken().then((token) => {
      if (token && !redirectedRef.current) {
        redirectedRef.current = true;
        // Move to final step, then redirect
        goToStep(3);
        setTimeout(() => {
          window.location.href = `isol8://auth?token=${encodeURIComponent(token)}`;
        }, 1200);
      }
    });
  }, [isSignedIn, getToken, goToStep]);

  const step = STEPS[currentStep];

  return (
    <>
      <style>{callbackStyles}</style>
      <div className="callback-wrapper">
        <div className="callback-card" role="main">
          <Link href="/" className="cb-logo" aria-label="isol8 home">
            <svg
              width="48"
              height="48"
              viewBox="0 0 100 100"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <rect width="100" height="100" rx="22" fill="#06402B" />
              <text
                x="50"
                y="68"
                textAnchor="middle"
                fontFamily="var(--font-lora-serif), serif"
                fontStyle="italic"
                fontSize="52"
                fill="white"
              >
                8
              </text>
            </svg>
          </Link>

          {/* Animation stage */}
          <div className="cb-stage" aria-hidden="true">
            {/* Step 1: Key spinner */}
            <div className={`cb-anim ${currentStep === 0 ? "active" : ""}`}>
              <div className="anim-key">
                <div className="anim-key-circle" />
                <div className="anim-key-icon">
                  <svg
                    width="28"
                    height="28"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="#06402B"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.78 7.78 5.5 5.5 0 0 1 7.78-7.78zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
                  </svg>
                </div>
              </div>
            </div>

            {/* Step 2: Pod opening */}
            <div className={`cb-anim ${currentStep === 1 ? "active" : ""}`}>
              <div className={`anim-pod ${podOpen ? "pod-open" : ""}`}>
                <div className="pod-steam">
                  <div className="pod-steam-line" />
                  <div className="pod-steam-line" />
                  <div className="pod-steam-line" />
                </div>
                <div className="pod-lid-l" />
                <div className="pod-lid-r" />
                <div className="pod-body">
                  <div className="pod-window" />
                </div>
              </div>
            </div>

            {/* Step 3: Gateway */}
            <div className={`cb-anim ${currentStep === 2 ? "active" : ""}`}>
              <div className={`anim-gate ${gateOpening ? "gate-opening" : ""}`}>
                <div className="gate-frame">
                  <div className="gate-glow" />
                  <div className="gate-door-l" />
                  <div className="gate-door-r" />
                  <div className="gate-signal">
                    <svg
                      width="12"
                      height="12"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="#06402B"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                    >
                      <path d="M5 12.55a11 11 0 0 1 14.08 0" />
                      <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
                      <circle cx="12" cy="20" r="1" fill="#06402B" />
                    </svg>
                  </div>
                </div>
                <div className="gate-keystone" />
              </div>
            </div>

            {/* Step 4: Done */}
            <div className={`cb-anim ${currentStep === 3 ? "active" : ""}`}>
              <div className="anim-done">
                <svg
                  width="32"
                  height="32"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#06402B"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="20 6 9 17 4 12" className="check-path" />
                </svg>
              </div>
            </div>
          </div>

          <h1 className={`cb-title ${fading ? "cb-fading" : ""}`}>
            {step.title}
          </h1>
          <p className={`cb-desc ${fading ? "cb-fading" : ""}`}>{step.desc}</p>

          {/* Progress dots */}
          <div
            className="cb-steps"
            role="progressbar"
            aria-valuenow={currentStep + 1}
            aria-valuemin={1}
            aria-valuemax={4}
            aria-label="Connection progress"
          >
            {STEPS.map((_, i) => (
              <span key={`step-${i}`}>
                {i > 0 && (
                  <span
                    className={`cb-connector ${i <= currentStep ? "done" : ""}`}
                    aria-hidden="true"
                  />
                )}
                <span
                  className={`cb-dot ${
                    i === currentStep
                      ? "active"
                      : i < currentStep
                        ? "done"
                        : ""
                  }`}
                  aria-hidden="true"
                />
              </span>
            ))}
          </div>
          <div className="cb-sr-only" aria-live="polite">
            Step {currentStep + 1} of 4: {step.title}
          </div>

          <p className="cb-hint">
            Something wrong?{" "}
            <Link href="/support">Report an issue</Link>
          </p>
        </div>
      </div>
    </>
  );
}

const callbackStyles = `
  .callback-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    background: #faf7f2;
    font-family: var(--font-dm-sans), sans-serif;
    color: #1a1a1a;
    -webkit-font-smoothing: antialiased;
  }

  .callback-card {
    text-align: center;
    max-width: 400px;
    width: 100%;
    padding: 48px 32px;
  }

  .cb-logo {
    display: inline-flex;
    margin-bottom: 48px;
    transition: opacity .2s;
  }
  .cb-logo:hover { opacity: .8; }
  .cb-logo:focus-visible {
    outline: 2px solid #06402B;
    outline-offset: 4px;
    border-radius: 4px;
  }

  /* -- ANIMATION STAGE -- */
  .cb-stage {
    width: 120px;
    height: 120px;
    margin: 0 auto 32px;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .cb-stage::before {
    content: '';
    position: absolute;
    inset: -8px;
    border-radius: 50%;
    border: 1.5px solid rgba(6,64,43,.1);
    animation: callback-stage-pulse 2.5s ease-in-out infinite;
  }
  @keyframes callback-stage-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0; transform: scale(1.15); }
  }

  .cb-anim {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transform: scale(.85);
    transition: opacity .4s ease, transform .4s ease;
    pointer-events: none;
  }
  .cb-anim.active {
    opacity: 1;
    transform: scale(1);
    pointer-events: auto;
  }

  /* -- STEP 1: Key spinner -- */
  .anim-key {
    width: 80px;
    height: 80px;
    position: relative;
  }
  .anim-key-circle {
    width: 80px;
    height: 80px;
    border: 2.5px solid #e0dbd0;
    border-top-color: #06402B;
    border-radius: 50%;
    animation: callback-spin 1s linear infinite;
  }
  .anim-key-icon {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  @keyframes callback-spin { to { transform: rotate(360deg); } }

  /* -- STEP 2: Pod opening -- */
  .anim-pod { position: relative; width: 80px; height: 80px; }
  .pod-body {
    position: absolute;
    bottom: 8px;
    left: 50%;
    transform: translateX(-50%);
    width: 48px;
    height: 56px;
    border: 2.5px solid #06402B;
    border-radius: 8px 8px 12px 12px;
    background: rgba(6,64,43,.04);
  }
  .pod-window {
    position: absolute;
    top: 10px;
    left: 50%;
    transform: translateX(-50%);
    width: 20px;
    height: 14px;
    border: 2px solid #06402B;
    border-radius: 4px;
    background: rgba(168,230,198,.2);
  }
  .pod-lid-l, .pod-lid-r {
    position: absolute;
    top: 0;
    width: 28px;
    height: 16px;
    border: 2.5px solid #06402B;
    background: #faf7f2;
    transition: transform .6s cubic-bezier(.34,1.56,.64,1);
  }
  .pod-lid-l {
    left: 50%;
    transform: translateX(-100%) rotate(0deg);
    transform-origin: right bottom;
    border-radius: 8px 0 0 0;
  }
  .pod-lid-r {
    left: 50%;
    transform: rotate(0deg);
    transform-origin: left bottom;
    border-radius: 0 8px 0 0;
  }
  .pod-open .pod-lid-l {
    transform: translateX(-100%) rotate(-35deg);
  }
  .pod-open .pod-lid-r {
    transform: rotate(35deg);
  }
  .pod-steam {
    position: absolute;
    top: -8px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    gap: 6px;
    opacity: 0;
    transition: opacity .4s ease .3s;
  }
  .pod-open .pod-steam { opacity: 1; }
  .pod-steam-line {
    width: 2px;
    height: 12px;
    background: rgba(6,64,43,.15);
    border-radius: 1px;
    animation: callback-steam-rise 1.2s ease-in-out infinite;
  }
  .pod-steam-line:nth-child(2) { animation-delay: .3s; height: 16px; }
  .pod-steam-line:nth-child(3) { animation-delay: .6s; }
  @keyframes callback-steam-rise {
    0% { transform: translateY(0); opacity: .6; }
    100% { transform: translateY(-10px); opacity: 0; }
  }

  /* -- STEP 3: Gateway -- */
  .anim-gate { position: relative; width: 80px; height: 80px; }
  .gate-frame {
    position: absolute;
    bottom: 4px;
    left: 50%;
    transform: translateX(-50%);
    width: 56px;
    height: 64px;
    border: 2.5px solid #06402B;
    border-radius: 28px 28px 0 0;
    overflow: hidden;
    background: rgba(6,64,43,.03);
  }
  .gate-door-l, .gate-door-r {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 50%;
    background: rgba(6,64,43,.08);
    transition: transform .7s cubic-bezier(.25,.46,.45,.94);
  }
  .gate-door-l { left: 0; border-right: 1px solid rgba(6,64,43,.15); }
  .gate-door-r { right: 0; border-left: 1px solid rgba(6,64,43,.15); }
  .gate-opening .gate-door-l { transform: translateX(-100%); }
  .gate-opening .gate-door-r { transform: translateX(100%); }
  .gate-glow {
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse at center, rgba(168,230,198,.3) 0%, transparent 70%);
    opacity: 0;
    transition: opacity .5s ease .3s;
  }
  .gate-opening .gate-glow { opacity: 1; }
  .gate-keystone {
    position: absolute;
    top: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 12px;
    height: 12px;
    background: #06402B;
    border-radius: 0 0 6px 6px;
  }
  .gate-signal {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 12px;
    height: 12px;
    opacity: 0;
    transition: opacity .3s ease .5s;
  }
  .gate-opening .gate-signal { opacity: 1; }

  /* -- STEP 4: Checkmark -- */
  .anim-done {
    width: 80px;
    height: 80px;
    border-radius: 50%;
    background: rgba(6,64,43,.06);
    border: 2.5px solid #06402B;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .check-path {
    stroke-dasharray: 30;
    stroke-dashoffset: 30;
    transition: stroke-dashoffset .5s ease .15s;
  }
  .cb-anim.active .check-path {
    stroke-dashoffset: 0;
  }

  /* -- TEXT -- */
  .cb-title {
    font-family: var(--font-lora-serif), serif;
    font-size: 22px;
    font-weight: 400;
    color: #1a1a1a;
    margin-bottom: 8px;
    transition: opacity .3s ease;
  }
  .cb-desc {
    font-size: 14px;
    color: #706b63;
    line-height: 1.6;
    margin-bottom: 36px;
    transition: opacity .3s ease;
  }
  .cb-fading {
    opacity: 0;
  }

  /* -- PROGRESS DOTS -- */
  .cb-steps {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0;
    margin-bottom: 36px;
  }
  .cb-steps > span {
    display: flex;
    align-items: center;
  }
  .cb-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #e0dbd0;
    transition: background .4s ease, transform .4s ease;
    flex-shrink: 0;
    display: inline-block;
  }
  .cb-dot.active {
    background: #06402B;
    transform: scale(1.3);
  }
  .cb-dot.done {
    background: #06402B;
    transform: scale(1);
  }
  .cb-connector {
    width: 24px;
    height: 2px;
    margin: 0 6px;
    background: #e0dbd0;
    border-radius: 1px;
    transition: background .4s ease;
    flex-shrink: 0;
    display: inline-block;
  }
  .cb-connector.done { background: #06402B; }

  /* -- FOOTER -- */
  .cb-hint {
    font-size: 13px;
    color: #918a7e;
  }
  .cb-hint a {
    color: #06402B;
    font-weight: 600;
    text-decoration: none;
    transition: color .2s;
  }
  .cb-hint a:hover { color: #054d33; }
  .cb-hint a:focus-visible {
    outline: 2px solid #06402B;
    outline-offset: 2px;
    border-radius: 2px;
  }

  /* -- SCREEN READER ONLY -- */
  .cb-sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0,0,0,0);
    white-space: nowrap;
    border: 0;
  }

  /* -- REDUCED MOTION -- */
  @media (prefers-reduced-motion: reduce) {
    .callback-wrapper *, .callback-wrapper *::before, .callback-wrapper *::after {
      transition-duration: 0.01ms !important;
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
    }
    .cb-stage::before { animation: none; }
    .anim-key-circle { animation: none; border-color: #06402B; }
    .pod-steam-line { animation: none; opacity: .6; }
    .cb-anim {
      transition: none !important;
    }
  }
`;
