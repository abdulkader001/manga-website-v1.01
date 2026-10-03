import React, { useState } from "react";
import api from "../../services/api";

// Takedown / rights for one series (plan.md P1-2). "Taken down" hides the
// series from readers and deletes its stored pictures on the server; the
// name must be typed back before that is sent. Every change is audited.
const STATUSES = [
  { value: "none", label: "Online" },
  { value: "requested", label: "Takedown requested (still online)" },
  { value: "taken_down", label: "Taken down (hidden, pictures deleted)" },
];

export default function TakedownPanel({ manga, onClose, onSaved }) {
  const [status, setStatus] = useState(manga.takedown_status || "none");
  const [reason, setReason] = useState("");
  const [confirmTitle, setConfirmTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const destructive = status === "taken_down" && manga.takedown_status !== "taken_down";
  const confirmed = !destructive || confirmTitle.trim() === (manga.title || "").trim();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!confirmed) return;
    setSaving(true);
    setError("");
    try {
      const res = await api.admin.series.takedown(manga.id, { status, reason: reason.trim() || null });
      onSaved?.(res, status);
    } catch (err) {
      setError(err?.message || "The server refused the change.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/80 backdrop-blur-sm p-4">
      <form
        onSubmit={handleSubmit}
        aria-label="Takedown"
        className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-md w-full max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain p-6 space-y-4 shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
          <div>
            <h3 className="text-sm font-bold text-white">Takedown</h3>
            <p className="text-[11px] text-[#8b93a3]">{manga.title}</p>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-white" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="space-y-3 text-xs">
          <div>
            <label htmlFor="takedown-status" className="font-semibold text-gray-300 block mb-1">
              Status
            </label>
            <select
              id="takedown-status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
            >
              {STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="takedown-reason" className="font-semibold text-gray-300 block mb-1">
              Reason (kept in the audit log)
            </label>
            <textarea
              id="takedown-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={2000}
              rows={3}
              className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
            />
          </div>
          {destructive && (
            <div className="space-y-1">
              <p className="text-[11px] text-red-300">
                Readers lose access at once and the stored pages and cover are deleted from the server. To show it
                again later, set it back to Online and compress the pictures again.
              </p>
              <label htmlFor="takedown-confirm" className="font-semibold text-gray-300 block">
                Type the series name to confirm
              </label>
              <input
                id="takedown-confirm"
                value={confirmTitle}
                onChange={(e) => setConfirmTitle(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-red-400"
              />
            </div>
          )}
          {error && (
            <p role="alert" className="text-[11px] text-red-400">
              {error}
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#262a33]">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-gray-300 hover:text-white"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving || !confirmed}
            className="px-5 py-2 rounded-xl bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white font-bold text-xs transition"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
