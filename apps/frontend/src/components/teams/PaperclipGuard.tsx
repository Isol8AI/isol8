"use client";

import { Loader2, Users, ArrowRight } from "lucide-react";
import Link from "next/link";
import { usePaperclipStatus, usePaperclipEnable } from "@/hooks/usePaperclip";
import { useBilling } from "@/hooks/useBilling";
import { Button } from "@/components/ui/button";
import { useState } from "react";

interface PaperclipGuardProps {
  children: React.ReactNode;
}

export function PaperclipGuard({ children }: PaperclipGuardProps) {
  const { status, isLoading } = usePaperclipStatus();
  const { planTier } = useBilling();
  const { enable } = usePaperclipEnable();
  const [isEnabling, setIsEnabling] = useState(false);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f5f3ee]">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  const isEligible = planTier === "pro" || planTier === "enterprise";

  if (!isEligible) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f5f3ee]">
        <div className="max-w-md text-center space-y-4 p-8">
          <div className="flex justify-center">
            <div className="rounded-full bg-white border border-[#e5e0d5] p-4">
              <Users className="h-8 w-8 text-[#8a8578]" />
            </div>
          </div>
          <h1 className="text-lg font-semibold text-[#1a1a1a]">Teams</h1>
          <p className="text-sm text-[#8a8578]">
            Teams is available on the Pro and Enterprise plans. Upgrade to manage AI agent teams with Paperclip.
          </p>
          <div className="flex flex-col gap-2 items-center">
            <Link href="/chat">
              <Button variant="outline" size="sm">
                Back to Chat
              </Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (!status.enabled) {
    const handleEnable = async () => {
      setIsEnabling(true);
      try {
        await enable();
      } finally {
        setIsEnabling(false);
      }
    };

    return (
      <div className="flex h-screen items-center justify-center bg-[#f5f3ee]">
        <div className="max-w-md text-center space-y-4 p-8">
          <div className="flex justify-center">
            <div className="rounded-full bg-white border border-[#e5e0d5] p-4">
              <Users className="h-8 w-8 text-[#8a8578]" />
            </div>
          </div>
          <h1 className="text-lg font-semibold text-[#1a1a1a]">Enable Teams</h1>
          <p className="text-sm text-[#8a8578]">
            Teams lets you manage AI agent teams, track issues, run routines, and more — powered by Paperclip.
          </p>
          <div className="flex flex-col gap-2 items-center">
            {status.can_toggle ? (
              <Button onClick={handleEnable} disabled={isEnabling} size="sm">
                {isEnabling ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <ArrowRight className="h-4 w-4 mr-2" />
                )}
                Enable Teams
              </Button>
            ) : (
              <p className="text-xs text-[#b0a99a]">
                Ask an organization admin to enable Teams.
              </p>
            )}
            <Link href="/chat">
              <Button variant="ghost" size="sm" className="text-[#8a8578]">
                Back to Chat
              </Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
