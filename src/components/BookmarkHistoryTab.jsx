import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import api from "../services/api";
import {
  clearHistory,
  exportLibrary,
  importLibrary,
  migrateLegacy,
  readSet,
  removeBookmark,
  removeHistory,
  useLibrary,
} from "../utils/library";
import { COVER_PLACEHOLDER, useFallback } from "../utils/placeholders";
import useAuth from "../hooks/useAuth";

// Bookmarks and reading history, kept in this browser (utils/library.js) and,
// for a signed-in reader, also on their account (BookmarkSync, HistorySync).
// The server is only asked for public facts about those series: cover, title
// and newest chapter.

const readerLink = (mangaId, chapterId) =>
  chapterId ? `/reader/${mangaId}/${chapterId}` : `/manga/${mangaId}`;

function Card({ manga, kind, lib, onRemove }) {
  const id = manga.id;
  const read = readSet(lib, id);
  const last = lib.last[String(id)];
  const latestId = manga.latest_chapter_id;
  const latestNo = manga.latest_chapter_number;
  const latestRead = latestId != null && read.has(latestId);
  const hasNew = kind === "bookmarks" && last && latestId != null && !latestRead;
  const onImgError = useFallback(COVER_PLACEHOLDER);

  // Where "Continue" goes: the next unread newest chapter, else where you stopped, else the start.
  const target = hasNew ? latestId : last?.chapterId || manga.first_chapter_id;
  const cta = hasNew ? `Read Ch. ${latestNo}` : last ? "Continue" : "Start reading";

  return (
    <article className="bg-[#15171c] border border-[#262a33] rounded-xl overflow-hidden flex flex-col group">
      <div className="relative aspect-[3/4] bg-black">
        <Link to={`/manga/${id}`}>
          <img
            src={manga.cover_url || manga.cover_image || COVER_PLACEHOLDER}
            alt={manga.title}
            loading="lazy"
            referrerPolicy="no-referrer"
            onError={onImgError}
            className="w-full h-full object-cover"
          />
        </Link>
        {hasNew && (
          <span className="absolute top-2 left-2 px-1.5 py-0.5 rounded bg-emerald-500 text-black text-[10px] font-extrabold">NEW</span>
        )}
        <button
          type="button"
          onClick={() => onRemove(id)}
          aria-label="Remove"
          className="absolute top-2 right-2 w-6 h-6 rounded-full bg-black/70 text-white text-xs hover:bg-red-600 transition"
        >
          ×
        </button>
        {manga.rating_count > 0 && (
          <span className="absolute bottom-2 left-2 px-1.5 py-0.5 rounded bg-black/70 text-amber-400 text-[10px] font-bold">
            ★ {Number(manga.rating).toFixed(1)}
          </span>
        )}
      </div>
      <div className="p-2.5 space-y-1.5 flex-1 flex flex-col">
        <Link to={`/manga/${id}`} className="font-bold text-xs text-white line-clamp-2 hover:text-[#00AEF0]">
          {manga.title}
        </Link>
        {kind === "history" && last && (
          <p className="text-[11px] text-[#00AEF0] font-semibold">Last read: Chapter {last.number ?? "?"}</p>
        )}
        {kind === "bookmarks" && (
          <p className="text-[11px] flex items-center gap-1.5">
            <span className="text-[#8b93a3]">Latest:</span>
            {latestNo != null ? (
              // light blue = you have opened it; plain = not yet read
              <span
                className={`px-1.5 py-0.5 rounded font-bold ${
                  latestRead ? "bg-[#00AEF0]/20 text-[#00AEF0]" : "bg-[#262a33] text-white"
                }`}
              >
                Ch. {latestNo}
              </span>
            ) : (
              <span className="text-[#8b93a3]">no chapters yet</span>
            )}
          </p>
        )}
        <div className="mt-auto pt-1">
          <Link
            to={readerLink(id, target)}
            className="block text-center py-1.5 rounded-lg bg-[#00AEF0] hover:bg-[#0F5065] text-white text-xs font-bold transition"
          >
            {cta}
          </Link>
        </div>
      </div>
    </article>
  );
}

