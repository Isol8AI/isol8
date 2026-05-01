"use client";

import { useState } from "react";
import { Loader2, MessageSquareText, MonitorSmartphone } from "lucide-react";
import { usePostHog } from "posthog-js/react";

import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";

interface ChannelOptInStepProps {
  /** Called after the user picks "skip" — go straight into chat. */
  onSkip: () => void;
  /**
   * Called after POST /container/channels {enable: true} succeeds. The
   * parent should switch to a "container restarting" state and poll
   * /container/status until the new task replaces the old one (~6 min).
   */
  onEnabled: () => void;
}

export function ChannelOptInStep({ onSkip, onEnabled }: ChannelOptInStepProps) {
  const api = useApi();
  const posthog = usePostHog();
  const [submitting, setSubmitting] = useState<"yes" | "no" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleEnable = async () => {
    setSubmitting("yes");
    setError(null);
    posthog?.capture("channel_optin_chose", { choice: "yes" });
    try {
      await api.post("/container/channels", { enable: true });
      onEnabled();
    } catch (err) {
      console.error("Failed to enable channels:", err);
      setError("Couldn't enable channels — please try again.");
      setSubmitting(null);
    }
  };

  const handleSkip = () => {
    setSubmitting("no");
    posthog?.capture("channel_optin_chose", { choice: "no" });
    onSkip();
  };

  return (
    <div className="flex-1 flex items-center justify-center p-6 bg-[#faf7f2]">
      <div className="w-full max-w-md text-center">
        <h2 className="text-2xl font-medium text-[#1a1a1a] mb-2 font-serif">
          Connect a messaging app?
        </h2>
        <p className="text-sm text-[#6e695d] leading-relaxed mb-8">
          Talk to your agent from Telegram, Discord, or Slack — handy for
          asking on the go. Skipping is fine; you can connect one later.
        </p>

        <div className="flex flex-col gap-3 mb-6">
          <button
            onClick={handleEnable}
            disabled={submitting !== null}
            className="flex items-start gap-4 p-4 rounded-xl border border-[#06402B] bg-white hover:bg-[#f7f4ee] transition-colors text-left disabled:opacity-60"
          >
            <MessageSquareText className="h-6 w-6 text-[#06402B] flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="font-medium text-[#1a1a1a]">
                Yes, set one up now
              </div>
              <div className="text-xs text-[#8a8578] mt-1 leading-snug">
                Adds about 6 minutes to setup while channels initialize.
                You&rsquo;ll connect a bot right after.
              </div>
            </div>
            {submitting === "yes" && (
              <Loader2 className="h-5 w-5 animate-spin text-[#06402B]" />
            )}
          </button>

          <button
            onClick={handleSkip}
            disabled={submitting !== null}
            className="flex items-start gap-4 p-4 rounded-xl border border-[#e0dbd0] bg-white hover:bg-[#f7f4ee] transition-colors text-left disabled:opacity-60"
          >
            <MonitorSmartphone className="h-6 w-6 text-[#6e695d] flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="font-medium text-[#1a1a1a]">
                Not now, just chat in browser
              </div>
              <div className="text-xs text-[#8a8578] mt-1 leading-snug">
                Fast path. Connect a messaging app later from settings.
              </div>
            </div>
          </button>
        </div>

        {error && (
          <p className="text-sm text-[#dc2626] mb-3">{error}</p>
        )}

        <Button
          variant="ghost"
          size="sm"
          onClick={handleSkip}
          disabled={submitting !== null}
          className="text-xs text-[#8a8578]"
        >
          Skip for now
        </Button>
      </div>
    </div>
  );
}
