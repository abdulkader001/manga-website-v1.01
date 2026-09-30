import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import { targetPathFor } from "../utils/notificationTargets";

const PAGE_SIZE = 20;

function formatTimestamp(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return "";
  }
}

export default function NotificationsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all"); // all | unread | chapter_issues | administrative

  const load = useCallback(async (nextOffset) => {
    setLoading(true);
    try {
      const data = await api.notifications.list({
        limit: PAGE_SIZE,
        offset: nextOffset,
      });
      const fetched = Array.isArray(data?.items) ? data.items : [];
      setItems((prev) => (nextOffset === 0 ? fetched : [...prev, ...fetched]));
      setHasMore(fetched.length === PAGE_SIZE);
      setOffset(nextOffset);
    } catch {
      if (nextOffset === 0) setItems([]);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(0);
  }, [load]);

  const handleMarkAllRead = async () => {
    try {
      await api.notifications.markAllRead();
      setItems((prev) => prev.map((item) => ({ ...item, read: true, is_read: true })));
    } catch {
      // Non-fatal.
    }
  };

  const handleItemClick = async (note) => {
    if (!note.read) {
      try {
        await api.notifications.markRead(note.id);
        setItems((prev) =>
          prev.map((item) => (item.id === note.id ? { ...item, read: true, is_read: true } : item))
        );
      } catch {
        // Non-fatal: still navigate.
      }
    }
    const path = targetPathFor(note);
    if (path) navigate(path);
  };

  const handleDismiss = async (note, event) => {
    event.stopPropagation();
    try {
      await api.notifications.remove(note.id);
      setItems((prev) => prev.filter((item) => item.id !== note.id));
    } catch {
      // Non-fatal.
    }
  };

  const chapterIssueCount = items.filter(
    (item) => item.category === "chapter_issue" || item.type === "chapter_issue" || item.type === "chapter_resolution"
  ).length;

  const visibleItems = items.filter((item) => {
    if (filter === "unread") return !item.read && !item.is_read;
    if (filter === "chapter_issues") {
      return (
        item.category === "chapter_issue" ||
        item.type === "chapter_issue" ||
        item.type === "chapter_resolution"
      );
    }
    if (filter === "administrative") return item.category === "administrative";
    return true;
  });

  const getIssueBadge = (note) => {
    const title = (note.title || "").toLowerCase();
    const body = (note.body || note.message || "").toLowerCase();
    const type = (note.data?.report_type || "").toLowerCase();

    if (note.type === "chapter_resolution") {
      return (
        <span className="flex-shrink-0 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-600 text-white flex items-center gap-1">
          <i className="fas fa-check-circle"></i> Resolved
        </span>
      );
    }
    if (type.includes("broken") || title.includes("broken") || body.includes("broken")) {
      return (
        <span className="flex-shrink-0 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-rose-600 text-white flex items-center gap-1">
          <i className="fas fa-exclamation-triangle"></i> Broken Chapter
        </span>
      );
    }
    if (type.includes("wrong") || title.includes("wrong") || body.includes("wrong")) {
      return (
        <span className="flex-shrink-0 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-600 text-white flex items-center gap-1">
          <i className="fas fa-exchange-alt"></i> Wrong Chapter
        </span>
      );
    }
    if (type.includes("image") || title.includes("image") || body.includes("image")) {
      return (
        <span className="flex-shrink-0 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-purple-600 text-white flex items-center gap-1">
          <i className="fas fa-image"></i> Missing Image
        </span>
      );
    }
    if (type.includes("text") || title.includes("text") || body.includes("text")) {
      return (
        <span className="flex-shrink-0 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-sky-600 text-white flex items-center gap-1">
          <i className="fas fa-font"></i> Missing Text
        </span>
      );
    }
    if (note.category === "chapter_issue" || note.type === "chapter_issue") {
      return (
        <span className="flex-shrink-0 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-rose-700 text-white flex items-center gap-1">
          <i className="fas fa-bug"></i> Chapter Alert
        </span>
      );
    }
    return null;
  };

  return (
    <div className="max-w-3xl mx-auto px-3 sm:px-4 py-4 sm:py-8 grid gap-4 sm:gap-5">
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[#262a33] pb-4">
        <div>
          <h1 className="text-lg sm:text-2xl font-bold text-white flex items-center gap-2">
            <i className="fas fa-bell text-[#00AEF0]"></i>
            <span>Notifications &amp; Chapter Alerts</span>
          </h1>
          <p className="text-[11px] sm:text-xs text-[#8b93a3] mt-1">
            Real-time updates on chapter releases, reported issues, and system alerts
          </p>
        </div>
        <button
          type="button"
          onClick={handleMarkAllRead}
          className="self-start sm:self-auto text-xs font-bold text-[#00AEF0] hover:underline px-3 py-1.5 rounded-lg bg-[#00AEF0]/10 border border-[#00AEF0]/20"
        >
          Mark all as read
        </button>
      </header>

      {/* Filter Tabs */}
      <div className="flex flex-wrap gap-2">
        {[
          { key: "all", label: "All", count: items.length },
          { key: "unread", label: "Unread", count: items.filter((n) => !n.read && !n.is_read).length },
          { key: "chapter_issues", label: "🚨 Chapter Alerts & Issues", count: chapterIssueCount },
          { key: "administrative", label: "Administrative" },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setFilter(tab.key)}
            className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 border ${
              filter === tab.key
                ? "bg-[#00AEF0] text-white border-[#00AEF0] shadow-md shadow-[#00AEF0]/20"
                : "bg-[#15171c] border-[#262a33] text-gray-400 hover:text-white hover:border-gray-600"
            }`}
          >
            <span>{tab.label}</span>
            {tab.count != null && tab.count > 0 && (
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] ${
                  filter === tab.key ? "bg-white/25 text-white" : "bg-[#262a33] text-gray-300"
                }`}
              >
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Notification Cards List */}
      <div className="grid gap-3">
        {loading && items.length === 0 && (
          <div className="p-8 text-center text-xs text-[#8b93a3] bg-[#15171c] border border-[#262a33] rounded-2xl">
            Loading notifications…
          </div>
        )}

        {!loading && visibleItems.length === 0 && (
          <div className="p-10 text-center text-xs text-[#8b93a3] bg-[#15171c] border border-[#262a33] rounded-2xl space-y-2">
            <div className="text-3xl">📭</div>
            <p className="font-semibold text-gray-300">
              {filter === "unread"
                ? "No unread notifications."
                : filter === "chapter_issues"
                ? "No active chapter issues reported right now. Everything is running smoothly!"
                : filter === "administrative"
                ? "No administrative notifications."
                : "No notifications yet."}
            </p>
          </div>
        )}

        {visibleItems.map((note) => {
          const isIssue =
            note.category === "chapter_issue" ||
            note.type === "chapter_issue" ||
            note.type === "chapter_resolution";

          return (
            <div
              key={note.id}
              role="button"
              tabIndex={0}
              onClick={() => handleItemClick(note)}
              onKeyDown={(event) => {
                if (event.key === "Enter") handleItemClick(note);
              }}
              className={`grid gap-2 rounded-2xl border p-4 cursor-pointer transition shadow-md ${
                isIssue
                  ? note.type === "chapter_resolution"
                    ? "bg-emerald-950/20 border-emerald-500/30 hover:border-emerald-500/50"
                    : "bg-red-950/20 border-red-500/30 hover:border-red-500/50"
                  : "bg-[#15171c] border-[#262a33] hover:border-gray-600"
              } ${note.read ? "opacity-75" : "border-l-4 border-l-[#00AEF0]"}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2 min-w-0">
                  {!note.read && !note.is_read && (
                    <span
                      className="h-2 w-2 flex-shrink-0 rounded-full bg-[#00AEF0] animate-pulse"
                      aria-hidden="true"
                    />
                  )}
                  <span className="font-bold text-white text-sm">
                    {note.title}
                  </span>

                  {getIssueBadge(note)}

                  {note.category === "administrative" && (
                    <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-600 text-white">
                      Admin
                    </span>
                  )}
                  {(note.category === "announcement" || note.type === "popup" || note.type === "system") && (
                    <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-purple-600 text-white">
                      Broadcast
                    </span>
                  )}
                  {note.category === "chapter_release" && (
                    <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-[#00AEF0] text-white">
                      New Chapter
                    </span>
                  )}
                  {note.category === "security" && (
                    <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-red-700 text-white">
                      Security
                    </span>
                  )}
                </div>

                <button
                  type="button"
                  onClick={(event) => handleDismiss(note, event)}
                  className="text-xs text-[#8b93a3] hover:text-red-400 flex-shrink-0 px-2 py-1 rounded bg-[#101216] border border-[#262a33]"
                  aria-label="Dismiss notification"
                >
                  Dismiss
                </button>
              </div>

              {(note.body || note.message) && (
                <p className="text-xs text-gray-300 leading-relaxed pl-1">
                  {note.body || note.message}
                </p>
              )}

              <div className="flex items-center justify-between pt-1 text-[11px] text-[#8b93a3]">
                <span>{formatTimestamp(note.created_at)}</span>
                {note.link && (
                  <span className="text-[#00AEF0] font-semibold hover:underline flex items-center gap-1">
                    <span>Inspect Chapter</span>
                    <i className="fas fa-chevron-right text-[9px]"></i>
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {hasMore && (
        <button
          type="button"
          onClick={() => load(offset + PAGE_SIZE)}
          disabled={loading}
          className="justify-self-center px-5 py-2.5 rounded-xl border border-[#262a33] text-xs font-bold text-white bg-[#15171c] hover:bg-[#1f2330] disabled:opacity-50 transition"
        >
          {loading ? "Loading…" : "Load more notifications"}
        </button>
      )}
    </div>
  );
}
