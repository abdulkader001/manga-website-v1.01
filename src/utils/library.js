import { useSyncExternalStore } from "react";

// The reader's library -- bookmarks, which chapters they have read, and where
// they stopped -- lives in THEIR browser. Reading history never leaves it.
// For a signed-in reader the server also keeps two things under their account
// so they follow them to a new phone or computer: the bookmarked series ids
// (components/BookmarkSync.jsx, which also feed new-chapter alerts) and which
// chapters they have opened with when (components/HistorySync.jsx). This
// browser stays the main copy and works offline. A guest's library stays here
// only. Export/import (Library page) still moves everything by hand.
//
// Shape (localStorage "mw_library_v1"):
//   bookmarks: { [mangaId]: addedAtIso }
//   read:      { [mangaId]: { [chapterId]: readAtIso } }   // only chapters actually opened
//   last:      { [mangaId]: { chapterId, number, at } }    // most recent chapter per series
//   pending:   { [mangaId]: "add" | "remove" }             // bookmark changes made while signed out
//   readPending:  { [chapterId]: readAtIso }               // chapters opened but not yet sent to the account
//   clearPending: { all: boolean, manga: { [mangaId]: true } } // history cleared but not yet sent

const KEY = "mw_library_v1";
const EMPTY = {
  bookmarks: {},
  read: {},
  last: {},
  pending: {},
  readPending: {},
  clearPending: { all: false, manga: {} },
};
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

// Set by HistorySync while someone is signed in: it sends each change to the
// account. With nobody signed in, changes wait in readPending / clearPending.
// Events: {type:"read", chapterId, at} | {type:"clear", mangaId} |
// {type:"clearAll"} | {type:"flush"} (pending changes are ready to send).
let historySink = null;

/** Register the function that sends a history change to the server. */
export function onHistoryChange(fn) {
  historySink = fn;
  return () => {
    if (historySink === fn) historySink = null;
  };
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
    readPending: historySink ? lib.readPending : { ...(lib.readPending || {}), [c]: at },
  });
  if (historySink) historySink({ type: "read", chapterId: Number(chapterId), at });
}

export function readSet(lib, mangaId) {
  return new Set(Object.keys(lib.read[String(mangaId)] || {}).map(Number));
}

// Clears made while nobody is signed in wait here, so a chapter forgotten on
// this device is not brought back by the account's list at the next sign-in.
function withClear(lib, mangaId) {
  const clear = lib.clearPending || { all: false, manga: {} };
  if (mangaId == null) return { all: true, manga: {} };
  if (clear.all) return clear;
  return { all: false, manga: { ...clear.manga, [mangaId]: true } };
}

export function removeHistory(mangaId) {
  const lib = load();
  const m = String(mangaId);
  const read = { ...lib.read };
  const last = { ...lib.last };
  const readPending = { ...(lib.readPending || {}) };
  for (const c of Object.keys(read[m] || {})) delete readPending[c];
  delete read[m];
  delete last[m];
  commit({
    ...lib,
    read,
    last,
    readPending,
    clearPending: historySink ? lib.clearPending : withClear(lib, m),
  });
  if (historySink) historySink({ type: "clear", mangaId: Number(mangaId) });
}

export function clearHistory() {
  const lib = load();
  commit({
    ...lib,
    read: {},
    last: {},
    readPending: {},
    clearPending: historySink ? lib.clearPending : withClear(lib, null),
  });
  if (historySink) historySink({ type: "clearAll" });
}

/** Take the changes waiting to be sent (and empty the queue). */
export function takePendingHistory() {
  const lib = load();
  const taken = {
    reads: { ...(lib.readPending || {}) },
    clear: {
      all: Boolean(lib.clearPending?.all),
      manga: { ...(lib.clearPending?.manga || {}) },
    },
  };
  commit({ ...lib, readPending: {}, clearPending: { all: false, manga: {} } });
  return taken;
}

/** Put changes back in the queue (they could not be sent). Newer reads win. */
export function restorePendingHistory(taken) {
  const lib = load();
  const clear = lib.clearPending || { all: false, manga: {} };
  commit({
    ...lib,
    readPending: { ...taken.reads, ...(lib.readPending || {}) },
    clearPending: {
      all: clear.all || taken.clear.all,
      manga: { ...taken.clear.manga, ...clear.manga },
    },
  });
}

/** Queue every chapter read on this device (a browser's first sign-in). */
export function queueAllReads() {
  const lib = load();
  const readPending = { ...(lib.readPending || {}) };
  for (const chapters of Object.values(lib.read)) {
    for (const [c, at] of Object.entries(chapters)) readPending[c] = readPending[c] || at;
  }
  commit({ ...lib, readPending });
}

/** Forget this device's reading (a different account signed in here). */
export function resetHistory() {
  commit({
    ...load(),
    read: {},
    last: {},
    readPending: {},
    clearPending: { all: false, manga: {} },
  });
}

/**
 * Make this device's read chapters exactly the account's list ({manga_id,
 * chapter_id, chapter_number, read_at}, newest first). Chapters opened here
 * since `keepSince` are kept: the account may not have heard about them yet.
 */
export function setReadFromAccount(entries, keepSince) {
  const lib = load();
  const read = {};
  const last = {};
  const put = (m, c, at, number) => {
    read[m] = { ...(read[m] || {}), [c]: at };
    if (!last[m] || at > last[m].at) last[m] = { chapterId: Number(c), number: number ?? null, at };
  };
  for (const e of entries) {
    put(String(e.manga_id), String(e.chapter_id), e.read_at || now(), e.chapter_number);
  }
  for (const [m, chapters] of Object.entries(lib.read)) {
    for (const [c, at] of Object.entries(chapters)) {
      if (at >= keepSince) put(m, c, at, lib.last[m]?.chapterId === Number(c) ? lib.last[m].number : null);
    }
  }
  commit({ ...lib, read, last });
}

export function exportLibrary() {
  const {
    pending: _pending, // eslint-disable-line no-unused-vars
    readPending: _readPending, // eslint-disable-line no-unused-vars
    clearPending: _clearPending, // eslint-disable-line no-unused-vars
    ...library
  } = load();
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
  // Chapters this device had not seen are sent to the account too.
  const readPending = { ...(lib.readPending || {}) };
  for (const [m, chapters] of Object.entries(data.read || {})) {
    for (const [c, at] of Object.entries(chapters || {})) {
      if (!lib.read[m]?.[c]) readPending[c] = at;
    }
  }
  commit({
    ...lib,
    pending,
    readPending,
    bookmarks: { ...lib.bookmarks, ...(data.bookmarks || {}) },
    read: Object.keys(data.read || {}).reduce(
      (acc, k) => ({ ...acc, [k]: { ...(lib.read[k] || {}), ...data.read[k] } }),
      { ...lib.read }
    ),
    last: { ...lib.last, ...(data.last || {}) },
  });
  if (historySink) historySink({ type: "flush" });
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
