import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({
  history: { read: vi.fn(), sync: vi.fn() },
}));
const auth = vi.hoisted(() => ({ value: { user: null } }));
vi.mock("../services/api", () => ({ default: api }));
vi.mock("../hooks/useAuth", () => ({ default: () => auth.value }));

import HistorySync from "./HistorySync";
import {
  clearHistory,
  readSet,
  recordRead,
  removeHistory,
  resetHistory,
} from "../utils/library";

const lib = () => JSON.parse(localStorage.getItem("mw_library_v1") || "{}");
const reads = (mangaId) => [...readSet(lib(), mangaId)].sort((a, b) => a - b);
const signIn = (id = 42) => {
  auth.value = { user: { id } };
};
const entry = (manga, chapter, number, at = "2026-01-01T10:00:00Z") => ({
  manga_id: manga,
  chapter_id: chapter,
  chapter_number: number,
  read_at: at,
});

describe("HistorySync", () => {
  beforeEach(() => {
    api.history.read.mockReset().mockResolvedValue({});
    api.history.sync.mockReset().mockResolvedValue({ entries: [] });
    auth.value = { user: null };
    resetHistory(); // the library keeps an in-memory copy; start from empty
  });

  it("keeps a guest's reading in the browser and sends nothing", () => {
    render(<HistorySync />);
    recordRead(5, 11, 1);
    expect(reads(5)).toEqual([11]);
    expect(lib().readPending).toEqual({ 11: expect.any(String) });
    expect(api.history.read).not.toHaveBeenCalled();
    expect(api.history.sync).not.toHaveBeenCalled();
  });

  it("on a browser's first sign-in sends what it has, then shows the account's list", async () => {
    recordRead(5, 11, 1); // read as a guest
    api.history.sync.mockResolvedValue({
      entries: [entry(5, 12, 2, "2026-02-01T10:00:00Z"), entry(5, 11, 1)],
    });
    signIn();
    render(<HistorySync />);

    await waitFor(() => expect(reads(5)).toEqual([11, 12]));
    const sent = api.history.sync.mock.calls[0][0];
    expect(sent.entries.map((e) => e.chapter_id)).toEqual([11]);
    expect(lib().readPending).toEqual({});
    expect(lib().last["5"]).toMatchObject({ chapterId: 12, number: 2 });
    expect(localStorage.getItem("mw_history_synced_user")).toBe("42");
  });

  it("a new phone gets the dimmed chapters and where the reader stopped", async () => {
    api.history.sync.mockResolvedValue({
      entries: [entry(8, 90, 3, "2026-03-01T10:00:00Z"), entry(8, 80, 2), entry(9, 70, 1)],
    });
    signIn();
    render(<HistorySync />);

    await waitFor(() => expect(reads(8)).toEqual([80, 90]));
    expect(reads(9)).toEqual([70]);
    expect(lib().last["8"]).toMatchObject({ chapterId: 90, number: 3 });
    expect(api.history.sync.mock.calls[0][0].entries).toEqual([]); // nothing to send
  });

  it("sends each chapter straight to the account while signed in, and queues it if that fails", async () => {
    localStorage.setItem("mw_history_synced_user", "42");
    signIn();
    render(<HistorySync />);
    await waitFor(() => expect(api.history.sync).toHaveBeenCalled());

    recordRead(5, 11, 1);
    expect(api.history.read).toHaveBeenCalledWith(11, expect.any(String));
    expect(lib().readPending).toEqual({});

    api.history.read.mockRejectedValueOnce(new Error("offline"));
    recordRead(5, 12, 2);
    await waitFor(() => expect(lib().readPending).toEqual({ 12: expect.any(String) }));
    expect(reads(5)).toEqual([11, 12]);
  });

  it("clearing while signed in reaches the account", async () => {
    localStorage.setItem("mw_history_synced_user", "42");
    signIn();
    render(<HistorySync />);
    await waitFor(() => expect(api.history.sync).toHaveBeenCalled());
    api.history.sync.mockClear();

    recordRead(5, 11, 1);
    removeHistory(5);
    expect(api.history.sync).toHaveBeenLastCalledWith({ clear_manga: [5], return_entries: false });
    clearHistory();
    expect(api.history.sync).toHaveBeenLastCalledWith({ clear_all: true, return_entries: false });
    expect(reads(5)).toEqual([]);
  });

  it("a clear made signed out is sent first, so the account's list does not bring it back", async () => {
    localStorage.setItem("mw_history_synced_user", "42");
    recordRead(5, 11, 1);
    recordRead(6, 21, 1);
    removeHistory(5); // signed out
    expect(lib().readPending).toEqual({ 21: expect.any(String) }); // 11 is no longer queued
    expect(lib().clearPending).toEqual({ all: false, manga: { 5: true } });

    api.history.sync.mockResolvedValue({ entries: [entry(6, 21, 1)] });
    signIn();
    render(<HistorySync />);

    await waitFor(() => expect(reads(6)).toEqual([21]));
    const sent = api.history.sync.mock.calls[0][0];
    expect(sent.clear_manga).toEqual([5]);
    expect(sent.entries.map((e) => e.chapter_id)).toEqual([21]);
    expect(reads(5)).toEqual([]);
    expect(lib().clearPending).toEqual({ all: false, manga: {} });
  });

  it("keeps this device's reading when the account can't be reached", async () => {
    localStorage.setItem("mw_history_synced_user", "42");
    recordRead(5, 11, 1);
    api.history.sync.mockRejectedValue(new Error("offline"));
    signIn();
    render(<HistorySync />);

    await waitFor(() => expect(api.history.sync).toHaveBeenCalled());
    await Promise.resolve();
    expect(reads(5)).toEqual([11]);
    expect(lib().readPending).toEqual({ 11: expect.any(String) });
  });

  it("a different account on the same browser starts from its own list", async () => {
    localStorage.setItem("mw_history_synced_user", "7");
    recordRead(5, 11, 1); // the previous reader's
    api.history.sync.mockResolvedValue({ entries: [entry(9, 70, 1)] });
    signIn(42);
    render(<HistorySync />);

    await waitFor(() => expect(reads(9)).toEqual([70]));
    expect(reads(5)).toEqual([]);
    expect(api.history.sync.mock.calls[0][0].entries).toEqual([]);
    expect(localStorage.getItem("mw_history_synced_user")).toBe("42");
  });

  it("sends a big library in pieces and asks for the list only at the end", async () => {
    for (let c = 1; c <= 2001; c += 1) recordRead(5, c, c);
    signIn();
    render(<HistorySync />);

    await waitFor(() => expect(api.history.sync).toHaveBeenCalledTimes(2));
    const [first, second] = api.history.sync.mock.calls.map((call) => call[0]);
    expect(first.entries).toHaveLength(2000);
    expect(first.return_entries).toBe(false);
    expect(second.entries).toHaveLength(1);
    expect(second.return_entries).toBe(true);
  });

  it("keeps a chapter opened while the first sync was still running", async () => {
    let finish;
    api.history.sync.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    signIn();
    render(<HistorySync />);
    await waitFor(() => expect(api.history.sync).toHaveBeenCalled());

    recordRead(5, 99, 9); // opened now; the account's answer doesn't know it yet
    finish({ entries: [entry(5, 11, 1)] });

    await waitFor(() => expect(reads(5)).toEqual([11, 99]));
    expect(lib().last["5"]).toMatchObject({ chapterId: 99, number: 9 });
  });
});
