import React, { useMemo, useState, useRef } from "react";
import { Link } from "react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../services/api";

// A real chapter when one is known, otherwise the series page.
const readerLink = (mangaId, chapterId) =>
  chapterId ? `/reader/${mangaId}/${chapterId}` : `/manga/${mangaId}`;

export default function BookmarkHistoryTab() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef(null);

  // Active tab: "bookmarks" | "history"
  const [activeTab, setActiveTab] = useState("bookmarks");
  const [toastMessage, setToastMessage] = useState(null);

  // View mode preference stored in localStorage: "grid" | "list"
  const [viewMode, setViewMode] = useState(() => {
    try {
      return localStorage.getItem("manga_bookmarks_view_mode") || "grid";
    } catch {
      return "grid";
    }
  });

  const handleSetViewMode = (mode) => {
    setViewMode(mode);
    try {
      localStorage.setItem("manga_bookmarks_view_mode", mode);
    } catch {
      // Ignore storage errors
    }
  };

  // Queries
  const {
    data: bookmarksData,
    isLoading: bookmarksLoading,
    isError: bookmarksError,
  } = useQuery({
    queryKey: ["bookmarks"],
    queryFn: () => api.bookmarks.list(),
  });

  const {
    data: historyData,
    isLoading: historyLoading,
    isError: historyError,
  } = useQuery({
    queryKey: ["history"],
    queryFn: () => api.history.list(),
  });

  const bookmarks = Array.isArray(bookmarksData) ? bookmarksData : [];
  const history = Array.isArray(historyData) ? historyData : [];

  // Mutations
  const removeBookmarkMutation = useMutation({
    mutationFn: (mangaId) => api.bookmarks.remove(mangaId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bookmarks"] });
      showToast("Bookmark removed");
    },
  });

  const removeHistoryMutation = useMutation({
    mutationFn: (id) => api.history.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["history"] });
      showToast("History entry removed");
    },
  });

  const clearHistoryMutation = useMutation({
    mutationFn: () => api.history.clearAll(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["history"] });
      showToast("Reading history cleared");
    },
  });

  const importBackupMutation = useMutation({
    mutationFn: (payload) => api.bookmarks.importBackup(payload),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["bookmarks"] });
      queryClient.invalidateQueries({ queryKey: ["history"] });
      showToast(data?.message || `Successfully imported ${data?.importedBookmarks || 0} bookmarks!`);
    },
    onError: () => {
      showToast("Failed to import backup JSON. Check file format.");
    },
  });

  const showToast = (msg) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  // Export JSON functionality
  const handleExportJSON = () => {
    try {
      const backupData = {
        app: "MangaWorld",
        version: "1.0",
        exported_at: new Date().toISOString(),
        bookmarks,
        history,
      };
      const blob = new Blob([JSON.stringify(backupData, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `manga_bookmarks_history_${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      showToast("✅ Downloaded bookmark & history JSON file!");
    } catch (err) {
      console.error("Export failed:", err);
      showToast("Failed to export JSON file.");
    }
  };

  // Import JSON functionality
  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const parsed = JSON.parse(event.target?.result);
        if (!parsed || (typeof parsed !== "object")) {
          throw new Error("Invalid format");
        }
        importBackupMutation.mutate({
          bookmarks: parsed.bookmarks || [],
          history: parsed.history || [],
        });
      } catch (err) {
        showToast("Invalid JSON file. Please provide a valid exported backup.");
      } finally {
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    };
    reader.readAsText(file);
  };

  // Format date helper
  const formatDate = (dateString) => {
    if (!dateString) return "";
    try {
      const d = new Date(dateString);
      return d.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return "";
    }
  };

  const loading = activeTab === "bookmarks" ? bookmarksLoading : historyLoading;
  const isError = activeTab === "bookmarks" ? bookmarksError : historyError;

  // Auto-sort bookmarks so newly released chapters rocket to top #1, serialized by update dates
  const currentItems = useMemo(() => {
    if (activeTab === "history") {
      return [...history].sort((a, b) => {
        const timeA = new Date(a.last_read_at || a.created_at || 0).getTime();
        const timeB = new Date(b.last_read_at || b.created_at || 0).getTime();
        return timeB - timeA;
      });
    }

    // Bookmarks: rocket recently updated manga to the top (#1 rank, then #2, #3, etc.)
    return [...bookmarks].sort((a, b) => {
      const mangaA = a.manga || {};
      const mangaB = b.manga || {};
      const dateA = new Date(mangaA.updated_at || a.updated_at || a.latest_chapter?.created_at || a.added_at || a.created_at || 0).getTime();
      const dateB = new Date(mangaB.updated_at || b.updated_at || b.latest_chapter?.created_at || b.added_at || b.created_at || 0).getTime();
      return dateB - dateA;
    });
  }, [activeTab, bookmarks, history]);

  // Build a lookup map of user reading history by mangaId
  const historyByMangaId = useMemo(() => {
    const map = new Map();
    history.forEach((h) => {
      const mId = String(h.manga_id);
      if (!map.has(mId)) {
        map.set(mId, h);
      }
    });
    return map;
  }, [history]);

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#1f2330] border border-[#00AEF0] text-white px-4 py-2.5 rounded-xl shadow-2xl text-xs font-semibold flex items-center gap-2 animate-in fade-in slide-in-from-bottom-3">
          <i className="fas fa-info-circle text-[#00AEF0]"></i>
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Hidden File Input for JSON Import */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept=".json,application/json"
        className="hidden"
      />

      {/* Header & Controls Row */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-[#262a33] pb-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center gap-2">
            <i className={activeTab === "bookmarks" ? "fas fa-bookmark text-[#00AEF0]" : "fas fa-history text-[#00AEF0]"}></i>
            <span>{activeTab === "bookmarks" ? "Bookmarks Library" : "Reading History"}</span>
          </h1>
          <p className="text-xs text-[#8b93a3] mt-1">
            Pick up right where you left off or organize your favorite saved series.
          </p>
        </div>

        {/* Action Controls: Compact Interchange Button, Import/Export, and Grid/List */}
        <div className="flex items-center gap-2 self-start sm:self-auto flex-wrap">
          {/* Concise Interchange Button: Just says "Bookmarks" or "History" */}
          <button
            type="button"
            onClick={() => setActiveTab(activeTab === "bookmarks" ? "history" : "bookmarks")}
            className="px-4 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white text-xs sm:text-sm font-bold flex items-center gap-2 shadow-md transition"
            title={`Switch to ${activeTab === "bookmarks" ? "History" : "Bookmarks"}`}
          >
            <i className={activeTab === "bookmarks" ? "fas fa-bookmark" : "fas fa-history"}></i>
            <span>{activeTab === "bookmarks" ? "Bookmarks" : "History"}</span>
            <span className="px-1.5 py-0.5 rounded-full text-[10px] bg-black/25 text-white font-semibold">
              {activeTab === "bookmarks" ? bookmarks.length : history.length}
            </span>
          </button>

          {/* Export JSON File Button */}
          <button
            type="button"
            onClick={handleExportJSON}
            className="px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] hover:border-emerald-500 text-gray-300 hover:text-white text-xs font-semibold flex items-center gap-1.5 shadow-sm transition"
            title="Download JSON backup of bookmarks and history"
          >
            <i className="fas fa-file-download text-emerald-400"></i>
            <span>Export JSON</span>
          </button>

          {/* Import JSON File Button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] hover:border-[#00AEF0] text-gray-300 hover:text-white text-xs font-semibold flex items-center gap-1.5 shadow-sm transition"
            title="Restore bookmarks & history from a JSON file"
          >
            <i className="fas fa-file-upload text-[#00AEF0]"></i>
            <span>Import JSON</span>
          </button>

          {/* Grid / List Toggle */}
          <button
            type="button"
            onClick={() => handleSetViewMode(viewMode === "grid" ? "list" : "grid")}
            className="px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-gray-300 hover:text-white hover:border-[#00AEF0] text-xs font-bold flex items-center gap-1.5 shadow-sm transition"
            title="Toggle Grid / List View"
          >
            <i className={viewMode === "grid" ? "fas fa-th" : "fas fa-list"}></i>
            <span>{viewMode === "grid" ? "Grid" : "List"}</span>
          </button>

          {/* Clear History (when on history) */}
          {activeTab === "history" && history.length > 0 && (
            <button
              type="button"
              onClick={() => clearHistoryMutation.mutate()}
              className="text-xs font-semibold text-red-400 hover:text-red-300 flex items-center gap-1 px-3 py-2 bg-red-950/30 border border-red-900/50 rounded-xl transition"
            >
              <i className="fas fa-trash-alt text-[10px]"></i>
              <span>Clear</span>
            </button>
          )}
        </div>
      </div>

      {/* Loading & Error States */}
      {loading && (
        <div className="text-center py-16 text-[#8b93a3]">
          Loading {activeTab}...
        </div>
      )}

      {isError && (
        <div className="bg-red-950/40 border border-red-900 text-red-300 p-4 rounded-xl text-xs">
          Failed to load {activeTab}. Please try again later.
        </div>
      )}

      {/* Empty State */}
      {!loading && !isError && currentItems.length === 0 && (
        <div className="text-center py-16 bg-[#15171c] border border-[#262a33] rounded-2xl p-8 max-w-lg mx-auto space-y-3">
          <div className="text-4xl">📚</div>
          <h3 className="text-lg font-bold text-white">
            {activeTab === "bookmarks" ? "No bookmarks yet" : "No reading history yet"}
          </h3>
          <p className="text-xs text-[#8b93a3] max-w-sm mx-auto">
            {activeTab === "bookmarks"
              ? "Keep track of manga you love by bookmarking them from any title page."
              : "Chapters you open in the reader will automatically appear here."}
          </p>
          <div className="pt-2">
            <Link
              to="/browse"
              className="inline-flex items-center gap-2 px-4 py-2 bg-[#00AEF0] text-white text-xs font-bold rounded-lg hover:bg-[#0F5065] transition"
            >
              <i className="fab fa-safari"></i>
              <span>Browse Comics</span>
            </Link>
          </div>
        </div>
      )}

      {/* Grid Mode */}
      {!loading && !isError && currentItems.length > 0 && viewMode === "grid" && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3.5">
          {currentItems.map((item) => {
            const manga = item.manga || {};
            const mangaId = item.manga_id || manga.id || 1;
            const chapterId = item.chapter_id || manga.first_chapter_id || null;
            const cover = manga.cover_url || manga.cover_image || "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600&auto=format&fit=crop&q=80";
            const title = item.manga_title || manga.title || `Manga #${mangaId}`;
            const chapterLabel = item.chapter_title || item.chapter?.title || `Chapter 1`;
            const dateStr = formatDate(item.last_read_at || item.created_at || item.added_at);

            // Last read chapter from user's history
            const userLastRead = historyByMangaId.get(String(mangaId));
            const lastReadNum = userLastRead?.chapter?.chapter_number || userLastRead?.chapter_number || null;

            // Latest chapter available
            const latestChapter = item.latest_chapter || manga.latest_chapter;
            const latestNum = latestChapter?.chapter_number || manga.chapters_count || "New";

            // Unread state
            const isUnread = !userLastRead || (lastReadNum !== null && String(lastReadNum) !== String(latestNum));

            return (
              <article key={item.id} className="comic-card group relative flex flex-col justify-between">
                {/* Remove button overlay */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    if (activeTab === "bookmarks") {
                      removeBookmarkMutation.mutate(mangaId);
                    } else {
                      removeHistoryMutation.mutate(item.id);
                    }
                  }}
                  className="absolute top-2 right-2 z-10 w-6 h-6 rounded-full bg-black/70 hover:bg-red-600 text-white flex items-center justify-center text-[10px] transition"
                  title="Remove"
                >
                  ✕
                </button>

                {/* Cover with badge */}
                <div className="comic-card__cover">
                  <span className="comic-card__badge--trending">
                    {activeTab === "bookmarks" ? "Saved" : "Read"}
                  </span>
                  <Link to={`/manga/${mangaId}`}>
                    <img src={cover} alt={title} loading="lazy" />
                  </Link>
                  <span className="mgeko-badge-score">
                    <i className="fas fa-star"></i>
                    <span>{(manga.rating || 0) > 0 ? (manga.rating).toFixed(1) : "0.0"}</span>
                  </span>
                </div>

                {/* Content */}
                <div className="comic-card__content flex flex-col justify-between flex-grow p-2.5">
                  <div>
                    <h3 className="comic-card__title group-hover:text-[#00AEF0] transition" title={title}>
                      <Link to={`/manga/${mangaId}`}>{title}</Link>
                    </h3>

                    {/* Bookmark Mode: Distinct Colored Badges for Last Read (Darkish Blue) and Latest Unread (Lighter Color) */}
                    {activeTab === "bookmarks" ? (
                      <div className="flex flex-col gap-1.5 mt-2">
                        {/* Last Read Chapter in Darkish Blue */}
                        {lastReadNum ? (
                          <div
                            className="px-2 py-0.5 rounded bg-[#0B253A] border border-[#00AEF0]/40 text-[#00AEF0] text-[10px] font-bold truncate flex items-center gap-1 shadow-sm"
                            title={`Last chapter you read: Chapter ${lastReadNum}`}
                          >
                            <i className="fas fa-check-circle text-[9px]"></i>
                            <span>Read: Ch. {lastReadNum}</span>
                          </div>
                        ) : (
                          <div className="px-2 py-0.5 rounded bg-[#101216] border border-[#262a33] text-gray-500 text-[10px]">
                            Not started yet
                          </div>
                        )}

                        {/* Latest Chapter in Lighter Color if unread */}
                        <div
                          className={`px-2 py-0.5 rounded text-[10px] font-bold truncate flex items-center gap-1 ${
                            isUnread
                              ? "bg-[#00AEF0] text-white shadow-sm"
                              : "bg-[#1f2330] text-gray-300 border border-[#262a33]"
                          }`}
                          title={isUnread ? "New unread chapter available!" : "All caught up to latest"}
                        >
                          <i className="fas fa-bolt text-[9px]"></i>
                          <span>Latest: Ch. {latestNum}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="text-[11px] text-[#00AEF0] font-semibold truncate mt-1">
                        {chapterLabel}
                      </div>
                    )}

                    <div className="text-[10px] text-[#8b93a3] mt-1">
                      {dateStr}
                    </div>
                  </div>

                  <div className="mt-3">
                    <Link
                      to={readerLink(mangaId, userLastRead?.chapter_id || chapterId)}
                      className="comic-card__button w-full"
                    >
                      ▶ {activeTab === "bookmarks" && userLastRead ? "Continue" : "Read Now"}
                    </Link>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {/* List Mode */}
      {!loading && !isError && currentItems.length > 0 && viewMode === "list" && (
        <div className="flex flex-col gap-3">
          {currentItems.map((item) => {
            const manga = item.manga || {};
            const mangaId = item.manga_id || manga.id || 1;
            const chapterId = item.chapter_id || manga.first_chapter_id || null;
            const cover = manga.cover_url || manga.cover_image || "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600&auto=format&fit=crop&q=80";
            const title = item.manga_title || manga.title || `Manga #${mangaId}`;
            const chapterLabel = item.chapter_title || item.chapter?.title || `Chapter 1`;
            const dateStr = formatDate(item.last_read_at || item.created_at || item.added_at);

            // Last read chapter from user's history
            const userLastRead = historyByMangaId.get(String(mangaId));
            const lastReadNum = userLastRead?.chapter?.chapter_number || userLastRead?.chapter_number || null;

            // Latest chapter available
            const latestChapter = item.latest_chapter || manga.latest_chapter;
            const latestNum = latestChapter?.chapter_number || manga.chapters_count || "New";

            // Unread state
            const isUnread = !userLastRead || (lastReadNum !== null && String(lastReadNum) !== String(latestNum));

            return (
              <article
                key={item.id}
                className="flex items-center gap-3 bg-[#15171c] border border-[#262a33] rounded-xl p-3 hover:border-[#00AEF0] transition group"
              >
                <Link
                  to={`/manga/${mangaId}`}
                  className="w-20 sm:w-24 h-28 sm:h-32 flex-none rounded-lg overflow-hidden bg-black relative"
                >
                  <img
                    src={cover}
                    alt={title}
                    className="w-full h-full object-cover group-hover:scale-105 transition"
                    loading="lazy"
                  />
                  <span className="mgeko-badge-score">
                    <i className="fas fa-star"></i>
                    <span>{(manga.rating || 0) > 0 ? (manga.rating).toFixed(1) : "0.0"}</span>
                  </span>
                </Link>

                <div className="flex-1 min-w-0 flex flex-col justify-between py-1">
                  <div>
                    <h3 className="font-bold text-sm sm:text-base text-white truncate group-hover:text-[#00AEF0] transition">
                      <Link to={`/manga/${mangaId}`}>{title}</Link>
                    </h3>

                    {activeTab === "bookmarks" ? (
                      <div className="flex items-center gap-2 flex-wrap mt-1.5">
                        {/* Last Read in Darkish Blue */}
                        {lastReadNum ? (
                          <span className="px-2.5 py-0.5 rounded bg-[#0B253A] border border-[#00AEF0]/40 text-[#00AEF0] text-xs font-bold flex items-center gap-1 shadow-sm">
                            <i className="fas fa-check-circle text-[10px]"></i>
                            <span>Last Read: Ch. {lastReadNum}</span>
                          </span>
                        ) : (
                          <span className="px-2.5 py-0.5 rounded bg-[#101216] border border-[#262a33] text-gray-500 text-xs">
                            Not started yet
                          </span>
                        )}

                        {/* Latest Chapter in Lighter Color if unread */}
                        <span
                          className={`px-2.5 py-0.5 rounded text-xs font-bold flex items-center gap-1 ${
                            isUnread
                              ? "bg-[#00AEF0] text-white shadow-sm"
                              : "bg-[#1f2330] text-gray-300 border border-[#262a33]"
                          }`}
                        >
                          <i className="fas fa-bolt text-[10px]"></i>
                          <span>Latest: Ch. {latestNum}</span>
                        </span>
                      </div>
                    ) : (
                      <Link
                        to={readerLink(mangaId, chapterId)}
                        className="text-xs text-[#00AEF0] font-semibold hover:underline block mt-1"
                      >
                        {chapterLabel}
                      </Link>
                    )}

                    <div className="text-[11px] text-[#8b93a3] mt-1 flex items-center gap-2">
                      <span>{activeTab === "bookmarks" ? "Added:" : "Last read:"} {dateStr}</span>
                      {manga.country && (
                        <span className="mgeko-flag uppercase">{manga.country}</span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center justify-between mt-3 pt-2 border-t border-[#262a33]/60">
                    <Link
                      to={readerLink(mangaId, userLastRead?.chapter_id || chapterId)}
                      className="px-3.5 py-1.5 bg-[#00AEF0] text-white text-xs font-bold rounded-lg hover:bg-[#0F5065] transition inline-flex items-center gap-1.5"
                    >
                      <i className="fas fa-book-open text-[10px]"></i>
                      <span>{activeTab === "bookmarks" && userLastRead ? "Continue Reading" : "Read Chapter"}</span>
                    </Link>

                    <button
                      type="button"
                      onClick={() => {
                        if (activeTab === "bookmarks") {
                          removeBookmarkMutation.mutate(mangaId);
                        } else {
                          removeHistoryMutation.mutate(item.id);
                        }
                      }}
                      className="text-xs text-gray-400 hover:text-red-400 px-2 py-1 transition flex items-center gap-1"
                      title="Remove"
                    >
                      <i className="fas fa-trash-alt text-[11px]"></i>
                      <span className="hidden sm:inline">Remove</span>
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
