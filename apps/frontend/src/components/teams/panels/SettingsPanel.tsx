"use client";

import { Loader2, AlertTriangle } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { usePaperclipApi, usePaperclipEnable, usePaperclipStatus } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";

interface Company {
  id?: string;
  name?: string;
  issue_prefix?: string;
  budget?: number;
}

export function SettingsPanel() {
  const { data, isLoading } = usePaperclipApi<Company[]>("companies");
  const { disable } = usePaperclipEnable();
  const { status } = usePaperclipStatus();
  const router = useRouter();
  const [isDisabling, setIsDisabling] = useState(false);
  const [confirmDisable, setConfirmDisable] = useState(false);

  const company = Array.isArray(data) ? data[0] : undefined;

  const handleDisable = async () => {
    if (!confirmDisable) {
      setConfirmDisable(true);
      return;
    }
    setIsDisabling(true);
    try {
      await disable();
      router.push("/chat");
    } finally {
      setIsDisabling(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Settings</h1>
        <p className="text-sm text-[#8a8578]">Teams configuration</p>
      </div>

      {company && (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4 space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[#8a8578]">Company</h2>
          <Row label="Name" value={company.name ?? "—"} />
          <Row label="Issue Prefix" value={company.issue_prefix ?? "—"} />
          <Row
            label="Budget"
            value={company.budget !== undefined ? `$${company.budget.toFixed(2)}` : "—"}
          />
        </div>
      )}

      {/* Danger Zone — only org admins (or personal accounts) can disable */}
      {status.can_toggle && (
        <div className="rounded-lg border border-red-200 bg-red-50/50 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-500" />
            <h2 className="text-sm font-semibold text-red-700">Danger Zone</h2>
          </div>
          <p className="text-sm text-red-600">
            Disabling Teams will turn off the Paperclip integration. Your data will be preserved but the /teams page will no longer be accessible.
          </p>
          {confirmDisable && (
            <p className="text-xs font-medium text-red-700">
              Are you sure? Click again to confirm.
            </p>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleDisable}
            disabled={isDisabling}
            className="text-red-600 border-red-300 hover:bg-red-100"
          >
            {isDisabling && <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" />}
            {confirmDisable ? "Confirm Disable" : "Disable Teams"}
          </Button>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-[#8a8578]">{label}</span>
      <span className="font-medium text-[#1a1a1a]">{value}</span>
    </div>
  );
}
