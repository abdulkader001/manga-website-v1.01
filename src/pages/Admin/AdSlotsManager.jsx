import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useMemo, useState } from "react";

import AuthGuard from "../../components/AuthGuard";
import api from "../../services/api";

const SLOT_TYPES = [
  { value: "image", label: "Image banner" },
  { value: "html", label: "HTML creative" },
  { value: "script", label: "External script" },
];

const BLANK_FORM = {
  name: "",
  slot_key: "",
  placement: "",
  position: 0,
  type: "image",
  image_url: "",
  link_url: "",
  alt_text: "",
  html_code: "",
  height_px: "",
  max_width_px: "",
  enabled: true,
};

const INPUT =
  "rounded border border-[var(--color-border)] bg-[var(--bg-secondary)] p-2 text-sm";

function toForm(slot) {
  return {
    ...BLANK_FORM,
    ...slot,
    placement: slot.placement || "",
    position: slot.position ?? 0,
    image_url: slot.image_url || "",
    link_url: slot.link_url || "",
    alt_text: slot.alt_text || "",
    html_code: slot.html_code || "",
    height_px: slot.height_px ?? "",
    max_width_px: slot.max_width_px ?? "",
    enabled: slot.enabled ?? true,
  };
}

/** Strip empty strings so the API stores NULL rather than "". */
function toPayload(form) {
  const payload = {
    name: form.name.trim(),
    slot_key: form.slot_key.trim(),
    placement: form.placement || null,
    position: Number(form.position) || 0,
    type: form.type,
    enabled: Boolean(form.enabled),
    image_url: form.image_url.trim() || null,
    link_url: form.link_url.trim() || null,
    alt_text: form.alt_text.trim() || null,
    html_code: form.html_code.trim() || null,
  };
  payload.height_px = form.height_px === "" ? null : Number(form.height_px);
  payload.max_width_px = form.max_width_px === "" ? null : Number(form.max_width_px);
  return payload;
}

