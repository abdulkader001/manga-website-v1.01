import { apiFetch } from "../services/api";

// Every ad box on a page used to fetch GET /ad-slots on its own: six identical
// calls on the homepage, nine in the reader. They now share one request, kept
// for a minute so moving between pages doesn't ask again.
const TTL_MS = 60 * 1000;

let cached = null; // { at, promise }

export function loadAdSlots() {
  const now = Date.now();
  if (cached && now - cached.at < TTL_MS) return cached.promise;
  const promise = apiFetch("/api/v1/ad-slots")
    .then((res) => (res.ok ? res.json() : []))
    .then((slots) => (Array.isArray(slots) ? slots : []))
    .catch(() => {
      // A failed load is not kept: the next ad box asks again.
      if (cached && cached.promise === promise) cached = null;
      return [];
    });
  cached = { at: now, promise };
  return promise;
}

export function findAdSlot(slots, key) {
  return (
    slots.find((s) => (s.placement === key || s.slot_key === key) && s.enabled !== false) ||
    null
  );
}

export function resetAdSlotsCache() {
  cached = null;
}
