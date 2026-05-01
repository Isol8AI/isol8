"use client";

import { useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useApi } from "@/lib/api";

interface RestartForChannelsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Called after the user confirms and POST /container/channels succeeds.
   * Parents typically close their own UI and let the user re-trigger the
   * channel action once the container is back up.
   */
  onConfirmed: () => void;
}

/**
 * Single source of truth for the "channels are off — flipping them on
 * requires a ~6 min container restart" confirmation. The two surfaces
 * that create or link bots (AgentChannelsSection + MyChannelsSection)
 * mount this and trigger it before opening their wizard when
 * `container.channels_at_boot === false`.
 */
export function RestartForChannelsDialog({
  open,
  onOpenChange,
  onConfirmed,
}: RestartForChannelsDialogProps) {
  const api = useApi();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/container/channels", { enable: true });
      onConfirmed();
      onOpenChange(false);
    } catch (err) {
      console.error("Failed to enable channels:", err);
      setError("Couldn't enable channels — please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Restart container to enable channels?</AlertDialogTitle>
          <AlertDialogDescription>
            Messaging channels are turned off on your container, so they
            can&rsquo;t connect right now. Enabling them re-deploys your
            container, which takes about 6 minutes. Once it&rsquo;s back,
            you can finish setting up your bot.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && (
          <p className="text-sm text-[#dc2626]">{error}</p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting}>Not now</AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirm} disabled={submitting}>
            {submitting ? "Enabling…" : "Restart and enable"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