export default function BookmarkHistoryTab() {
  const { user } = useAuth();
  const lib = useLibrary();
  const fileRef = useRef(null);
  const [tab, setTab] = useState("bookmarks");
  const [toast, setToast] = useState("");

  useEffect(() => migrateLegacy(), []);

  const bookmarkIds = Object.keys(lib.bookmarks);
  const historyIds = Object.keys(lib.last).sort(
    (a, b) => new Date(lib.last[b].at).getTime() - new Date(lib.last[a].at).getTime()
  );
  const ids = tab === "bookmarks" ? bookmarkIds : historyIds;
  const idsKey = ids.join(",");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["libraryCards", idsKey],
    queryFn: () => api.manga.batch(idsKey),
    enabled: ids.length > 0,
    staleTime: 60_000,
  });

  const items = useMemo(() => {
    const byId = new Map((data?.items || []).map((m) => [String(m.id), m]));
    return ids.map((id) => byId.get(id)).filter(Boolean);
  }, [data, ids]);

  const flash = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3500);
  };

  const download = () => {
    const url = URL.createObjectURL(new Blob([exportLibrary()], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `mangaworld-library-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const onFile = (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        importLibrary(String(reader.result));
        flash("Library imported.");
      } catch {
        flash("That file is not a MangaWorld library export.");
      }
    };
    reader.readAsText(file);
  };

  const tabBtn = (key, label, count) => (
    <button
      type="button"
      onClick={() => setTab(key)}
      className={`px-4 py-2 rounded-xl text-xs font-bold transition ${
        tab === key ? "bg-[#00AEF0] text-white" : "bg-[#15171c] border border-[#262a33] text-gray-300 hover:text-white"
      }`}
    >
      {label} <span className="ml-1 opacity-80">{count}</span>
    </button>
  );

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3 border-b border-[#262a33] pb-4">
        <div>
          <h1 className="text-2xl font-extrabold text-white">My Library</h1>
          <p className="text-[11px] text-[#8b93a3]">
            {user
              ? "Your bookmarks and the chapters you have read are saved to your account, so they follow you to other devices, and you get an alert when a bookmarked series has a new chapter."
              : "Saved in this browser only. Sign in to keep your bookmarks and read chapters on your account, so they follow you to other devices, and to get an alert when a bookmarked series has a new chapter."}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {tabBtn("bookmarks", "Bookmarks", bookmarkIds.length)}
          {tabBtn("history", "History", historyIds.length)}
          <button type="button" onClick={download} className="px-3 py-2 rounded-xl border border-[#262a33] text-xs text-gray-300 hover:text-white">
            Export
          </button>
          <button type="button" onClick={() => fileRef.current?.click()} className="px-3 py-2 rounded-xl border border-[#262a33] text-xs text-gray-300 hover:text-white">
            Import
          </button>
          <input ref={fileRef} type="file" accept="application/json" className="hidden" onChange={onFile} />
          {tab === "history" && historyIds.length > 0 && (
            <button
              type="button"
              onClick={() => window.confirm(user ? "Clear all reading history on this device and your account?" : "Clear all reading history on this device?") && clearHistory()}
              className="px-3 py-2 rounded-xl border border-red-500/40 text-xs text-red-300 hover:bg-red-500/10"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {toast && <div className="p-3 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-gray-200">{toast}</div>}

      {ids.length === 0 ? (
        <p className="py-16 text-center text-sm text-[#8b93a3]">
          {tab === "bookmarks" ? "No bookmarks yet. Open a series and press “Add to Bookmarks”." : "Nothing read yet."}
        </p>
      ) : isLoading ? (
        <p className="py-16 text-center text-xs text-[#8b93a3]">Loading…</p>
      ) : isError ? (
        <p className="py-16 text-center text-xs text-red-400">Could not load series details. Check your connection.</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3.5">
          {items.map((m) => (
            <Card
              key={m.id}
              manga={m}
              kind={tab}
              lib={lib}
              onRemove={tab === "bookmarks" ? removeBookmark : removeHistory}
            />
          ))}
        </div>
      )}
    </div>
  );
}
