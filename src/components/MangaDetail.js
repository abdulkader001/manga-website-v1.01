import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useParams, Link } from "react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../services/api";
import CommentSection from "./CommentSection";
import "../styles/components.css";

const MangaDetail = () => {
  const { mangaId } = useParams();
  const queryClient = useQueryClient();
  const [bookmarked, setBookmarked] = useState(false);
  const [hoverRating, setHoverRating] = useState(0);
  const [ratingMessage, setRatingMessage] = useState("");

  // Chapter display controls
  const [chapterSort, setChapterSort] = useState("newest"); // "newest" | "oldest"
  const [chapterSearch, setChapterSearch] = useState("");
  const [viewMode, setViewMode] = useState(() => {
    try {
      return localStorage.getItem("manga_chapter_view_mode") || "grid";
    } catch {
      return "grid";
    }
  });

  const handleSetViewMode = (mode) => {
    setViewMode(mode);
    try {
      localStorage.setItem("manga_chapter_view_mode", mode);
    } catch {}
  };

  const { data: manga, isLoading: isMangaLoading, error: mangaError } = useQuery({
    queryKey: ["manga", mangaId],
    queryFn: () => api.manga.detail(mangaId),
    enabled: !!mangaId,
  });

  const { data: chaptersData, isLoading: isChaptersLoading } = useQuery({
    queryKey: ["chapters", mangaId],
    queryFn: () => api.manga.chapters(mangaId),
    enabled: !!mangaId,
  });

  const rawChapters = Array.isArray(chaptersData) ? chaptersData : (manga?.chapters || []);

  // Sort and filter chapters according to user selection
  const sortedChapters = useMemo(() => {
    const list = [...rawChapters].sort((a, b) => {
      const numA = typeof a.chapter_number === "number" ? a.chapter_number : Number(a.id || 0);
      const numB = typeof b.chapter_number === "number" ? b.chapter_number : Number(b.id || 0);
      return chapterSort === "newest" ? numB - numA : numA - numB;
    });

    if (!chapterSearch.trim()) return list;
    const query = chapterSearch.toLowerCase();
    return list.filter(
      (c) =>
        String(c.chapter_number || "").includes(query) ||
        String(c.title || "").toLowerCase().includes(query)
    );
  }, [rawChapters, chapterSort, chapterSearch]);

  const { data: bookmarks } = useQuery({
    queryKey: ["bookmarks"],
    queryFn: () => api.bookmarks.list(),
  });

  const { data: historyData } = useQuery({
    queryKey: ["history"],
    queryFn: () => api.history.list(),
  });

  const history = Array.isArray(historyData) ? historyData : [];

  useEffect(() => {
    if (bookmarks && mangaId) {
      setBookmarked(Array.isArray(bookmarks) && bookmarks.some((b) => String(b.manga_id) === String(mangaId)));
    }
  }, [bookmarks, mangaId]);

  const rateMutation = useMutation({
    mutationFn: (score) => api.manga.rate(mangaId, score),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["manga", mangaId] });
      setRatingMessage(data.message || `You rated ${data.user_rating} / 10!`);
      setTimeout(() => setRatingMessage(""), 4000);
    },
    onError: () => {
      setRatingMessage("Failed to submit rating. Please try again.");
    },
  });

  const handleRate = (score) => {
    rateMutation.mutate(score);
  };

  // Determine user history for this manga safely before conditional returns
  const userHistoryForManga = useMemo(() => {
    return history.filter((h) => String(h.manga_id) === String(mangaId));
  }, [history, mangaId]);

  // Load local read chapters from localStorage to guarantee instant 100% offline & session resilience
  const localReadData = useMemo(() => {
    try {
      const stored = localStorage.getItem(`manga_read_chapters_${mangaId}`);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  }, [mangaId]);

  // Find the maximum read chapter number across both server history and local history
  const maxReadChapterNumber = useMemo(() => {
    let maxNum = -1;
    userHistoryForManga.forEach((h) => {
      const ch = rawChapters.find((c) => Number(c.id) === Number(h.chapter_id));
      const chNum = ch ? parseFloat(ch.chapter_number) : parseFloat(h.chapter_number || h.chapter_id);
      if (!isNaN(chNum) && chNum > maxNum) maxNum = chNum;
    });
    localReadData.forEach((item) => {
      const num = parseFloat(item?.chapter_number || item);
      if (!isNaN(num) && num > maxNum) maxNum = num;
    });
    try {
      const maxStored = parseFloat(localStorage.getItem(`manga_max_read_${mangaId}`));
      if (!isNaN(maxStored) && maxStored > maxNum) maxNum = maxStored;
    } catch {}
    return maxNum;
  }, [userHistoryForManga, localReadData, rawChapters, mangaId]);

  // If chapter 45 is read, all downward chapters (<= 45) turn blue!
  const isChapterRead = useCallback(
    (ch) => {
      if (!ch) return false;
      const chId = Number(ch.id);
      const chNum = parseFloat(ch.chapter_number);

      // 1. Direct match in server history
      if (history.some((h) => Number(h.chapter_id) === chId || (Number(h.manga_id) === Number(mangaId) && parseFloat(h.chapter_number) === chNum))) return true;
      // 2. Direct match in local storage
      if (localReadData.some((item) => Number(item) === chId || String(item) === String(ch.chapter_number) || Number(item?.chapter_id) === chId)) return true;
      // 3. User requirement: if chapter 45 is read, all downward chapters (<= 45) must turn blue
      if (!isNaN(chNum) && maxReadChapterNumber > 0 && chNum <= maxReadChapterNumber) {
        return true;
      }
      return false;
    },
    [history, localReadData, maxReadChapterNumber, mangaId]
  );

  const loading = isMangaLoading || isChaptersLoading;
  const error = !mangaId ? "Manga ID is missing." : mangaError ? "Failed to load manga details." : "";

  async function toggleBookmark() {
    try {
      if (bookmarked) {
        await api.bookmarks.remove(mangaId);
        setBookmarked(false);
      } else {
        await api.bookmarks.add(mangaId);
        setBookmarked(true);
      }
      queryClient.invalidateQueries({ queryKey: ["bookmarks"] });
    } catch (err) {
      console.error("Bookmark toggle failed:", err);
    }
  }

  if (loading) return <div className="p-8 text-center text-[#8b93a3]">Loading manga details…</div>;
  if (error) return <div className="p-8 text-center text-red-400">{error}</div>;
  if (!manga) return <div className="p-8 text-center text-[#8b93a3]">Manga not found.</div>;

  const cover = manga.cover_url || manga.cover_image;

  // Determine last read chapter for this manga
  const getHistoryTimestamp = (entry) =>
    new Date(
      entry?.last_read_at || entry?.viewed_at || entry?.updated_at || entry?.created_at || 0
    ).getTime();

  const lastRead = userHistoryForManga.reduce((acc, h) => {
    const ts = getHistoryTimestamp(h);
    const accTs = getHistoryTimestamp(acc);
    return ts > accTs ? h : acc;
  }, null);

  // Compute combined total views across all chapters
  const computedTotalViews = rawChapters.reduce((sum, ch) => sum + (ch.views || 0), 0);
  const totalViews = manga.views || computedTotalViews || 0;
  const formattedTotalViews = manga.views_formatted || (totalViews >= 1000 ? `${(totalViews / 1000).toFixed(1).replace(/\.0$/, "")}k` : String(totalViews));

  // Hot Indicator: ONLY if explicitly marked is_hot by admin or actual high viewership
  const isHotManga = Boolean(manga.is_hot || totalViews >= 25000);

  // Current rating out of 10 (starts from 0 if no votes)
  const currentRating = typeof manga.rating === "number" ? manga.rating : 0;
  const ratingCount = manga.rating_count || 0;
  const userRating = manga.user_rating || null;

  // Newest and first chapter for direct links
  const newestChapter = rawChapters.length > 0
    ? [...rawChapters].sort((a, b) => (Number(b.chapter_number || b.id || 0) - Number(a.chapter_number || a.id || 0)))[0]
    : null;
  const firstChapter = rawChapters.length > 0
    ? [...rawChapters].sort((a, b) => (Number(a.chapter_number || a.id || 0) - Number(b.chapter_number || b.id || 0)))[0]
    : null;

  return (
    <div className="manga-detail p-4 sm:p-6 max-w-6xl mx-auto space-y-8">
      {/* --- Header Banner & Information Card --- */}
      <div className="flex flex-col md:flex-row gap-6 bg-[#15171c] border border-[#262a33] p-5 sm:p-6 rounded-2xl shadow-xl">
        {cover && (
          <div className="flex-none mx-auto md:mx-0">
            <img
              src={cover}
              alt={`${manga.title} Cover`}
              className="w-48 sm:w-56 h-72 sm:h-80 object-cover rounded-xl shadow-2xl border border-[#262a33]"
              referrerPolicy="no-referrer"
              decoding="async"
              onError={(e) => {
                e.currentTarget.src = "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600&auto=format&fit=crop&q=80";
              }}
            />
          </div>
        )}

        <div className="flex-1 flex flex-col justify-between space-y-4">
          <div>
            {/* Meta Badges: Type, Status, Total Views, Rating, Hot */}
            <div className="flex items-center gap-2 flex-wrap mb-2">
              {isHotManga && (
                <span className="px-2.5 py-0.5 rounded-full text-[11px] font-extrabold uppercase bg-red-600 text-white shadow-[0_0_10px_rgba(220,38,38,0.5)] flex items-center gap-1 animate-pulse">
                  <span>🔥</span>
                  <span>HOT</span>
                </span>
              )}
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-extrabold uppercase bg-[#00AEF0]/15 text-[#00AEF0] border border-[#00AEF0]/30">
                {manga.type || "Manga"}
              </span>
              <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold border capitalize ${
                (manga.status || "").toLowerCase().includes("complete")
                  ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                  : (manga.status || "").toLowerCase().includes("hiatus")
                  ? "bg-amber-500/15 text-amber-400 border-amber-500/30"
                  : "bg-blue-500/15 text-blue-400 border-blue-500/30"
              }`}>
                {manga.status || "Ongoing"}
              </span>
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 flex items-center gap-1">
                <i className="fas fa-eye text-[10px]"></i>
                <span>{formattedTotalViews} Total Views</span>
              </span>
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-purple-500/15 text-purple-300 border border-purple-500/30 flex items-center gap-1">
                <i className="fas fa-star text-[10px]"></i>
                <span>{currentRating > 0 ? `${currentRating.toFixed(1)} / 10` : "0.0 / 10"}</span>
              </span>
            </div>

            <h1 className="text-2xl sm:text-3xl font-extrabold text-white mb-2">{manga.title}</h1>

            {/* Summary / Story Description directly on the card */}
            {manga.description && (
              <p className="text-xs sm:text-sm text-gray-300 leading-relaxed mb-3 line-clamp-4">
                {manga.description}
              </p>
            )}

            {/* Clickable Genre Links */}
            {manga.genres && (
              <div className="flex items-center gap-1.5 flex-wrap text-xs text-[#8b93a3] mb-4">
                <span className="font-semibold text-gray-400">Genres:</span>
                {(Array.isArray(manga.genres) ? manga.genres : [manga.genres]).map((g, idx) => (
                  <Link
                    key={idx}
                    to={`/browse?genre=${encodeURIComponent(g)}`}
                    className="px-2.5 py-1 rounded-lg bg-[#101216] border border-[#262a33] text-gray-300 hover:text-[#00AEF0] hover:border-[#00AEF0] hover:bg-[#00AEF0]/10 transition font-semibold"
                  >
                    {g}
                  </Link>
                ))}
              </div>
            )}

            {/* 1 to 10 Interactive Rating Box */}
            <div className="p-3 rounded-xl bg-[#101216] border border-[#262a33] space-y-1.5">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-lg text-amber-400 font-extrabold flex items-center gap-1">
                    <i className="fas fa-star text-sm"></i>
                    <span>{currentRating > 0 ? currentRating.toFixed(1) : "0.0"}</span>
                  </span>
                  <span className="text-xs text-gray-400 font-medium">/ 10</span>
                  <span className="text-xs text-[#8b93a3]">
                    ({ratingCount} {ratingCount === 1 ? "rating" : "ratings"})
                  </span>
                </div>

                {userRating && (
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                    Your rating: {userRating} / 10
                  </span>
                )}
              </div>

              <div className="flex items-center gap-1 sm:gap-1.5 flex-wrap pt-0.5">
                <span className="text-[11px] font-bold text-[#8b93a3] mr-1">Rate:</span>
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((star) => {
                  const isActive = (hoverRating || userRating || 0) >= star;
                  return (
                    <button
                      key={star}
                      type="button"
                      disabled={rateMutation.isLoading}
                      onMouseEnter={() => setHoverRating(star)}
                      onMouseLeave={() => setHoverRating(0)}
                      onClick={() => handleRate(star)}
                      className={`w-7 h-7 sm:w-8 sm:h-8 rounded-lg text-xs font-extrabold flex items-center justify-center transition ${
                        isActive
                          ? "bg-amber-400 text-black shadow-md scale-105"
                          : "bg-[#1f2330] text-gray-400 border border-[#262a33] hover:text-white hover:border-amber-400"
                      }`}
                      title={`Rate ${star} / 10`}
                    >
                      {star}
                    </button>
                  );
                })}
              </div>

              {ratingMessage && (
                <p className="text-xs font-semibold text-emerald-400 pt-1 animate-in fade-in">
                  {ratingMessage}
                </p>
              )}
            </div>
          </div>

          {/* Action Buttons: Bookmark & Reading Entry Points */}
          <div className="pt-2 flex items-center gap-3 flex-wrap">
            <button
              onClick={toggleBookmark}
              className={`px-5 py-2.5 rounded-xl font-bold text-xs sm:text-sm flex items-center gap-2 shadow-lg transition ${
                bookmarked
                  ? "bg-red-500/20 border border-red-500 text-red-400 hover:bg-red-500/30"
                  : "bg-[#00AEF0] hover:bg-[#0F5065] text-white"
              }`}
            >
              <i className={bookmarked ? "fas fa-bookmark" : "far fa-bookmark"}></i>
              <span>{bookmarked ? "Bookmarked" : "Add to Bookmarks"}</span>
            </button>

            {lastRead ? (
              <Link
                to={`/reader/${mangaId}/${lastRead.chapter_id}`}
                className="px-5 py-2.5 rounded-xl font-bold text-xs sm:text-sm bg-purple-600 hover:bg-purple-700 text-white flex items-center gap-2 shadow-lg transition"
                title="Continue from your last read chapter"
              >
                <i className="fas fa-play"></i>
                <span>Continue Reading ({lastRead.chapter_title || `Ch. ${lastRead.chapter_id % 100 || lastRead.chapter_id}`})</span>
              </Link>
            ) : newestChapter ? (
              <Link
                to={`/reader/${mangaId}/${newestChapter.id}`}
                className="px-5 py-2.5 rounded-xl font-bold text-xs sm:text-sm bg-[#00AEF0] hover:bg-[#0F5065] text-white flex items-center gap-2 shadow-lg transition"
              >
                <i className="fas fa-book-open"></i>
                <span>Read Latest (Ch. {newestChapter.chapter_number || newestChapter.id})</span>
              </Link>
            ) : null}

            {firstChapter && !lastRead && (
              <Link
                to={`/reader/${mangaId}/${firstChapter.id}`}
                className="px-4 py-2.5 rounded-xl font-bold text-xs sm:text-sm bg-[#1f2330] hover:bg-[#252a38] text-gray-200 hover:text-white border border-[#262a33] flex items-center gap-2 transition"
              >
                <i className="fas fa-step-forward"></i>
                <span>First Chapter</span>
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* --- Chapters Section (With Grid/List interchange & Sequence Sort) --- */}
      <div className="bg-[#15171c] border border-[#262a33] p-5 sm:p-6 rounded-2xl shadow-xl space-y-4">
        {/* Chapters Section Header & Controls */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-[#262a33] pb-4">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <i className="fas fa-list text-[#00AEF0]"></i>
              <span>Chapters ({rawChapters.length})</span>
            </h2>
            <p className="text-xs text-[#8b93a3] mt-0.5">
              {formattedTotalViews} cumulative reads across all releases
            </p>
          </div>

          {/* Controls: Search, Sort Sequence, Grid/List Toggle */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Chapter Search Filter */}
            <div className="relative">
              <input
                type="text"
                value={chapterSearch}
                onChange={(e) => setChapterSearch(e.target.value)}
                placeholder="Search chapter..."
                className="px-3 py-1.5 pl-8 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0] w-36 sm:w-44"
              />
              <i className="fas fa-search absolute left-2.5 top-2.5 text-[11px] text-gray-500"></i>
            </div>

            {/* Sequence Sort: Newest to Oldest vs Oldest to Newest */}
            <div className="flex items-center bg-[#101216] border border-[#262a33] rounded-xl p-0.5">
              <button
                type="button"
                onClick={() => setChapterSort("newest")}
                className={`px-3 py-1 rounded-lg text-xs font-bold transition flex items-center gap-1 ${
                  chapterSort === "newest"
                    ? "bg-[#00AEF0] text-white shadow"
                    : "text-gray-400 hover:text-white"
                }`}
                title="Sort Newest to Oldest"
              >
                <i className="fas fa-sort-amount-down text-[10px]"></i>
                <span>Newest</span>
              </button>
              <button
                type="button"
                onClick={() => setChapterSort("oldest")}
                className={`px-3 py-1 rounded-lg text-xs font-bold transition flex items-center gap-1 ${
                  chapterSort === "oldest"
                    ? "bg-[#00AEF0] text-white shadow"
                    : "text-gray-400 hover:text-white"
                }`}
                title="Sort Oldest to Newest"
              >
                <i className="fas fa-sort-amount-up text-[10px]"></i>
                <span>Oldest</span>
              </button>
            </div>

            {/* Grid / List Interchange Toggle */}
            <div className="flex items-center bg-[#101216] border border-[#262a33] rounded-xl p-0.5">
              <button
                type="button"
                onClick={() => handleSetViewMode("grid")}
                className={`p-1.5 rounded-lg text-xs transition ${
                  viewMode === "grid"
                    ? "bg-[#00AEF0] text-white"
                    : "text-gray-400 hover:text-white"
                }`}
                title="Grid view"
              >
                <i className="fas fa-th"></i>
              </button>
              <button
                type="button"
                onClick={() => handleSetViewMode("list")}
                className={`p-1.5 rounded-lg text-xs transition ${
                  viewMode === "list"
                    ? "bg-[#00AEF0] text-white"
                    : "text-gray-400 hover:text-white"
                }`}
                title="List view"
              >
                <i className="fas fa-list"></i>
              </button>
            </div>
          </div>
        </div>

        {/* Chapters Listing */}
        {sortedChapters.length > 0 ? (
          viewMode === "grid" ? (
            /* --- Grid View --- */
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
              {sortedChapters.map((ch) => {
                const read = isChapterRead(ch);
                const chapterViews = ch.views || 0;
                const formattedChapterViews =
                  ch.views_formatted ||
                  (chapterViews >= 1000
                    ? `${(chapterViews / 1000).toFixed(1).replace(/\.0$/, "")}k`
                    : String(chapterViews));

                return (
                  <Link
                    key={ch.id}
                    to={`/reader/${mangaId}/${ch.id}`}
                    className={`p-3 rounded-xl border flex items-center justify-between gap-3 transition ${
                      read
                        ? "bg-[#00AEF0]/15 border-[#00AEF0] text-[#00AEF0] shadow-[0_0_12px_rgba(0,174,240,0.2)]"
                        : "bg-[#101216] border-[#262a33] text-white hover:border-[#00AEF0] hover:bg-[#15171c]"
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span
                        className={`w-2.5 h-2.5 rounded-full flex-none ${
                          read ? "bg-[#00AEF0] shadow-[0_0_8px_#00AEF0]" : "bg-gray-600"
                        }`}
                      ></span>
                      <div className="truncate">
                        <span className={`font-bold text-xs block truncate ${read ? "text-[#00AEF0]" : "text-white"}`}>
                          {ch.chapter_number ? `Chapter ${ch.chapter_number}` : `Chapter #${ch.id}`}
                        </span>
                        {ch.title && (
                          <span className="text-[10px] text-[#8b93a3] block truncate">
                            {ch.title}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-none text-[11px]">
                      <span className="text-[#8b93a3] flex items-center gap-1">
                        <i className="fas fa-eye text-[10px]"></i>
                        <span>{formattedChapterViews}</span>
                      </span>
                      {read ? (
                        <span className="px-2 py-0.5 rounded text-[10px] bg-[#00AEF0] text-black font-extrabold shadow">
                          ✓ Read
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-[10px] bg-[#1f2330] text-gray-400 font-medium border border-[#262a33]">
                          New
                        </span>
                      )}
                    </div>
                  </Link>
                );
              })}
            </div>
          ) : (
            /* --- List View --- */
            <div className="divide-y divide-[#262a33] border border-[#262a33] rounded-xl overflow-hidden bg-[#101216]">
              {sortedChapters.map((ch) => {
                const read = isChapterRead(ch);
                const chapterViews = ch.views || 0;
                const formattedChapterViews =
                  ch.views_formatted ||
                  (chapterViews >= 1000
                    ? `${(chapterViews / 1000).toFixed(1).replace(/\.0$/, "")}k`
                    : String(chapterViews));

                return (
                  <Link
                    key={ch.id}
                    to={`/reader/${mangaId}/${ch.id}`}
                    className={`p-3 sm:px-4 flex items-center justify-between gap-4 transition ${
                      read
                        ? "bg-[#00AEF0]/15 border-l-4 border-l-[#00AEF0] text-[#00AEF0] hover:bg-[#00AEF0]/25"
                        : "hover:bg-[#15171c] text-white"
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className={`w-2.5 h-2.5 rounded-full flex-none ${
                          read ? "bg-[#00AEF0] shadow-[0_0_8px_#00AEF0]" : "bg-gray-600"
                        }`}
                      ></span>
                      <div className="truncate">
                        <span className={`font-bold text-xs sm:text-sm ${read ? "text-[#00AEF0]" : "text-white"}`}>
                          {ch.chapter_number ? `Chapter ${ch.chapter_number}: ` : ""}
                          {ch.title || `Chapter #${ch.id}`}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 flex-none text-xs">
                      <span className="text-[#8b93a3] hidden sm:flex items-center gap-1 text-[11px]">
                        <i className="fas fa-eye text-[10px]"></i>
                        <span>{formattedChapterViews} reads</span>
                      </span>
                      {read ? (
                        <span className="px-2.5 py-1 rounded-md text-[11px] bg-[#00AEF0] text-black font-extrabold shadow flex items-center gap-1">
                          <i className="fas fa-check"></i>
                          <span>Read</span>
                        </span>
                      ) : (
                        <span className="px-2.5 py-1 rounded-md text-[11px] bg-[#00AEF0] text-white font-bold shadow hover:bg-[#0F5065] transition">
                          Read Chapter
                        </span>
                      )}
                    </div>
                  </Link>
                );
              })}
            </div>
          )
        ) : (
          <p className="text-xs text-[#8b93a3] text-center py-8">
            {chapterSearch ? "No chapters matching your search." : "No chapters released yet."}
          </p>
        )}
      </div>

      {/* --- Comments Section --- */}
      <div>
        <CommentSection targetType="manga" targetId={Number(mangaId)} />
      </div>
    </div>
  );
};

export default MangaDetail;
