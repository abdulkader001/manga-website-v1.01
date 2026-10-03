import { describe, it, expect, vi, beforeEach } from "vitest";

const apiFetch = vi.fn();
vi.mock("../services/api", () => ({ apiFetch: (...a) => apiFetch(...a) }));

import { findAdSlot, loadAdSlots, resetAdSlotsCache } from "./adSlots";

const slots = [
  { placement: "home_top", enabled: true, id: 1 },
  { slot_key: "reader_bottom", enabled: false, id: 2 },
];

describe("shared ad-slot loading", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    resetAdSlotsCache();
  });

  it("asks the server once for every ad box on the page", async () => {
    apiFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(slots) });
    const results = await Promise.all([loadAdSlots(), loadAdSlots(), loadAdSlots()]);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(results[2]).toEqual(slots);
  });

  it("asks again after a failure", async () => {
    apiFetch.mockRejectedValueOnce(new Error("offline"));
    expect(await loadAdSlots()).toEqual([]);
    apiFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(slots) });
    expect(await loadAdSlots()).toEqual(slots);
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("finds an enabled slot by placement or key", () => {
    expect(findAdSlot(slots, "home_top").id).toBe(1);
    expect(findAdSlot(slots, "reader_bottom")).toBeNull();
    expect(findAdSlot(slots, "missing")).toBeNull();
  });
});
