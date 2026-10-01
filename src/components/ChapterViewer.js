import { PAGE_PLACEHOLDER } from "../utils/placeholders";
import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useParams, Link, useNavigate } from "react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../services/api";
import ReaderOverlay from "./ReaderOverlay";
import OverlayScaleControl from "./OverlayScaleControl";
import AdSection from "./GlobalAds";
import AdPlacement from "./AdPlacement";
import CommentSection from "./CommentSection";
import useAuth from "../hooks/useAuth";
import useReaderSettings from "../hooks/useReaderSettings";
import useChapterTitles from "../hooks/useChapterTitles";
import { isBookmarked, recordRead, toggleBookmark as toggleLocalBookmark, useLibrary } from "../utils/library";
import "../fonts/overlayFonts";
import "./ChapterViewer.css";

const normalizePageImages = (page) => {
  if (!page) return [];
  if (Array.isArray(page)) return page.filter(Boolean);
  if (typeof page === "string") return [page];
  if (Array.isArray(page.images)) return page.images.filter(Boolean);
  if (Array.isArray(page.image_urls)) return page.image_urls.filter(Boolean);
  if (page.image_url) return [page.image_url];
  if (page.url) return [page.url];
  if (page.src) return [page.src];
  return [];
};

export default function ChapterViewer() {
  const { mangaId, chapterId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { isAdmin, isSecondaryAdmin, user: authUser } = useAuth();
  const isPrivileged = isAdmin || isSecondaryAdmin;

  // Page translation follows the reader's saved settings (Settings ->
  // Reading & Translation); there is no per-chapter toggle.
  const { settings: readerSettings, loaded: readerSettingsLoaded } = useReaderSettings({
    enabled: Boolean(authUser),
  });
  const showOcr = Boolean(authUser && readerSettingsLoaded && readerSettings.overlay_enabled);
  const chapterLabel = useChapterTitles(mangaId);
  const [overlayNotice, setOverlayNotice] = useState("");

  // Bookmark / Marked state
  const [toastMessage, setToastMessage] = useState("");

  // Like state
  const [liked, setLiked] = useState(false);
  const [likeClicked, setLikeClicked] = useState(false);

  // Admin rescrape controls
  const [deletePrev, setDeletePrev] = useState(false);
  const [rescrapeBusy, setRescrapeBusy] = useState(false);

  // Broken Chapter Report Modal state
  const [reportOpen, setReportOpen] = useState(false);
  const [reportType, setReportType] = useState("Broken Chapter");
  const [reportDetails, setReportDetails] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportSuccess, setReportSuccess] = useState(false);

  // Active Chapter Alerts Query
  const { data: chapterAlertsData, refetch: refetchAlerts } = useQuery({
    queryKey: ["chapterAlerts", chapterId],
    queryFn: () => api.reports.getChapterReports(chapterId),
    // Staff only: readers never see report status.
    enabled: !!chapterId && isPrivileged,
    refetchInterval: 10000,
  });
  const activeChapterAlert = chapterAlertsData?.active_alert;

  // Fetch chapter data
  const {
    data: chapter,
    isLoading: loading,
    error: queryError,
    refetch,
  } = useQuery({
    queryKey: ["chapter", mangaId, chapterId],
    queryFn: async () => {
      if (!chapterId) throw new Error("Chapter ID is missing.");
      const data = await api.manga.chapter(mangaId, chapterId);
      return data;
    },
    enabled: !!chapterId,
  });

  // Fetch all chapters for navigation dropdown
  const { data: allChaptersData } = useQuery({
    queryKey: ["chapters", mangaId],
    queryFn: () => api.manga.chapters(mangaId),
    enabled: !!mangaId,
  });

  const allChapters = useMemo(() => {
    if (Array.isArray(chapter?.all_chapters) && chapter.all_chapters.length > 0) {
      return chapter.all_chapters;
    }
    if (Array.isArray(allChaptersData)) {
      return allChaptersData;
    }
    return [];
  }, [chapter, allChaptersData]);

  // Bookmark (whole series) and read marks live in this browser.
  const lib = useLibrary();
  const bookmarked = isBookmarked(lib, mangaId);

  // Remember that THIS chapter was opened (only this one) and where we stopped.
  useEffect(() => {
    if (mangaId && chapterId && chapter) {
      recordRead(mangaId, chapterId, chapter.chapter_number);
    }
  }, [mangaId, chapterId, chapter]);

  const showToast = (msg) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(""), 3000);
  };

  // Flatten all page image URLs for vertical stream
  const allImages = useMemo(() => {
    if (!chapter?.pages || !Array.isArray(chapter.pages)) return [];
    const imgs = [];
    chapter.pages.forEach((p) => {
      const normalized = normalizePageImages(p);
      imgs.push(...normalized);
    });
    return imgs;
  }, [chapter]);

  // Next / Prev navigation calculation
  const currentChIndex = allChapters.findIndex((c) => String(c.id) === String(chapterId));
  const prevChapter = chapter?.prev_chapter_id
    ? allChapters.find((c) => String(c.id) === String(chapter.prev_chapter_id))
    : currentChIndex > 0
    ? allChapters[currentChIndex - 1]
    : null;

  const nextChapter = chapter?.next_chapter_id
    ? allChapters.find((c) => String(c.id) === String(chapter.next_chapter_id))
    : currentChIndex >= 0 && currentChIndex < allChapters.length - 1
    ? allChapters[currentChIndex + 1]
    : null;

  const handleBookmarkToggle = useCallback(() => {
    if (!mangaId) return;
    const now = toggleLocalBookmark(mangaId);
    showToast(now ? "Series bookmarked" : "Bookmark removed");
  }, [mangaId]);

  // Like chapter action
  const handleLike = async () => {
    setLikeClicked(true);
    setLiked(!liked);
    try {
      await api.manga.likeChapter(chapterId);
    } catch (err) {
      console.warn("Like failed", err);
    }
    setTimeout(() => setLikeClicked(false), 800);
  };

  // Report broken chapter submission
  const handleReportSubmit = async (e) => {
    if (e) e.preventDefault();
    if (reportSubmitting) return;
    setReportSubmitting(true);
    try {
      await api.manga.reportChapter(chapterId, {
        report_type: reportType,
        details: reportDetails.trim(),
      });
      setReportOpen(false);
      setReportDetails("");
      setReportSuccess(true);
      refetchAlerts();
      queryClient.invalidateQueries({ queryKey: ["chapterAlerts", chapterId] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      setTimeout(() => setReportSuccess(false), 4000);
    } catch (err) {
      console.error("Report failed", err);
      showToast("Failed to submit report. Please try again.");
    } finally {
      setReportSubmitting(false);
    }
  };

  // Admin Rescrape
  const handleRescrape = useCallback(async () => {
    if (!isPrivileged || !chapterId || rescrapeBusy) return;
    setRescrapeBusy(true);
    try {
      const res = await api.admin.rescrapeChapter(Number(chapterId), {
        delete_previous: deletePrev,
      });
      showToast(res?.message || "Chapter re-scraped successfully!");
      refetch();
    } catch (err) {
      console.error("Rescrape failed", err);
      showToast("Failed to re-scrape chapter.");
    } finally {
      setRescrapeBusy(false);
    }
  }, [chapterId, deletePrev, isPrivileged, rescrapeBusy, refetch]);

  // Admin Delete Page
  const handleDeletePage = async (pageIdx) => {
    if (!window.confirm(`Are you sure you want to delete Page ${pageIdx + 1}?`)) return;
    try {
      await api.admin.deleteChapterPage(Number(chapterId), pageIdx);
      showToast(`Page ${pageIdx + 1} deleted.`);
      refetch();
    } catch (err) {
      console.error("Delete page failed", err);
      showToast("Failed to delete page.");
    }
  };

  if (loading) {
    return (
      <div className="chapter-viewer-page flex flex-col items-center justify-center min-h-[60vh] space-y-3">
        <div className="w-10 h-10 border-4 border-[#00AEF0] border-t-transparent rounded-full animate-spin"></div>
        <p className="text-sm font-semibold text-gray-400">Loading chapter images…</p>
      </div>
    );
  }

  if (queryError || !chapter) {
    return (
      <div className="chapter-viewer-page max-w-xl mx-auto my-12 p-6 bg-[#15171c] border border-red-900/50 rounded-2xl text-center space-y-4 shadow-2xl">
        <div className="text-4xl text-red-500">⚠️</div>
        <h2 className="text-lg font-bold text-white">Chapter Load Error</h2>
        <p className="text-xs text-gray-400">{queryError?.message || "Chapter not available."}</p>
        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            type="button"
            onClick={() => refetch()}
            className="px-4 py-2 rounded-xl bg-[#00AEF0] text-white text-xs font-bold hover:bg-[#0F5065] transition"
          >
            Retry
          </button>
          <Link
            to={`/manga/${mangaId}`}
            className="px-4 py-2 rounded-xl bg-[#1f2330] text-gray-300 text-xs font-bold border border-[#262a33] hover:text-white transition"
          >
            Back to Manga
          </Link>
        </div>
      </div>
    );
  }

  const mangaTitle = chapter.manga?.title || `Manga #${mangaId}`;
  const chapterTitle = chapterLabel(chapter);

  return (
    <div className="chapter-viewer-page pb-16">
      {/* Toast Feedback */}
      {toastMessage && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-[#15171c] border border-[#00AEF0] text-white px-5 py-2.5 rounded-xl shadow-2xl text-xs font-bold flex items-center gap-2 animate-in fade-in slide-in-from-bottom-3">
          <i className="fas fa-check-circle text-[#00AEF0]"></i>
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Top Main Chapter Header (Template Coherent Style) */}
      <header className="chapter-header">
        <div className="content-wrap">
          <div className="titles">
            <h1>
              <Link to={`/manga/${mangaId}`} title={mangaTitle}>
                {mangaTitle}
              </Link>
            </h1>
            <h2>{chapterTitle}</h2>
          </div>

          <aside className="control-action">
            <nav className="action-items">
              <div className="action-select">
                <Link
                  to={prevChapter ? `/reader/${mangaId}/${prevChapter.id}` : "#"}
                  className={`chnav prev ${!prevChapter ? "isDisabled" : ""}`}
                  title={prevChapter ? `Go to ${chapterLabel(prevChapter)}` : "First chapter"}
                >
                  <i className="fas fa-chevron-left mr-1 text-[10px]"></i>
                  <span>Prev</span>
                </Link>

                <Link
                  to={nextChapter ? `/reader/${mangaId}/${nextChapter.id}` : "#"}
                  className={`chnav next ${!nextChapter ? "isDisabled" : ""}`}
                  title={nextChapter ? `Go to ${chapterLabel(nextChapter)}` : "Latest chapter"}
                >
                  <span>Next</span>
                  <i className="fas fa-chevron-right ml-1 text-[10px]"></i>
                </Link>
              </div>
            </nav>
          </aside>
        </div>
      </header>

      {/* Active Chapter Alert Banner */}
      {activeChapterAlert && (
        <div className="max-w-4xl mx-auto my-3 px-4">
          <div className="p-3.5 bg-rose-950/40 border border-rose-500/50 rounded-2xl flex items-center justify-between gap-3 text-xs shadow-lg animate-in fade-in">
            <div className="flex items-start sm:items-center gap-3">
              <div className="w-8 h-8 rounded-xl bg-rose-500/20 border border-rose-500/40 flex items-center justify-center text-sm flex-shrink-0">
                🚨
              </div>
              <div>
                <span className="font-bold text-white text-xs block">
                  Active Reader Alert: {activeChapterAlert.report_type}
                </span>
                <span className="text-gray-300 text-[11px] leading-relaxed">
                  {activeChapterAlert.details || "A reader reported an issue with this chapter. Our team is actively investigating and updating scans."}
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={() => refetch()}
              className="px-3 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 font-bold border border-rose-500/40 text-[11px] whitespace-nowrap transition flex items-center gap-1.5"
            >
              <i className="fas fa-sync-alt text-[10px]"></i>
              <span className="hidden sm:inline">Refresh Images</span>
            </button>
          </div>
        </div>
      )}

      {/* Top Banner Ad Placements */}
      <div className="max-w-4xl mx-auto my-3 px-4">
        <AdPlacement placement="chapter_top" className="chapter-viewer__ad-row" />
        <AdSection sectionKey="header_row_2" className="chapter-viewer__ad-row" fallback={null} />
      </div>

      {/* Top Chapter Navigator (Prev + Chapter Dropdown + Next) */}
      <div className="chapternav">
        <Link
          to={prevChapter ? `/reader/${mangaId}/${prevChapter.id}` : "#"}
          className={`prevchap ${!prevChapter ? "isDisabled" : ""}`}
        >
          <i className="fas fa-chevron-left text-[11px]"></i>
          <span>Prev</span>
        </Link>

        {allChapters.length > 0 && (
          <select
            value={chapterId}
            onChange={(e) => navigate(`/reader/${mangaId}/${e.target.value}`)}
            aria-label="Select Chapter"
          >
            {allChapters.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {chapterLabel(ch)}
              </option>
            ))}
          </select>
        )}

        <Link
          to={nextChapter ? `/reader/${mangaId}/${nextChapter.id}` : "#"}
          className={`nextchap ${!nextChapter ? "isDisabled" : ""}`}
        >
          <span>Next</span>
          <i className="fas fa-chevron-right text-[11px]"></i>
        </Link>
      </div>

      {/* Translation status (settings live in Settings -> Reading & Translation) */}
      <div className="max-w-4xl mx-auto my-3 px-4 flex items-center justify-between flex-wrap gap-3 bg-[#15171c] border border-[#262a33] p-3 rounded-xl shadow-lg">
        <div className="flex items-center gap-2 text-xs text-gray-300 flex-wrap">
          <i className="fas fa-language text-[#00AEF0]"></i>
          {!authUser ? (
            <span>
              <Link to="/login" className="text-[#00AEF0] hover:underline font-semibold">Sign in</Link> to translate pages automatically.
            </span>
          ) : showOcr ? (
            <span>
              Auto-translate is <span className="text-emerald-400 font-bold">on</span> ({(readerSettings.target_language || "en").toUpperCase()}).
            </span>
          ) : (
            <span>
              Auto-translate is <span className="text-gray-400 font-bold">off</span>.
            </span>
          )}
          {authUser && (
            <Link to="/settings?tab=reading" className="text-[#00AEF0] hover:underline font-semibold">
              Change in Settings
            </Link>
          )}
        </div>
        {showOcr && <OverlayScaleControl />}
        {overlayNotice && (
          <div className="w-full text-[11px] text-amber-300 bg-amber-950/30 border border-amber-500/30 rounded-lg px-3 py-2 flex items-center justify-between gap-2">
            <span>{overlayNotice}</span>
            <button type="button" onClick={() => setOverlayNotice("")} className="text-gray-400 hover:text-white" aria-label="Dismiss">
              ✕
            </button>
          </div>
        )}
      </div>

      {/* Admin and sub-admin only: never rendered for readers */}
      {isPrivileged && (
        <div className="max-w-4xl mx-auto mb-3 px-4 flex items-center justify-end flex-wrap gap-3 bg-[#15171c] border border-amber-500/20 p-3 rounded-xl">
          <span className="mr-auto text-[11px] font-bold text-amber-300 flex items-center gap-1.5">
            <i className="fas fa-user-shield"></i> Staff tools
          </span>
          <label className="flex items-center gap-1.5 text-[11px] text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              checked={deletePrev}
              onChange={(e) => setDeletePrev(e.target.checked)}
              disabled={rescrapeBusy}
              className="rounded bg-[#101216] border-[#262a33]"
            />
            <span>Delete existing pages</span>
          </label>
          <button
            type="button"
            onClick={handleRescrape}
            disabled={rescrapeBusy}
            className="px-3.5 py-1.5 rounded-lg bg-[#00AEF0] hover:bg-[#0F5065] text-white text-xs font-bold flex items-center gap-1.5 shadow transition disabled:opacity-50"
          >
            <i className={`fas fa-sync-alt ${rescrapeBusy ? "animate-spin" : ""}`}></i>
            <span>{rescrapeBusy ? "Re-scraping…" : "Re-Scrape Chapter"}</span>
          </button>
        </div>
      )}

      {/* Main Chapter Reader Container (Vertical continuous stream with no gaps) */}
      <section className="my-4 px-2 sm:px-4">
        <div id="chapter-reader">
          {allImages.length === 0 ? (
            <div className="p-12 text-center text-xs text-gray-500">
              No images found in this chapter.
            </div>
          ) : (
            allImages.map((imgUrl, idx) => (
              <div key={idx} className="chapter-page-item group relative">
                <img
                  src={imgUrl}
                  alt={`Chapter Page ${idx + 1}`}
                  id={`image-${idx + 1}`}
                  referrerPolicy="no-referrer"
                  loading="lazy"
                  decoding="async"
                  onError={(e) => {
                    e.currentTarget.onerror = null;
                    e.currentTarget.src = PAGE_PLACEHOLDER;
                  }}
                />

                {/* OCR overlay per image if enabled */}
                {showOcr && (
                  <ReaderOverlay
                    imageUrl={imgUrl}
                    chapterId={chapterId}
                    pageIndex={idx}
                    settings={readerSettings}
                    translatable={chapter?.may_translate !== false}
                    onLimitReached={() =>
                      setOverlayNotice(
                        "You've reached your translation limit for this period. Raise it in Settings → Reading & Translation."
                      )
                    }
                    onError={(code) =>
                      setOverlayNotice(
                        code === "untranslated"
                          ? "Text was found but not translated: no translator is set up. Add a free AI key in Settings → AI & OCR Engines."
                          : code === 403 || code === 401
                          ? "Translation needs you to be signed in."
                          : "Some pages could not be translated right now."
                      )
                    }
                  />
                )}

                {/* Page indicator & Admin page delete button */}
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1.5 bg-black/75 px-2 py-1 rounded-md text-[10px] font-bold text-white z-20">
                  <span>Page {idx + 1}</span>
                  {isPrivileged && (
                    <button
                      type="button"
                      onClick={() => handleDeletePage(idx)}
                      className="ml-1 text-red-400 hover:text-red-300 hover:underline"
                      title={`Delete Page ${idx + 1}`}
                    >
                      <i className="fas fa-trash-alt"></i> Delete
                    </button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      {/* Bottom Chapter Navigator (Prev + Chapter Dropdown + Next) */}
      <div className="chapternav mt-6">
        <Link
          to={prevChapter ? `/reader/${mangaId}/${prevChapter.id}` : "#"}
          className={`prevchap ${!prevChapter ? "isDisabled" : ""}`}
        >
          <i className="fas fa-chevron-left text-[11px]"></i>
          <span>Prev</span>
        </Link>

        {allChapters.length > 0 && (
          <select
            value={chapterId}
            onChange={(e) => navigate(`/reader/${mangaId}/${e.target.value}`)}
            aria-label="Select Chapter Bottom"
          >
            {allChapters.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {chapterLabel(ch)}
              </option>
            ))}
          </select>
        )}

        <Link
          to={nextChapter ? `/reader/${mangaId}/${nextChapter.id}` : "#"}
          className={`nextchap ${!nextChapter ? "isDisabled" : ""}`}
        >
          <span>Next</span>
          <i className="fas fa-chevron-right text-[11px]"></i>
        </Link>
      </div>

      {/* Chapter Mini Actions Bar (Back to Manga, Home, Report Issue) */}
      <div id="chapter-mini-actions" className="flex items-center justify-center gap-2 sm:gap-3 py-4 px-2 max-w-xl mx-auto flex-nowrap overflow-x-auto">
        <Link
          to={`/manga/${mangaId}`}
          className="navChapter px-3 py-1.5 text-xs rounded-lg flex items-center gap-1.5 whitespace-nowrap flex-shrink-0"
          title="Back to Manga Overview"
        >
          <i className="fas fa-angle-double-left text-xs"></i>
          <span className="text-xs">Overview</span>
        </Link>

        <Link
          to="/"
          className="navChapter px-3 py-1.5 text-xs rounded-lg flex items-center gap-1.5 whitespace-nowrap flex-shrink-0"
          title="Homepage"
        >
          <i className="fas fa-home text-xs"></i>
          <span className="text-xs">Home</span>
        </Link>

        <button
          type="button"
          onClick={() => setReportOpen(true)}
          className="reportBtn px-3 py-1.5 text-xs rounded-lg flex items-center gap-1.5 whitespace-nowrap flex-shrink-0"
          title="Report broken images or chapter issues"
        >
          <i className="fas fa-bug text-xs"></i>
          <span className="text-xs">Report</span>
        </button>
      </div>

      {/* Broken Chapter Report Modal */}
      {reportOpen && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <form onSubmit={handleReportSubmit} className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-rose-500/20 border border-rose-500/30 flex items-center justify-center text-sm">
                  🚨
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">Report Chapter Issue</h3>
                  <p className="text-[11px] text-[#8b93a3]">Notify the scan team and trigger an active reader alert</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setReportOpen(false)}
                className="text-gray-400 hover:text-white text-sm p-1 rounded-lg hover:bg-[#262a33]"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-gray-300 block mb-1.5">What is the problem?</label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {[
                    { val: "Broken Chapter", label: "Broken Chapter", icon: "🚨", desc: "Blank / failed to load" },
                    { val: "Wrong Chapter", label: "Wrong Chapter", icon: "🔄", desc: "Out of order / wrong manga" },
                    { val: "Missing Images", label: "Missing Images", icon: "🖼️", desc: "Pages cut off or skipped" },
                    { val: "Missing Text", label: "Missing Text", icon: "📝", desc: "Untranslated / empty bubbles" },
                    { val: "Slow Loading", label: "Slow Loading", icon: "⏳", desc: "CDN connection delay" },
                  ].map((opt) => (
                    <button
                      key={opt.val}
                      type="button"
                      onClick={() => setReportType(opt.val)}
                      className={`p-2.5 rounded-xl border text-left transition flex items-start gap-2 ${
                        reportType === opt.val
                          ? "bg-[#00AEF0]/15 border-[#00AEF0] text-white ring-1 ring-[#00AEF0]"
                          : "bg-[#101216] border-[#262a33] text-gray-400 hover:text-white hover:border-gray-600"
                      }`}
                    >
                      <span className="text-base">{opt.icon}</span>
                      <div>
                        <span className="text-xs font-bold text-white block">{opt.label}</span>
                        <span className="text-[10px] text-[#8b93a3]">{opt.desc}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-gray-300 block mb-1.5">
                  Additional Details (Optional)
                </label>
                <textarea
                  rows={3}
                  value={reportDetails}
                  onChange={(e) => setReportDetails(e.target.value)}
                  placeholder="e.g., Page 3 is blank, dialogue in speech bubble #2 is missing, wrong chapter number..."
                  className="w-full p-3 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0] resize-none"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setReportOpen(false)}
                className="px-4 py-2 rounded-xl bg-[#1f2330] text-gray-300 text-xs font-bold hover:text-white transition"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={reportSubmitting}
                className="px-5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white text-xs font-bold shadow-lg transition flex items-center gap-1.5 disabled:opacity-50"
              >
                {reportSubmitting ? (
                  <span>Submitting…</span>
                ) : (
                  <>
                    <i className="fas fa-paper-plane text-[10px]"></i>
                    <span>Submit &amp; Alert Team</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      )}

      {reportSuccess && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-[#15171c] border border-emerald-500 text-emerald-400 px-5 py-3 rounded-2xl shadow-2xl text-xs font-bold flex items-center gap-2.5 animate-in fade-in slide-in-from-bottom-4">
          <i className="fas fa-check-circle text-base"></i>
          <div>
            <span className="block text-white">Report Submitted Successfully!</span>
            <span className="text-[11px] text-emerald-400 font-normal">A reader alert and notification have been dispatched.</span>
          </div>
        </div>
      )}

      {/* Bottom Ad Placements */}
      <div className="max-w-4xl mx-auto my-6 px-4">
        <AdPlacement placement="chapter_bottom" className="chapter-viewer__ad-row" />
        <AdSection sectionKey="footer_row_1" className="chapter-viewer__ad-row" fallback={null} />
        <AdSection sectionKey="footer_row_2" className="chapter-viewer__ad-row" fallback={null} />
      </div>

      {/* Comments Section */}
      <div className="max-w-4xl mx-auto mt-8 px-4">
        <CommentSection targetType="chapter" targetId={Number(chapterId)} />
      </div>
    </div>
  );
}
