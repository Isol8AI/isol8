"use client";

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
 * `unpublish <slug>` before the action fires. We rethrow backend errors so the
 * dialog's own busy / error state handles the failure — keeping this island
 * state-free and cheap to re-render per row.
 */
export function CatalogRowActions({
  slug,
  name,
  onOpenVersions,
}: CatalogRowActionsProps) {
  async function handleUnpublish() {
    const result = await unpublishSlug(slug);
    if (!result.ok) {
      throw new Error(result.error ?? `unpublish_failed_${result.status}`);
    }
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
    </div>
  );
}
