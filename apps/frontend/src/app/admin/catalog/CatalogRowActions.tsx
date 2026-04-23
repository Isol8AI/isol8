"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ConfirmActionDialog } from "@/components/admin/ConfirmActionDialog";
import { Button } from "@/components/ui/button";
import { unpublishSlug } from "@/app/admin/_actions/catalog";

export interface CatalogRowActionsProps {
  slug: string;
  name: string;
  onOpenVersions: (slug: string) => void;
}

/**
 * Per-row action cluster for the admin catalog table. Pairs a
 * typed-confirmation Unpublish dialog with a sibling "View versions" button
 * that hoists selection state up to the parent page (the versions panel lives
 * alongside the table so a single instance re-renders as the slug changes).
 *
 * The Unpublish flow wraps `unpublishSlug` in `ConfirmActionDialog` with the
 * CEO S5 convention: the operator must type the literal phrase
 * `unpublish <slug>` before the action fires. On success we call
 * `router.refresh()` so the parent Server Component re-runs and the retired
 * slug moves out of the Live table immediately — without this, the row
 * lingers until a manual reload and a second click hits a 404. Failures are
 * captured into local state and surfaced inline; the dialog component itself
 * has no error slot, so throwing would end up as an unhandled rejection with
 * no operator-visible feedback.
 */
export function CatalogRowActions({
  slug,
  name,
  onOpenVersions,
}: CatalogRowActionsProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function handleUnpublish() {
    setError(null);
    const result = await unpublishSlug(slug);
    if (!result.ok) {
      setError(result.error ?? `unpublish_failed_${result.status}`);
      return;
    }
    router.refresh();
  }

  return (
    <div className="flex items-center gap-2">
      <ConfirmActionDialog
        confirmText={`unpublish ${slug}`}
        actionLabel={`Unpublish ${name}`}
        destructive
        onConfirm={handleUnpublish}
      >
        <Button type="button" variant="outline" size="sm">
          Unpublish
        </Button>
      </ConfirmActionDialog>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onOpenVersions(slug)}
      >
        View versions
      </Button>
      {error && (
        <span className="text-xs text-red-400 ml-2" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
