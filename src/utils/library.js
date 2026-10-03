import { useSyncExternalStore } from "react";

// The reader's library -- bookmarks, which chapters they have read, and where
// they stopped -- lives in THEIR browser. Reading history never leaves it.
// Bookmarks of a signed-in reader are also kept on the server as series ids
// (components/BookmarkSync.jsx), so new-chapter alerts reach them and their
// bookmarks follow them to other devices. A guest's bookmarks stay here only.
// Export/import (Library page) still moves everything between devices.
//
// Shape (localStorage "mw_library_v1"):
//   bookmarks: { [mangaId]: addedAtIso }
//   read:      { [mangaId]: { [chapterId]: readAtIso } }   // only chapters actually opened
//   last:      { [mangaId]: { chapterId, number, at } }    // most recent chapter per series
//   pending:   { [mangaId]: "add" | "remove" }             // bookmark changes made while signed out

const KEY = "mw_library_v1";
const EMPTY = { bookmarks: {}, read: {}, last: {}, pending: {} };
let cache = null;
const listeners = new Set();

function load() {
  if (cache) return cache;
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || "null");
    cache = parsed && typeof parsed === "object" ? { ...EMPTY, ...parsed } : { ...EMPTY };
  } catch {
    cache = { ...EMPTY };
  }
  return cache;
}

function commit(next) {
  cache = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // storage full or blocked: the in-memory copy still works this session
  }
  listeners.forEach((l) => l());
}

const subscribe = (fn) => {
  listeners.add(fn);
  const onStorage = (e) => {
    if (e.key === KEY) {
      cache = null;
      fn();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", onStorage);
  };
};

/** Reactive snapshot of the whole library. */
export function useLibrary() {
  return useSyncExternalStore(subscribe, load, () => EMPTY);
}

const now = () => new Date().toISOString();

export function isBookmarked(lib, mangaId) {
  return Boolean(lib.bookmarks[String(mangaId)]);
}

// Set by BookmarkSync while someone is signed in: it sends each bookmark
// change to the server. With nobody signed in, changes wait in `pending`.
let bookmarkSink = null;

/** Register the function that sends a bookmark change to the server. */
export function onBookmarkChange(fn) {
  bookmarkSink = fn;
  return () => {
    if (bookmarkSink === fn) bookmarkSink = null;
  };
}

function withChange(lib, id, on) {
  if (bookmarkSink) {
    bookmarkSink(id, on);
    return lib.pending || {};
  }
  return { ...(lib.pending || {}), [id]: on ? "add" : "remove" };
}

export function toggleBookmark(mangaId) {
  const lib = load();
  const id = String(mangaId);
  const bookmarks = { ...lib.bookmarks };
  if (bookmarks[id]) delete bookmarks[id];
  else bookmarks[id] = now();
  const on = Boolean(bookmarks[id]);
  commit({ ...lib, bookmarks, pending: withChange(lib, id, on) });
  return on;
}

export function removeBookmark(mangaId) {
  const lib = load();
  const id = String(mangaId);
  const bookmarks = { ...lib.bookmarks };
  delete bookmarks[id];
  commit({ ...lib, bookmarks, pending: withChange(lib, id, false) });
}

export function bookmarkIds() {
  return Object.keys(load().bookmarks);
}

export function pendingBookmarkChanges() {
  return { ...(load().pending || {}) };
}

/** After the pending changes reached the server. */
export function clearPendingBookmarks() {
  commit({ ...load(), pending: {} });
}

/** Make the bookmarks exactly the server's list (keeping when each was added). */
export function setBookmarks(ids) {
  const lib = load();
  const bookmarks = {};
  for (const raw of ids) {
    const id = String(raw);
    bookmarks[id] = lib.bookmarks[id] || now();
  }
  commit({ ...lib, bookmarks });
}

/** Mark ONE chapter as read and remember it as the place the reader stopped. */
export function recordRead(mangaId, chapterId, number) {
  if (!mangaId || !chapterId) return;
  const lib = load();
  const m = String(mangaId);
  const c = String(chapterId);
  const at = now();
  commit({
    ...lib,
    read: { ...lib.read, [m]: { ...(lib.read[m] || {}), [c]: at } },
    last: { ...lib.last, [m]: { chapterId: Number(chapterId), number: number ?? null, at } },
  });
}

export function readSet(lib, mangaId) {
  return new Set(Object.keys(lib.read[String(mangaId)] || {}).map(Number));
}

export function removeHistory(mangaId) {
  const lib = load();
  const read = { ...lib.read };
  const last = { ...lib.last };
  delete read[String(mangaId)];
  delete last[String(mangaId)];
  commit({ ...lib, read, last });
}

export function clearHistory() {
  commit({ ...load(), read: {}, last: {} });
}

export function exportLibrary() {
  const { pending: _pending, ...library } = load(); // eslint-disable-line no-unused-vars
  return JSON.stringify({ version: 1, exportedAt: now(), ...library }, null, 2);
}

export function importLibrary(text) {
  const data = JSON.parse(text);
  if (!data || typeof data !== "object") throw new Error("Not a library file.");
  const lib = load();
  let pending = lib.pending || {};
  for (const id of Object.keys(data.bookmarks || {})) {
    if (!lib.bookmarks[id]) pending = withChange({ pending }, id, true);
  }
  commit({
    pending,
    bookmarks: { ...lib.bookmarks, ...(data.bookmarks || {}) },
    read: Object.keys(data.read || {}).reduce(
      (acc, k) => ({ ...acc, [k]: { ...(lib.read[k] || {}), ...data.read[k] } }),
      { ...lib.read }
    ),
    last: { ...lib.last, ...(data.last || {}) },
  });
}

/** One-time move of the old per-series keys written by earlier versions. */
export function migrateLegacy() {
  try {
    if (localStorage.getItem("mw_library_migrated")) return;
    const lib = load();
    const read = { ...lib.read };
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i) || "";
      const m = /^manga_read_chapters_(\d+)$/.exec(key);
      if (!m) continue;
      // Old versions also marked every lower chapter number as read, which
      // is not real reading history, so those entries are dropped.
      read[m[1]] = read[m[1]] || {};
      localStorage.removeItem(key);
      localStorage.removeItem(`manga_max_read_${m[1]}`);
    }
    commit({ ...lib, read });
    localStorage.setItem("mw_library_migrated", "1");
  } catch {
    // ignore
  }
}
