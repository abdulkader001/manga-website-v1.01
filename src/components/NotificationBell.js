import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import api from "../services/api";
import { targetPathFor } from "../utils/notificationTargets";

const POLL_INTERVAL_MS = 20000;

function formatTimestamp(iso) {
  if (!iso) return "";
  try {
    const date = new Date(iso);
    return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

export default function NotificationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef(null);

  const loadUnreadCount = useCallback(async () => {
    try {
      const data = await api.notifications.unreadCount();
      setUnreadCount(Number(data?.count) || 0);
    } catch {
      // Silent: the bell must never break the rest of the page (1I.5.1).
    }
  }, []);

  const loadPanel = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.notifications.list({ limit: 10 });
      setItems(Array.isArray(data?.items) ? data.items : []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUnreadCount();
    const interval = setInterval(loadUnreadCount, POLL_INTERVAL_MS);
    const handleSync = () => loadUnreadCount();
    window.addEventListener("notifications-updated", handleSync);
    return () => {
      clearInterval(interval);
      window.removeEventListener("notifications-updated", handleSync);
    };
  }, [loadUnreadCount]);

  useEffect(() => {
    if (open) {
      loadPanel();
    }
  }, [open, loadPanel]);

  useEffect(() => {
    function handleDocumentClick(event) {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    function handleEscape(event) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleDocumentClick);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleDocumentClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  const handleMarkAllRead = async () => {
    try {
      await api.notifications.markAllRead();
      setItems((prev) => prev.map((item) => ({ ...item, read: true })));
      setUnreadCount(0);
    } catch {
      // Best-effort; the badge will resync on the next poll.
    }
  };

  const handleItemClick = async (note) => {
    if (!note.read) {
      try {
        await api.notifications.markRead(note.id);
        setItems((prev) =>
          prev.map((item) => (item.id === note.id ? { ...item, read: true } : item))
        );
        setUnreadCount((prev) => Math.max(0, prev - 1));
      } catch {
        // Non-fatal: still navigate.
      }
    }
    const path = targetPathFor(note);
    setOpen(false);
    if (path) navigate(path);
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="relative p-1.5 sm:p-2 rounded-full hover:bg-gray-800 text-gray-300 hover:text-white transition-colors"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={
          unreadCount > 0 ? `Notifications, ${unreadCount} unread` : "Notifications"
        }
      >
        <svg
          className="h-4 w-4 sm:h-5 sm:w-5"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.89 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4a1.5 1.5 0 00-3 0v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z" />
        </svg>
        {unreadCount > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-[1rem] h-[1rem] px-1 rounded-full bg-red-600 text-white text-[9px] sm:text-[10px] leading-[1rem] text-center font-bold"
            data-testid="notification-badge"
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {/* Backdrop for mobile */}
      {open && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-xs z-40 sm:hidden"
          onClick={() => setOpen(false)}
          aria-hidden="true"
        />
      )}

      {open && (
        <div
          className="fixed left-3 right-3 top-14 z-50 sm:absolute sm:left-auto sm:right-0 sm:top-auto sm:mt-2 sm:w-80 max-w-sm sm:max-w-[90vw] rounded-xl bg-[#15171c] border border-[#262a33] shadow-2xl overflow-hidden"
          role="menu"
          aria-label="Notifications"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-3.5 py-2.5 bg-[#101216] border-b border-[#262a33]">
            <div className="flex items-center gap-1.5">
              <span className="text-xs sm:text-sm font-bold text-white">Notifications</span>
              {unreadCount > 0 && (
                <span className="bg-[#00AEF0] text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full">
                  {unreadCount}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleMarkAllRead}
                className="text-[11px] text-[#00AEF0] hover:underline font-semibold"
              >
                Mark all read
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-gray-400 hover:text-white text-xs sm:hidden"
                title="Close"
              >
                ✕
              </button>
            </div>
          </div>

          {/* List */}
          <div className="max-h-[60vh] sm:max-h-96 overflow-y-auto divide-y divide-[#262a33]/60">
            {loading && (
              <div className="px-3 py-6 text-center text-xs text-gray-400">Loading notifications…</div>
            )}
            {!loading && items.length === 0 && (
              <div className="px-3 py-8 text-center text-xs text-gray-400">
                You're all caught up.
              </div>
            )}
            {!loading &&
              items.map((note) => (
                <button
                  key={note.id}
                  type="button"
                  role="menuitem"
                  onClick={() => handleItemClick(note)}
                  className={`w-full text-left px-3.5 py-2.5 hover:bg-[#1f2330] transition-colors flex items-start gap-2.5 ${
                    note.read ? "opacity-60" : "bg-[#15171c]"
                  }`}
                >
                  {!note.read && (
                    <span
                      className="mt-1 h-2 w-2 flex-shrink-0 rounded-full bg-[#00AEF0]"
                      aria-hidden="true"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center flex-wrap gap-1.5 mb-0.5">
                      <span className="text-xs sm:text-sm font-bold text-white break-words line-clamp-1">
                        {note.title}
                      </span>
                      {note.category === "administrative" && (
                        <span className="flex-shrink-0 px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-amber-600 text-white">
                          Admin
                        </span>
                      )}
                      {(note.category === "announcement" || note.type === "popup" || note.type === "system") && (
                        <span className="flex-shrink-0 px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-purple-600 text-white">
                          Broadcast
                        </span>
                      )}
                      {note.category === "chapter_release" && (
                        <span className="flex-shrink-0 px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-[#00AEF0] text-white">
                          New Chapter
                        </span>
                      )}
                      {note.category === "security" && (
                        <span className="flex-shrink-0 px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-red-700 text-white">
                          Security
                        </span>
                      )}
                    </div>
                    {(note.body || note.message) && (
                      <p className="text-[11px] text-gray-300 line-clamp-2 leading-relaxed break-words">
                        {note.body || note.message}
                      </p>
                    )}
                    <span className="text-[10px] text-gray-500 mt-1 block">
                      {formatTimestamp(note.created_at)}
                    </span>
                  </div>
                </button>
              ))}
          </div>

          {/* Footer */}
          <div className="px-3 py-2 bg-[#101216] border-t border-[#262a33] text-center">
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                navigate("/notifications");
              }}
              className="text-xs text-[#00AEF0] hover:underline font-bold"
            >
              View all notifications »
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
