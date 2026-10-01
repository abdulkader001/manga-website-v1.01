import React, { useCallback, useEffect, useState, useMemo } from "react";
import { Link } from "react-router";
import api, { apiFetch } from "../services/api";
import AdPlacement from "./AdPlacement";
import AdSection from "./GlobalAds";
import useAuth from "../hooks/useAuth";
import { formatTimeAgo, formatGstTime } from "../utils/gstTime";

export default function Homepage() {
  const { user, isAdmin, isSecondaryAdmin } = useAuth();
  const isUserAdmin = user?.is_admin === true || isAdmin || isSecondaryAdmin;

  // Header and Notice configuration
  const [headerTitle, setHeaderTitle] = useState(() => {
    return localStorage.getItem("mgeko_header_title") || "Recently Updated Manga Chapters";
  });
  const [headerSubtitle, setHeaderSubtitle] = useState(() => {
    return localStorage.getItem("mgeko_header_subtitle") || "New chapters are immediately updated on our website as soon as they are translated.";
  });

  // Notification types: 'fix', 'solve', 'alert', 'issue', 'popup'
  const [notifications, setNotifications] = useState([
    { id: 1, type: "fix", text: "Fix applied: Fast OCR Machine Translation engine upgraded across all chapters", enabled: true },
    { id: 2, type: "solve", text: "Solved: High-capacity CDN image servers active worldwide", enabled: true },
    { id: 3, type: "alert", text: "If images are not loading, use VPN or change dns to 1.1.1.1", enabled: true },
    { id: 4, type: "issue", text: "We are fixing server issue,, thanks", enabled: true },
  ]);

  // Active Global Modal Pop-up state
  const [activePopup, setActivePopup] = useState(null);

  // Admin Broadcast Modal state
  const [broadcastModalOpen, setBroadcastModalOpen] = useState(false);
  const [editHeaderModalOpen, setEditHeaderModalOpen] = useState(false);
  const [tempHeaderTitle, setTempHeaderTitle] = useState(headerTitle);
  const [tempHeaderSubtitle, setTempHeaderSubtitle] = useState(headerSubtitle);

  // New notification form state
  const [newNoticeType, setNewNoticeType] = useState("alert");
  const [newNoticeText, setNewNoticeText] = useState("");
  const [isModalPopup, setIsModalPopup] = useState(false);
  const [noticesExpandedMobile, setNoticesExpandedMobile] = useState(false);

  // Manga Data states (50 per page)
  const [mangaList, setMangaList] = useState([]);
  const [totalManga, setTotalManga] = useState(125);
  const [mostViewedPeriod, setMostViewedPeriod] = useState("1d");
  const [mostViewed, setMostViewed] = useState([]);
  const [newManga, setNewManga] = useState([]);
  const [filterType, setFilterType] = useState("All");
  const [sortDropdownOpen, setSortDropdownOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(false);
  const [autoSlideEnabled, setAutoSlideEnabled] = useState(true);
  const [isSliderHovered, setIsSliderHovered] = useState(false);

  // Mouse drag-to-scroll for the card rows. The pointer is only captured once
  // the mouse has actually moved: capturing on pointerdown retargets the click
  // to the row, so a plain click on a card never reached its <Link>. Touch and
  // pen keep the browser's native swipe scrolling.
  const usePointerDragScroll = () => {
    const [isDragging, setIsDragging] = useState(false);
    const stateRef = React.useRef({ isDown: false, startX: 0, startScrollLeft: 0, hasMoved: false });

    const onPointerDown = (e) => {
      if (e.pointerType !== "mouse" || e.button !== 0) return;
      stateRef.current = {
        isDown: true,
        startX: e.clientX,
        startScrollLeft: e.currentTarget.scrollLeft,
        hasMoved: false,
      };
    };

    const onPointerMove = (e) => {
      const st = stateRef.current;
      if (!st.isDown) return;
      const dx = e.clientX - st.startX;
      if (!st.hasMoved) {
        if (Math.abs(dx) <= 5) return;
        st.hasMoved = true;
        setIsDragging(true);
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch {}
      }
      e.currentTarget.scrollLeft = st.startScrollLeft - dx;
    };

    const endDrag = (e) => {
      if (!stateRef.current.isDown) return;
      stateRef.current.isDown = false;
      setIsDragging(false);
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {}
    };

    // Swallow only the click that ends a drag, so dragging never opens a card.
    const onClickCapture = (e) => {
      if (stateRef.current.hasMoved) {
        e.preventDefault();
        e.stopPropagation();
        stateRef.current.hasMoved = false;
      }
    };

    return {
      isDragging,
      handlers: {
        onPointerDown,
        onPointerMove,
        onPointerUp: endDrag,
        onPointerCancel: endDrag,
        onClickCapture,
      },
    };
  };

  const mostViewedDrag = usePointerDragScroll();
  const newMangaDrag = usePointerDragScroll();

  // Circular slide handler: moves left/right and loops in a circle
  const handleCircularSlide = (elementId, direction) => {
    const el = document.getElementById(elementId);
    if (!el) return;
    const scrollStep = 240;
    const maxScroll = el.scrollWidth - el.clientWidth;

    if (direction === "right") {
      if (el.scrollLeft >= maxScroll - 15) {
        el.scrollTo({ left: 0, behavior: "smooth" });
      } else {
        el.scrollBy({ left: scrollStep, behavior: "smooth" });
      }
    } else {
      if (el.scrollLeft <= 15) {
        el.scrollTo({ left: maxScroll, behavior: "smooth" });
      } else {
        el.scrollBy({ left: -scrollStep, behavior: "smooth" });
      }
    }
  };

  // Relaxed, slow auto-slide rotation (7 seconds, paused when hovered/dragged)
  useEffect(() => {
    if (!autoSlideEnabled || isSliderHovered) return;
    const interval = setInterval(() => {
      handleCircularSlide("most-viewed-slider", "right");
      handleCircularSlide("new-manga-slider", "right");
    }, 7000);
    return () => clearInterval(interval);
  }, [autoSlideEnabled, isSliderHovered]);

  // Load announcements from server if available
  useEffect(() => {
    apiFetch("/api/v1/announcements")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.announcements && Array.isArray(data.announcements)) {
          setNotifications(data.announcements);
        }
        if (data?.popup) {
          setActivePopup(data.popup);
        }
      })
      .catch(() => {});
  }, []);

  // Fetch 50 Manga per page
  const fetchCatalog = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await api.manga.browse({ page, per_page: 50, sort: "latest" });
      const items = Array.isArray(data?.items) ? data.items : [];
      setMangaList(items);
      if (data?.total) {
        setTotalManga(data.total);
      }
    } catch (err) {
      console.error("Homepage error:", err);
    } finally {
      setIsLoading(false);
    }
  }, [page]);

  useEffect(() => {
    fetchCatalog();
  }, [fetchCatalog]);

  // Dynamically sorted Most Viewed according to selected period
  const displayedMostViewed = useMemo(() => {
    const list = [...mangaList];
    if (mostViewedPeriod === "1d") {
      list.sort((a, b) => (b.daily_views || 0) - (a.daily_views || 0));
    } else if (mostViewedPeriod === "1w") {
      list.sort((a, b) => (b.weekly_views || 0) - (a.weekly_views || 0));
    } else {
      list.sort((a, b) => (b.monthly_views || 0) - (a.monthly_views || 0));
    }
    return list.slice(0, 15);
  }, [mangaList, mostViewedPeriod]);

  // Dynamically sorted New Releases (newly added first, stable tie-breaker)
  const displayedNewManga = useMemo(() => {
    return [...mangaList]
      .sort((a, b) => {
        const timeB = new Date(b.created_at || b.updated_at || 0).getTime();
        const timeA = new Date(a.created_at || a.updated_at || 0).getTime();
        if (timeB !== timeA) return timeB - timeA;
        return Number(b.id || 0) - Number(a.id || 0);
      })
      .slice(0, 15);
  }, [mangaList]);

  const filteredUpdates = mangaList.filter((m) => {
    if (filterType !== "All" && m.type?.toLowerCase() !== filterType.toLowerCase()) {
      return false;
    }
    return true;
  });

  const getCountryBadge = (country, type) => {
    const code = (country || (type === "manhwa" ? "KR" : type === "manhua" ? "CN" : "JP")).toUpperCase();
    return code;
  };

  // Add / Publish Notification
  const handlePublishBroadcast = async (e) => {
    e.preventDefault();
    if (!newNoticeText.trim()) return;

    const newId = Date.now();
    const newEntry = {
      id: newId,
      type: newNoticeType,
      text: newNoticeText.trim(),
      enabled: true,
    };

    setNotifications((prev) => [newEntry, ...prev]);

    if (isModalPopup) {
      setActivePopup({
        id: newId,
        title: "Announcement",
        message: newNoticeText.trim(),
        type: newNoticeType,
      });
    }

    try {
      await apiFetch("/api/v1/admin/broadcast", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: "Announcement",
          message: newNoticeText.trim(),
          type: newNoticeType,
          isPopup: isModalPopup,
        }),
      });
    } catch (err) {
      // Local fallback active
    }

    setNewNoticeText("");
    setIsModalPopup(false);
    setBroadcastModalOpen(false);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("notifications-updated"));
    }
  };

  // Delete notification
  const handleDeleteNotice = async (id) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    try {
      await apiFetch(`/api/v1/admin/announcements/${id}`, { method: "DELETE" });
    } catch (err) {}
  };

  // Save Header edits
  const handleSaveHeader = (e) => {
    e.preventDefault();
    setHeaderTitle(tempHeaderTitle);
    setHeaderSubtitle(tempHeaderSubtitle);
    localStorage.setItem("mgeko_header_title", tempHeaderTitle);
    localStorage.setItem("mgeko_header_subtitle", tempHeaderSubtitle);
    setEditHeaderModalOpen(false);
  };

  const totalPages = Math.max(1, Math.ceil(totalManga / 50));

  return (
    <div className="max-w-[1240px] mx-auto px-3 sm:px-4 py-3 space-y-6">
      <AdPlacement placement="homepage_top" className="homepage__ads" />
      <AdSection sectionKey="header_row_2" className="homepage__ads homepage__ads--top" fallback={null} />

      {/* Global Reader Modal Popup if active */}
      {activePopup && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/75 backdrop-blur-sm p-4">
          <div className="bg-[#15171c] border border-[#00AEF0] rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <span>📢</span>
                <span>{activePopup.title || "Announcement"}</span>
              </h3>
              <button
                type="button"
                onClick={() => setActivePopup(null)}
                className="text-gray-400 hover:text-white text-base"
              >
                ✕
              </button>
            </div>
            <div className="text-sm text-gray-200 leading-relaxed py-2">
              {activePopup.message}
            </div>
            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={() => setActivePopup(null)}
                className="px-4 py-2 bg-[#00AEF0] text-white text-xs font-bold rounded-lg hover:bg-[#0F5065] transition"
              >
                Got It
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header & Dynamic Notification Bar (Optimized for Mobile) */}
      <header className="mgeko-notice-header relative bg-[#15171c]/60 border border-[#262a33] rounded-xl sm:rounded-2xl p-2.5 sm:p-5 shadow-lg">
        {/* Admin Broadcast / Edit Controls */}
        {isUserAdmin && (
          <div className="absolute top-2.5 right-2.5 sm:top-3 sm:right-3 flex items-center gap-1.5 sm:gap-2">
            <button
              type="button"
              onClick={() => setBroadcastModalOpen(true)}
              className="bg-blue-600 hover:bg-blue-500 text-white text-[10px] sm:text-xs font-bold px-2 py-1 sm:px-3 sm:py-1.5 rounded-lg flex items-center gap-1 shadow-md transition"
              title="Admin Broadcast & Add Notification"
            >
              <span>📢</span>
              <span className="hidden sm:inline">Broadcast</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setTempHeaderTitle(headerTitle);
                setTempHeaderSubtitle(headerSubtitle);
                setEditHeaderModalOpen(true);
              }}
              className="bg-gray-800 hover:bg-gray-700 text-gray-300 text-[10px] sm:text-xs font-medium px-2 py-1 sm:px-2.5 sm:py-1.5 rounded-lg border border-gray-700 transition"
              title="Edit Section Title"
            >
              <i className="fas fa-pencil-alt"></i>
            </button>
          </div>
        )}

        <h1 className="text-sm sm:text-2xl font-bold sm:font-extrabold text-white tracking-wide pr-14 sm:pr-0">
          {headerTitle}
        </h1>
        {headerSubtitle && (
          <p className="text-[10px] sm:text-sm text-[#8b93a3] mt-0.5 sm:mt-1 max-w-2xl mx-auto line-clamp-1 sm:line-clamp-none">
            {headerSubtitle}
          </p>
        )}

        {/* Desktop / Tablet Notification List (Full View) */}
        <div className="hidden sm:block mt-3 sm:mt-4 space-y-2 max-w-2xl mx-auto text-xs sm:text-sm">
          {notifications.map((n) => {
            let styleClass = "";
            let prefix = "";

            if (n.type === "fix") {
              styleClass = "text-emerald-400 bg-emerald-950/40 border-emerald-800/60";
              prefix = "✅ Fix:";
            } else if (n.type === "solve") {
              styleClass = "text-cyan-400 bg-cyan-950/40 border-cyan-800/60";
              prefix = "💡 Solved:";
            } else if (n.type === "alert") {
              styleClass = "text-amber-400 bg-amber-950/40 border-amber-800/60";
              prefix = "⚠️ Alert:";
            } else if (n.type === "issue") {
              styleClass = "text-rose-400 bg-rose-950/40 border-rose-800/60";
              prefix = "🚨 Issue:";
            } else {
              styleClass = "text-blue-400 bg-blue-950/40 border-blue-800/60";
              prefix = "📢 Notice:";
            }

            return (
              <div
                key={n.id}
                className={`flex items-center justify-between border rounded-lg px-3 py-1.5 font-semibold transition ${styleClass}`}
              >
                <div className="flex items-center gap-1.5 text-left">
                  <span>{prefix}</span>
                  <span>{n.text}</span>
                </div>
                {isUserAdmin && (
                  <button
                    type="button"
                    onClick={() => handleDeleteNotice(n.id)}
                    className="ml-2 text-gray-400 hover:text-white text-xs px-1"
                    title="Delete notice"
                  >
                    ✕
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {/* Mobile-Optimized Compact Notification View */}
        <div className="block sm:hidden mt-2 space-y-1 text-[11px]">
          {(noticesExpandedMobile ? notifications : notifications.slice(0, 1)).map((n) => {
            let styleClass = "";
            let prefix = "";

            if (n.type === "fix") {
              styleClass = "text-emerald-400 bg-emerald-950/40 border-emerald-800/60";
              prefix = "✅";
            } else if (n.type === "solve") {
              styleClass = "text-cyan-400 bg-cyan-950/40 border-cyan-800/60";
              prefix = "💡";
            } else if (n.type === "alert") {
              styleClass = "text-amber-400 bg-amber-950/40 border-amber-800/60";
              prefix = "⚠️";
            } else if (n.type === "issue") {
              styleClass = "text-rose-400 bg-rose-950/40 border-rose-800/60";
              prefix = "🚨";
            } else {
              styleClass = "text-blue-400 bg-blue-950/40 border-blue-800/60";
              prefix = "📢";
            }

            return (
              <div
                key={n.id}
                className={`flex items-center justify-between border rounded-md px-2 py-1 font-medium transition ${styleClass}`}
              >
                <div className="flex items-center gap-1 text-left line-clamp-1 truncate">
                  <span>{prefix}</span>
                  <span className="truncate">{n.text}</span>
                </div>
                {isUserAdmin && (
                  <button
                    type="button"
                    onClick={() => handleDeleteNotice(n.id)}
                    className="ml-1 text-gray-400 hover:text-white text-[10px] px-1"
                  >
                    ✕
                  </button>
                )}
              </div>
            );
          })}

          {notifications.length > 1 && (
            <div className="text-center pt-0.5">
              <button
                type="button"
                onClick={() => setNoticesExpandedMobile(!noticesExpandedMobile)}
                className="text-[10px] text-[#00AEF0] hover:underline font-semibold"
              >
                {noticesExpandedMobile ? "▲ Show less" : `▼ View all notices (${notifications.length})`}
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Admin Broadcast Modal */}
      {broadcastModalOpen && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/75 p-4">
          <form
            onSubmit={handlePublishBroadcast}
            className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-lg w-full p-5 shadow-2xl space-y-4"
          >
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <span>📢</span>
                <span>Publish Admin Broadcast</span>
              </h3>
              <button
                type="button"
                onClick={() => setBroadcastModalOpen(false)}
                className="text-gray-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-bold text-gray-300 block mb-1">Notification Variety</label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {[
                    { key: "fix", label: "✅ Fix", color: "text-emerald-400 border-emerald-700" },
                    { key: "solve", label: "💡 Solve", color: "text-cyan-400 border-cyan-700" },
                    { key: "alert", label: "⚠️ Alert", color: "text-amber-400 border-amber-700" },
                    { key: "issue", label: "🚨 Issue", color: "text-rose-400 border-rose-700" },
                  ].map((v) => (
                    <button
                      key={v.key}
                      type="button"
                      onClick={() => setNewNoticeType(v.key)}
                      className={`p-2 rounded-lg border text-center font-bold transition ${
                        newNoticeType === v.key
                          ? "bg-blue-600/30 border-blue-500 text-white"
                          : `bg-[#1f2330] ${v.color} hover:bg-[#252a38]`
                      }`}
                    >
                      {v.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="font-bold text-gray-300 block mb-1">Notice / Message Text</label>
                <textarea
                  rows={3}
                  value={newNoticeText}
                  onChange={(e) => setNewNoticeText(e.target.value)}
                  placeholder="e.g. Scheduled maintenance complete, all chapters restored..."
                  className="w-full bg-[#1f2330] border border-[#374151] rounded-lg p-2.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0]"
                  required
                />
              </div>

              <div className="pt-1">
                <label className="flex items-center gap-2 cursor-pointer text-gray-300 font-semibold">
                  <input
                    type="checkbox"
                    checked={isModalPopup}
                    onChange={(e) => setIsModalPopup(e.target.checked)}
                    className="rounded bg-[#1f2330] border-gray-700 text-[#00AEF0]"
                  />
                  <span>Display also as a Global Pop-up Modal dialog</span>
                </label>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setBroadcastModalOpen(false)}
                className="px-3.5 py-1.5 rounded-lg bg-gray-800 text-gray-300 text-xs font-semibold hover:bg-gray-700"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 rounded-lg bg-[#00AEF0] text-white text-xs font-bold hover:bg-[#0F5065]"
              >
                Publish Broadcast
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Edit Header Title Modal */}
      {editHeaderModalOpen && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/75 p-4">
          <form
            onSubmit={handleSaveHeader}
            className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-md w-full p-5 shadow-2xl space-y-4"
          >
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <h3 className="text-base font-bold text-white">Edit Header Section</h3>
              <button
                type="button"
                onClick={() => setEditHeaderModalOpen(false)}
                className="text-gray-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-bold text-gray-300 block mb-1">Header Title</label>
                <input
                  type="text"
                  value={tempHeaderTitle}
                  onChange={(e) => setTempHeaderTitle(e.target.value)}
                  className="w-full bg-[#1f2330] border border-[#374151] rounded-lg p-2 text-xs text-white"
                  required
                />
              </div>

              <div>
                <label className="font-bold text-gray-300 block mb-1">Header Subtitle</label>
                <input
                  type="text"
                  value={tempHeaderSubtitle}
                  onChange={(e) => setTempHeaderSubtitle(e.target.value)}
                  className="w-full bg-[#1f2330] border border-[#374151] rounded-lg p-2 text-xs text-white"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setEditHeaderModalOpen(false)}
                className="px-3.5 py-1.5 rounded-lg bg-gray-800 text-gray-300 text-xs font-semibold hover:bg-gray-700"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 rounded-lg bg-[#00AEF0] text-white text-xs font-bold hover:bg-[#0F5065]"
              >
                Save Header
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Most Viewed Today Section (Circular Slide Carousel) */}
      <section className="mgeko-section">
        <div className="mgeko-section-header flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <h3>Most Viewed</h3>
            <div className="mgeko-period-selector">
              {["1d", "1w", "1m"].map((period) => (
                <button
                  key={period}
                  type="button"
                  onClick={() => setMostViewedPeriod(period)}
                  className={`mgeko-period-btn ${mostViewedPeriod === period ? "active" : ""}`}
                >
                  {period === "1d" ? "Today" : period === "1w" ? "Week" : "Month"}
                </button>
              ))}
            </div>
          </div>

          {/* Slider Navigation Buttons with Circular Loop */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setAutoSlideEnabled(!autoSlideEnabled)}
              className={`px-2 py-1 rounded-lg text-[10px] sm:text-xs font-semibold border transition flex items-center gap-1 ${
                autoSlideEnabled
                  ? "bg-[#00AEF0]/15 border-[#00AEF0] text-[#00AEF0]"
                  : "bg-[#15171c] border-[#262a33] text-gray-400 hover:text-white"
              }`}
              title="Toggle automatic circular rotation"
            >
              <i className={`fas fa-sync-alt ${autoSlideEnabled ? "animate-spin" : ""}`} style={{ animationDuration: "6s" }}></i>
              <span className="hidden sm:inline">Rotate</span>
            </button>
            <button
              type="button"
              onClick={() => handleCircularSlide("most-viewed-slider", "left")}
              className="w-7 h-7 rounded-full bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] hover:border-[#00AEF0] text-gray-300 hover:text-white flex items-center justify-center text-xs transition active:scale-90"
              title="Slide Left (Circular)"
            >
              <i className="fas fa-chevron-left"></i>
            </button>
            <button
              type="button"
              onClick={() => handleCircularSlide("most-viewed-slider", "right")}
              className="w-7 h-7 rounded-full bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] hover:border-[#00AEF0] text-gray-300 hover:text-white flex items-center justify-center text-xs transition active:scale-90"
              title="Slide Right (Circular)"
            >
              <i className="fas fa-chevron-right"></i>
            </button>
          </div>
        </div>

        {/* Horizontal Sliding Row with Smooth Pointer Drag-to-Scroll */}
        <div
          id="most-viewed-slider"
          onMouseEnter={() => setIsSliderHovered(true)}
          onMouseLeave={() => setIsSliderHovered(false)}
          {...mostViewedDrag.handlers}
          className={`flex items-stretch gap-2.5 sm:gap-3.5 overflow-x-auto scrollbar-none py-1 px-0.5 select-none ${
            mostViewedDrag.isDragging
              ? "cursor-grabbing scroll-auto snap-none"
              : "cursor-grab scroll-smooth snap-x snap-mandatory"
          }`}
        >
          {displayedMostViewed.map((manga, idx) => {
            const rank = idx + 1;
            const viewText =
              mostViewedPeriod === "1d"
                ? `${(manga.daily_views || 0).toLocaleString()} views today`
                : mostViewedPeriod === "1w"
                ? `${(manga.weekly_views || 0).toLocaleString()} views this week`
                : `${(manga.monthly_views || 0).toLocaleString()} views this month`;

            return (
              <Link
                key={manga.id}
                to={`/manga/${manga.id}`}
                draggable={false}
                className="comic-card group w-28 sm:w-36 md:w-44 flex-none snap-start shadow-md select-none relative"
              >
                <div className="comic-card__cover pointer-events-none relative">
                  <img
                    src={manga.cover_url || manga.cover_image}
                    alt={manga.title}
                    referrerPolicy="no-referrer"
                    loading="lazy"
                    draggable={false}
                  />
                  {/* Serial Rank Badge */}
                  <span
                    className={`absolute top-2 left-2 w-6 h-6 rounded-lg flex items-center justify-center text-xs font-black shadow-lg ${
                      rank === 1
                        ? "bg-amber-400 text-black shadow-amber-500/50"
                        : rank === 2
                        ? "bg-slate-300 text-black shadow-slate-400/50"
                        : rank === 3
                        ? "bg-amber-700 text-white shadow-amber-900/50"
                        : "bg-black/75 text-white border border-[#262a33]"
                    }`}
                  >
                    #{rank}
                  </span>

                  {manga.rating_count > 0 && manga.rating != null && (
                    <span className="mgeko-badge-score">
                      <i className="fas fa-star"></i>
                      <span>{Number(manga.rating).toFixed(1)}</span>
                    </span>
                  )}
                </div>
                <div className="p-1.5 sm:p-2 pointer-events-none space-y-0.5">
                  <h4 className="comic-card__title group-hover:text-[#00AEF0] transition text-[11px] sm:text-xs truncate">
                    {manga.title}
                  </h4>
                  <p className="text-[10px] text-[#00AEF0] font-semibold truncate">
                    {viewText}
                  </p>
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      {/* New Section (Circular Slide Carousel) */}
      <section className="mgeko-section">
        <div className="mgeko-section-header flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <h3>New Releases</h3>
            <Link to="/browse?sort=recently_added" className="text-xs text-[#00AEF0] hover:underline flex items-center gap-1 font-semibold ml-2">
              <span>View All</span> <i className="fas fa-chevron-right text-[9px]"></i>
            </Link>
          </div>

          {/* Slider Navigation Buttons with Circular Loop */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => handleCircularSlide("new-manga-slider", "left")}
              className="w-7 h-7 rounded-full bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] hover:border-[#00AEF0] text-gray-300 hover:text-white flex items-center justify-center text-xs transition active:scale-90"
              title="Slide Left (Circular)"
            >
              <i className="fas fa-chevron-left"></i>
            </button>
            <button
              type="button"
              onClick={() => handleCircularSlide("new-manga-slider", "right")}
              className="w-7 h-7 rounded-full bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] hover:border-[#00AEF0] text-gray-300 hover:text-white flex items-center justify-center text-xs transition active:scale-90"
              title="Slide Right (Circular)"
            >
              <i className="fas fa-chevron-right"></i>
            </button>
          </div>
        </div>

        {/* Horizontal Sliding Row with Smooth Pointer Drag-to-Scroll */}
        <div
          id="new-manga-slider"
          onMouseEnter={() => setIsSliderHovered(true)}
          onMouseLeave={() => setIsSliderHovered(false)}
          {...newMangaDrag.handlers}
          className={`flex items-stretch gap-2.5 sm:gap-3.5 overflow-x-auto scrollbar-none py-1 px-0.5 select-none ${
            newMangaDrag.isDragging
              ? "cursor-grabbing scroll-auto snap-none"
              : "cursor-grab scroll-smooth snap-x snap-mandatory"
          }`}
        >
          {displayedNewManga.map((manga) => (
            <Link
              key={manga.id}
              to={`/manga/${manga.id}`}
              draggable={false}
              className="comic-card group w-28 sm:w-36 md:w-44 flex-none snap-start shadow-md select-none"
            >
              <div className="comic-card__cover pointer-events-none">
                <img
                  src={manga.cover_url || manga.cover_image}
                  alt={manga.title}
                  referrerPolicy="no-referrer"
                  loading="lazy"
                  draggable={false}
                />
                <span className="mgeko-badge-status new">New</span>
              </div>
              <div className="p-1.5 sm:p-2 pointer-events-none">
                <h4 className="comic-card__title group-hover:text-[#00AEF0] transition text-[11px] sm:text-xs">
                  {manga.title}
                </h4>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* Latest Updates Section */}
      <section className="mgeko-section">
        {/* Controls Toolbar */}
        <div className="flex items-center justify-between flex-wrap gap-2 sm:gap-3 mb-3 sm:mb-4 pb-2 border-b border-[#262a33]">
          {/* Left: Latest Updates Title */}
          <div className="flex items-center gap-2">
            <h3 className="text-base sm:text-lg font-bold text-white flex items-center gap-1.5">
              <i className="fas fa-clock text-[#00AEF0] text-xs sm:text-sm"></i>
              <span>Latest Updates</span>
            </h3>
          </div>

          {/* Right: Pagination mini & Sorting dropdown */}
          <div className="flex items-center gap-2">
            {/* Mini pagination */}
            <div className="flex items-center bg-[#15171c] border border-[#262a33] rounded-lg px-2 py-1 text-xs">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                className="text-gray-400 hover:text-white disabled:opacity-30 px-1"
              >
                <i className="fas fa-chevron-left"></i>
              </button>
              <span className="px-1.5 font-bold text-white text-[11px] sm:text-xs">
                {page} <span className="text-gray-500 font-normal">/ {totalPages}</span>
              </span>
              <button
                type="button"
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
                className="text-gray-400 hover:text-white disabled:opacity-30 px-1"
              >
                <i className="fas fa-chevron-right"></i>
              </button>
            </div>

            {/* Sorting dropdown */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setSortDropdownOpen(!sortDropdownOpen)}
                className="bg-[#15171c] border border-[#262a33] text-gray-200 text-[11px] sm:text-xs px-2.5 py-1 sm:px-3 sm:py-1.5 rounded-lg font-medium flex items-center gap-1.5 hover:border-[#00AEF0] transition"
              >
                <span>{filterType}</span>
                <i className="fas fa-chevron-down text-[9px]"></i>
              </button>

              {sortDropdownOpen && (
                <div className="absolute right-0 mt-1 w-36 bg-[#1a1d28] border border-[#262a33] rounded-lg shadow-2xl z-30 py-1 text-xs">
                  {["All", "Manhua", "Manhwa", "Manga"].map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => {
                        setFilterType(t);
                        setSortDropdownOpen(false);
                      }}
                      className={`w-full text-left px-3 py-1.5 hover:bg-[#252a38] transition ${
                        filterType === t ? "text-[#00AEF0] font-bold" : "text-gray-300"
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Manga Updates Grid */}
        {isLoading ? (
          <div className="text-center py-16 text-gray-400 text-xs">Loading updates...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 sm:gap-3">
            {filteredUpdates.map((manga) => (
              <div key={manga.id} className="mgeko-update-card">
                <Link to={`/manga/${manga.id}`} className="mgeko-update-cover">
                  <img
                    src={manga.cover_url || manga.cover_image}
                    alt={manga.title}
                    referrerPolicy="no-referrer"
                    loading="lazy"
                  />
                  {manga.is_hot && (
                    <span className="mgeko-badge-status hot">Hot</span>
                  )}
                  {manga.rating_count > 0 && manga.rating != null && (
                    <span className="mgeko-badge-score">
                      <i className="fas fa-star"></i>
                      <span>{Number(manga.rating).toFixed(1)}</span>
                    </span>
                  )}
                </Link>

                <div className="mgeko-update-info">
                  <div>
                    <Link to={`/manga/${manga.id}`} className="mgeko-update-title" title={manga.title}>
                      {manga.title}
                    </Link>
                    {manga.latest_chapter_id ? (
                      <Link
                        to={`/reader/${manga.id}/${manga.latest_chapter_id}`}
                        className="mgeko-update-chapter"
                      >
                        {manga.last_chapter_title || "Latest chapter"}
                      </Link>
                    ) : (
                      <span className="mgeko-update-chapter opacity-60">No chapters yet</span>
                    )}
                  </div>

                  <div className="mgeko-update-meta">
                    <span className="flex items-center gap-1 font-mono text-[11px]" title={`Added at: ${formatGstTime(manga.created_at || manga.updated_at)}`}>
                      <i className="material-icons text-[11px]">update</i> {formatTimeAgo(manga.created_at || manga.updated_at || manga.last_scraped_at)}
                    </span>
                    <span className="mgeko-flag">
                      {getCountryBadge(manga.country, manga.type)}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Bottom Pagination */}
        <div className="flex items-center justify-center gap-2 mt-8">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => {
              setPage(page - 1);
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
            className="px-3 py-1.5 bg-[#15171c] border border-[#262a33] rounded-full text-xs font-semibold text-gray-300 disabled:opacity-30 hover:border-[#00AEF0] transition"
          >
            « Prev
          </button>
          {Array.from({ length: totalPages }).map((_, idx) => (
            <button
              key={idx + 1}
              type="button"
              onClick={() => {
                setPage(idx + 1);
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
              className={`px-3.5 py-1.5 rounded-full text-xs font-bold transition ${
                page === idx + 1
                  ? "bg-[#00AEF0] text-white"
                  : "bg-[#15171c] border border-[#262a33] text-gray-300 hover:border-[#00AEF0]"
              }`}
            >
              {idx + 1}
            </button>
          ))}
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => {
              setPage(page + 1);
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
            className="px-3 py-1.5 bg-[#15171c] border border-[#262a33] rounded-full text-xs font-semibold text-gray-300 disabled:opacity-30 hover:border-[#00AEF0] transition"
          >
            Next »
          </button>
        </div>
      </section>
    </div>
  );
}
