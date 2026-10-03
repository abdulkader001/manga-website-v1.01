import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({
  bookmarks: { importBackup: vi.fn(), remove: vi.fn(), add: vi.fn(), list: vi.fn() },
}));
const auth = vi.hoisted(() => ({ value: { user: null } }));
vi.mock("../services/api", () => ({ default: api }));
vi.mock("../hooks/useAuth", () => ({ default: () => auth.value }));

import BookmarkSync from "./BookmarkSync";
import {
  bookmarkIds,
  clearPendingBookmarks,
  pendingBookmarkChanges,
  setBookmarks,
  toggleBookmark,
} from "../utils/library";

const lib = () => JSON.parse(localStorage.getItem("mw_library_v1") || "{}");

describe("BookmarkSync", () => {
  beforeEach(() => {
    Object.values(api.bookmarks).forEach((fn) => fn.mockReset());
    api.bookmarks.add.mockResolvedValue({});
    api.bookmarks.remove.mockResolvedValue({});
    api.bookmarks.importBackup.mockResolvedValue({ imported: 1 });
    auth.value = { user: null };
    // The library keeps an in-memory copy; start every test from empty.
    setBookmarks([]);
    clearPendingBookmarks();
  });

  it("keeps a guest's bookmarks in the browser and sends nothing", () => {
    render(<BookmarkSync />);
    toggleBookmark(7);
    expect(bookmarkIds()).toEqual(["7"]);
    expect(pendingBookmarkChanges()).toEqual({ 7: "add" });
    expect(api.bookmarks.add).not.toHaveBeenCalled();
    expect(api.bookmarks.importBackup).not.toHaveBeenCalled();
  });

  it("on first sign-in uploads this browser's bookmarks, then shows the account's list", async () => {
    toggleBookmark(7); // made as a guest
    api.bookmarks.list.mockResolvedValue([{ manga_id: 7 }, { manga_id: 9 }]);
    auth.value = { user: { id: 42 } };
    render(<BookmarkSync />);
    await waitFor(() => expect(bookmarkIds().sort()).toEqual(["7", "9"]));
    expect(api.bookmarks.importBackup).toHaveBeenCalledWith({ bookmarks: [{ manga_id: 7 }] });
    expect(pendingBookmarkChanges()).toEqual({});
  });

  it("sends each change straight to the server while signed in", async () => {
    localStorage.setItem("mw_bookmarks_synced_user", "42");
    api.bookmarks.list.mockResolvedValue([]);
    auth.value = { user: { id: 42 } };
    render(<BookmarkSync />);
    await waitFor(() => expect(api.bookmarks.list).toHaveBeenCalled());
    toggleBookmark(3);
    expect(api.bookmarks.add).toHaveBeenCalledWith(3);
    toggleBookmark(3);
    expect(api.bookmarks.remove).toHaveBeenCalledWith(3);
    expect(pendingBookmarkChanges()).toEqual({});
  });

  it("keeps this browser's list when the upload fails", async () => {
    toggleBookmark(7);
    api.bookmarks.importBackup.mockRejectedValue(new Error("offline"));
    api.bookmarks.list.mockResolvedValue([]);
    auth.value = { user: { id: 42 } };
    render(<BookmarkSync />);
    await waitFor(() => expect(api.bookmarks.importBackup).toHaveBeenCalled());
    expect(api.bookmarks.list).not.toHaveBeenCalled();
    expect(bookmarkIds()).toEqual(["7"]);
    expect(lib().pending).toEqual({ 7: "add" });
  });
});
