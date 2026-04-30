"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { grantTakedown } from "@/app/admin/_actions/marketplace";
import { ConfirmActionDialog } from "@/components/admin/ConfirmActionDialog";
import { Button } from "@/components/ui/button";

export interface TakedownActionsProps {
  listingId: string;
  takedownId: string;
}

/**
 * Grant-takedown button for a single pending takedown row.
 *
 * Wraps `grantTakedown` in the shared `ConfirmActionDialog` (CEO S5
 * typed-confirmation convention — operator types `takedown <listing_id>`).
 * Granting a takedown cascades: revokes ALL license keys for the listing,
 * queues refunds for purchases in the last 30 days, hides the listing from
 * browse, and emails affected buyers — so the typed-confirmation gate is the
 * required friction. On success the page calls `router.refresh()` and the
 * just-actioned takedown drops out of the queue. Errors render inline.
 */
export function TakedownActions({
  listingId,
  takedownId,
}: TakedownActionsProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function handleGrant() {
    setError(null);
    const result = await grantTakedown(listingId, takedownId);
    if (!result.ok) {
      setError(result.error ?? `grant_failed_${result.status}`);
      return;
    }
    router.refresh();
  }

  return (
    <div className="flex shrink-0 flex-col items-end gap-2">
      <ConfirmActionDialog
        confirmText={`takedown ${listingId}`}
        actionLabel={`Grant takedown for ${listingId}`}
        destructive
        onConfirm={handleGrant}
      >
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-red-700/40 bg-red-700/20 text-red-300 hover:bg-red-700/30"
        >
          Grant takedown
        </Button>
      </ConfirmActionDialog>
      {error && (
        <span className="text-xs text-red-400" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
