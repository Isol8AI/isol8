"use client";

import { useState, useEffect } from "react";
import { useTeamsApi } from "@/hooks/useTeamsApi";

interface CompanySettings {
  display_name?: string;
  description?: string;
}

export function SettingsPanel() {
  const { read, patch } = useTeamsApi();
  const { data, mutate } = read<CompanySettings>("/settings");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (data) {
      setName(data.display_name ?? "");
      setDesc(data.description ?? "");
    }
  }, [data]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      // SECURITY: body contains ONLY {display_name, description}, matching
      // PatchCompanySettingsBody (Task 3, extra="forbid"). Adapter, plugin,
      // and instance settings are operator-controlled — defense in depth.
      await patch("/settings", { display_name: name, description: desc });
      mutate();
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-8 max-w-2xl space-y-4">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <label className="block">
        <span className="text-sm">Display name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full border rounded px-3 py-2 mt-1"
        />
      </label>
      <label className="block">
        <span className="text-sm">Description</span>
        <textarea
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          className="w-full border rounded px-3 py-2 mt-1"
          rows={4}
        />
      </label>
      {err && <div className="text-red-600 text-sm">{err}</div>}
      <button
        onClick={save}
        disabled={saving}
        className="px-4 py-2 bg-zinc-900 text-white rounded text-sm"
      >
        {saving ? "Saving…" : "Save"}
      </button>
      <p className="text-xs text-zinc-500 pt-4 border-t">
        Adapter, plugin, and instance settings are operator-controlled and not
        editable here.
      </p>
    </div>
  );
}