function SlotForm({ form, setForm, placements, onSubmit, onCancel, saving, isEdit }) {
  const set = (patch) => setForm((prev) => ({ ...prev, ...patch }));

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="grid gap-4 rounded border border-[var(--color-border)] bg-[var(--bg-primary)] p-4"
    >
      <h2 className="text-lg font-semibold">{isEdit ? "Edit ad slot" : "New ad slot"}</h2>

      <div className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-sm">
          <span>Name *</span>
          <input
            required
            className={INPUT}
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
            placeholder="Homepage leaderboard"
          />
        </label>
        <label className="grid gap-1 text-sm">
          <span>Slot key * (unique)</span>
          <input
            required
            className={INPUT}
            value={form.slot_key}
            onChange={(e) => set({ slot_key: e.target.value })}
            placeholder="homepage_leaderboard"
          />
        </label>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <label className="grid gap-1 text-sm">
          <span>Placement</span>
          <select
            className={INPUT}
            value={form.placement}
            onChange={(e) => set({ placement: e.target.value })}
          >
            <option value="">— Not placed (hidden) —</option>
            {placements.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span>Order in placement</span>
          <input
            type="number"
            className={INPUT}
            value={form.position}
            onChange={(e) => set({ position: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          <span>Type</span>
          <select
            className={INPUT}
            value={form.type}
            onChange={(e) => set({ type: e.target.value })}
          >
            {SLOT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-sm">
          <span>Height (px)</span>
          <input
            type="number"
            min="0"
            className={INPUT}
            value={form.height_px}
            onChange={(e) => set({ height_px: e.target.value })}
            placeholder="Leave blank for automatic"
          />
        </label>
        <label className="grid gap-1 text-sm">
          <span>Max width (px)</span>
          <input
            type="number"
            min="0"
            className={INPUT}
            value={form.max_width_px}
            onChange={(e) => set({ max_width_px: e.target.value })}
            placeholder="Leave blank for full width"
          />
        </label>
      </div>

      {form.type === "html" ? (
        <label className="grid gap-1 text-sm">
          <span>HTML creative</span>
          <textarea
            rows={5}
            className={`${INPUT} font-mono`}
            value={form.html_code}
            onChange={(e) => set({ html_code: e.target.value })}
            placeholder="<div>…</div>"
          />
          <span className="text-xs text-[var(--text-secondary)]">
            Scripts and event handlers are stripped server-side before storage.
          </span>
        </label>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-1 text-sm">
            <span>{form.type === "script" ? "Script URL" : "Image URL"}</span>
            <input
              className={INPUT}
              value={form.type === "script" ? form.link_url : form.image_url}
              onChange={(e) =>
                set(
                  form.type === "script"
                    ? { link_url: e.target.value }
                    : { image_url: e.target.value }
                )
              }
              placeholder="https://…"
            />
          </label>
          {form.type === "image" && (
            <label className="grid gap-1 text-sm">
              <span>Click-through URL</span>
              <input
                className={INPUT}
                value={form.link_url}
                onChange={(e) => set({ link_url: e.target.value })}
                placeholder="https://advertiser.example"
              />
            </label>
          )}
        </div>
      )}

      {form.type === "image" && (
        <label className="grid gap-1 text-sm">
          <span>Alt text</span>
          <input
            className={INPUT}
            value={form.alt_text}
            onChange={(e) => set({ alt_text: e.target.value })}
            placeholder="Advertisement"
          />
        </label>
      )}

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(e) => set({ enabled: e.target.checked })}
        />
        Enabled (visible to readers)
      </label>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {saving ? "Saving…" : isEdit ? "Save changes" : "Create slot"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-[var(--color-border)] px-4 py-2 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function AdSlotsManager() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState("");

  const { data: slots = [], isLoading } = useQuery({
    queryKey: ["adminAdSlots"],
    queryFn: () => api.adSlots.list(),
  });

  const { data: placements = [] } = useQuery({
    queryKey: ["adPlacements"],
    queryFn: () => api.ads.placements(),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["adminAdSlots"] });
    // The reader-facing placements read a different cache entry.
    queryClient.invalidateQueries({ queryKey: ["adSlots", "public"] });
  };

  const saveMutation = useMutation({
    mutationFn: ({ id, payload }) =>
      id ? api.adSlots.update(id, payload) : api.adSlots.create(payload),
    onSuccess: () => {
      refresh();
      setForm(null);
      setEditingId(null);
      setError("");
    },
    onError: (err) => setError(err?.message || "Failed to save the ad slot."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => api.adSlots.remove(id),
    onSuccess: refresh,
    onError: (err) => setError(err?.message || "Failed to delete the ad slot."),
  });

  const placementList = useMemo(() => {
    if (Array.isArray(placements)) return placements;
    if (placements && typeof placements === "object") {
      return Object.entries(placements).map(([key, val]) => ({
        key,
        label: (val && typeof val === "object" && val.label) || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      }));
    }
    return [
      { key: "global_top", label: "Global Top" },
      { key: "global_bottom", label: "Global Bottom" },
      { key: "homepage_top", label: "Homepage Top" },
      { key: "browse_top", label: "Browse Top" },
      { key: "reader_sidebar", label: "Reader Sidebar" },
    ];
  }, [placements]);

  const placementLabels = useMemo(() => {
    const map = {};
    placementList.forEach((p) => {
      map[p.key] = p.label;
    });
    return map;
  }, [placementList]);

  const grouped = useMemo(() => {
    const buckets = new Map();
    slots.forEach((slot) => {
      const key = slot.placement || "";
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(slot);
    });
    buckets.forEach((list) => list.sort((a, b) => (a.position ?? 0) - (b.position ?? 0)));
    return buckets;
  }, [slots]);

  const startCreate = () => {
    setEditingId(null);
    setForm({ ...BLANK_FORM });
  };

  const startEdit = (slot) => {
    setEditingId(slot.id);
    setForm(toForm(slot));
  };

  return (
    <AuthGuard requireAdmin>
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-bold">Ad Slots</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Create ad creatives and assign each one to a placement. Site-wide
            placements appear on every page — including every chapter — with no
            further setup, so you never have to place an ad page by page.
          </p>
        </header>

        {error && (
          <div className="rounded border border-red-400 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {form ? (
          <SlotForm
            form={form}
            setForm={setForm}
            placements={placementList}
            saving={saveMutation.isPending}
            isEdit={Boolean(editingId)}
            onCancel={() => {
              setForm(null);
              setEditingId(null);
            }}
            onSubmit={() =>
              saveMutation.mutate({ id: editingId, payload: toPayload(form) })
            }
          />
        ) : (
          <button
            type="button"
            onClick={startCreate}
            className="rounded bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-white"
          >
            + New ad slot
          </button>
        )}

        {isLoading ? (
          <p>Loading ad slots…</p>
        ) : slots.length === 0 ? (
          <p className="text-sm text-[var(--text-secondary)]">
            No ad slots yet. Create one above to start showing ads.
          </p>
        ) : (
          <div className="space-y-6">
            {[...grouped.entries()].map(([placement, list]) => (
              <section key={placement || "unplaced"} className="space-y-2">
                <h2 className="text-sm font-semibold">
                  {placement
                    ? placementLabels[placement] || placement
                    : "Not placed (hidden from readers)"}
                </h2>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-sm">
                    <thead className="text-[var(--text-secondary)]">
                      <tr>
                        <th className="p-2">Name</th>
                        <th className="p-2">Type</th>
                        <th className="p-2">Size</th>
                        <th className="p-2">Order</th>
                        <th className="p-2">Status</th>
                        <th className="p-2">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((slot) => (
                        <tr key={slot.id} className="border-t border-[var(--color-border)]">
                          <td className="p-2">
                            <div>{slot.name}</div>
                            <div className="text-xs text-[var(--text-secondary)]">
                              {slot.slot_key}
                            </div>
                          </td>
                          <td className="p-2">{slot.type}</td>
                          <td className="p-2">
                            {slot.height_px ? `${slot.height_px}px tall` : "auto"}
                            {slot.max_width_px ? ` · max ${slot.max_width_px}px` : ""}
                          </td>
                          <td className="p-2">{slot.position ?? 0}</td>
                          <td className="p-2">
                            {slot.enabled ? (
                              <span className="text-green-600">Enabled</span>
                            ) : (
                              <span className="text-[var(--text-secondary)]">Disabled</span>
                            )}
                          </td>
                          <td className="p-2">
                            <div className="flex gap-2">
                              <button
                                type="button"
                                onClick={() => startEdit(slot)}
                                className="rounded border border-[var(--color-border)] px-2 py-1 text-xs"
                              >
                                Edit
                              </button>
                              <button
                                type="button"
                                onClick={() =>
                                  saveMutation.mutate({
                                    id: slot.id,
                                    payload: { enabled: !slot.enabled },
                                  })
                                }
                                className="rounded border border-[var(--color-border)] px-2 py-1 text-xs"
                              >
                                {slot.enabled ? "Disable" : "Enable"}
                              </button>
                              <button
                                type="button"
                                onClick={() => deleteMutation.mutate(slot.id)}
                                className="rounded border border-red-500/40 bg-red-500/10 px-2 py-1 text-xs text-red-400 hover:bg-red-500/20 transition"
                              >
                                Delete
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </AuthGuard>
  );
}
