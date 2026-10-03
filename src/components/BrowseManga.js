import React, { useState, useMemo, useEffect } from "react";
import { Link, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import api from "../services/api";
import useAuth from "../hooks/useAuth";
import AdSection from "./GlobalAds";
import AdPlacement from "./AdPlacement";

const ALL_GENRES = [
  "Action", "Adult", "Adventure", "Comedy", "Cooking", "Crime", "Cyberpunk",
  "Delinquents", "Demons", "Drama", "Dungeons", "Ecchi", "Fantasy", "Game",
  "Gender Bender", "Gore", "Harem", "Historical", "Horror", "Isekai", "Josei",
  "Magic", "Manga", "Manhua", "Manhwa", "Martial Arts", "Mature", "Mecha",
  "Medical", "Military", "Monsters", "Music", "Mystery", "Necromancy", "Office Workers",
  "One Shot", "Overpowered", "Police", "Post-Apocalyptic", "Psychological", "Reincarnation",
  "Regression", "Revenge", "Romance", "School Life", "Sci Fi", "Seinen", "Shoujo",
  "Shoujo Ai", "Shounen", "Shounen Ai", "Slice Of Life", "Smut", "Sports", "Super Power",
  "Supernatural", "Survival", "Thriller", "Time Travel", "Tragedy", "Vampires",
  "Video Games", "Villainess", "Webtoons", "Wuxia", "Xianxia", "Yaoi", "Yuri", "Zombies"
];

// Genres hidden by "Hide NSFW" (sent to the server as exclusions, so the
// count and the pages stay right). The server compares genres case-blind.
const NSFW_GENRES = ["Adult", "Ecchi", "Hentai", "Smut", "Gore", "Mature"];

const PER_PAGE = 48;
const SORTS = ["latest", "new", "views_today", "views_week", "views_month", "popular", "rating", "az", "chapters"];

const listParam = (value) => (value ? value.split(",").map((v) => v.trim()).filter(Boolean) : []);

// First chapter when the series has one, otherwise its detail page.
const readNowLink = (manga) =>
  manga.first_chapter_id ? `/reader/${manga.id}/${manga.first_chapter_id}` : `/manga/${manga.id}`;

export default function BrowseManga() {
  const { user } = useAuth();
  const isUnder18 = user?.is_under_18 === true || (user?.age != null && user.age < 18);

  // Every filter lives in the address (plan.md P1-3, P1-4), so the navbar
  // search, genre links and "see all" links land on the right results, and
  // the server does the filtering over the whole catalogue, not one page.
  const [params, setParams] = useSearchParams();
  const searchQuery = params.get("search") || params.get("q") || "";
  const status = params.get("status") || "";
  const type = params.get("type") || "";
  const sortParam = params.get("sort") || "latest";
  const sort = SORTS.includes(sortParam) ? sortParam : "latest";
  const includeGenres = listParam(params.get("genre"));
  const excludeGenres = listParam(params.get("exclude"));
  const page = Math.max(1, Number.parseInt(params.get("page") || "1", 10) || 1);

  const [safeMode, setSafeMode] = useState(true);
  const [advancedCollapsed, setAdvancedCollapsed] = useState(false);
  const [viewMode, setViewMode] = useState("grid"); // "grid" | "list"
  const [searchInput, setSearchInput] = useState(searchQuery);

  // Any change of filter starts again from page 1.
  const update = (changes, { keepPage = false } = {}) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      const empty = value == null || value === "" || (Array.isArray(value) && value.length === 0);
      if (empty) next.delete(key);
      else next.set(key, Array.isArray(value) ? value.join(",") : String(value));
    }
    if (!keepPage) next.delete("page");
    if ("search" in changes) next.delete("q");
    setParams(next, { replace: !keepPage });
  };

  useEffect(() => setSearchInput(searchQuery), [searchQuery]);
  useEffect(() => {
    if (searchInput.trim() === searchQuery) return undefined;
    const timer = setTimeout(() => update({ search: searchInput.trim() }), 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  const hideNsfw = safeMode || isUnder18;
  const excluded = useMemo(() => {
    const all = [...excludeGenres];
    if (hideNsfw) {
      for (const g of NSFW_GENRES) {
        if (!all.some((e) => e.toLowerCase() === g.toLowerCase())) all.push(g);
      }
    }
    return all;
  }, [excludeGenres, hideNsfw]);

  const { data: browseData, isLoading } = useQuery({
    queryKey: ["browseManga", searchQuery, status, type, sort, page, includeGenres.join(","), excluded.join(",")],
    queryFn: () =>
      api.manga.browse({
        search: searchQuery || undefined,
        status: status || undefined,
        type: type || undefined,
        sort,
        include: includeGenres.length ? includeGenres.join(",") : undefined,
        exclude: excluded.length ? excluded.join(",") : undefined,
        page,
        per_page: PER_PAGE,
      }),
    placeholderData: (previous) => previous,
  });

  const mangaItems = Array.isArray(browseData?.items) ? browseData.items : [];
  const totalResults = Number(browseData?.total) || 0;
  const totalPages = Math.max(1, Math.ceil(totalResults / PER_PAGE));

  const toggleIn = (list, genre) =>
    list.includes(genre) ? list.filter((g) => g !== genre) : [...list, genre];
  const toggleIncludeGenre = (genre) => update({ genre: toggleIn(includeGenres, genre) });
  const toggleExcludeGenre = (genre) => update({ exclude: toggleIn(excludeGenres, genre) });
  const setStatus = (value) => update({ status: value });
  const setType = (value) => update({ type: value });
  const setSort = (value) => update({ sort: value === "latest" ? "" : value });
  const setPage = (value) => update({ page: value > 1 ? value : "" }, { keepPage: true });

  const handleResetFilters = () => {
    setSearchInput("");
    setParams(new URLSearchParams(), { replace: true });
  };

  return (
    <div className="max-w-[1240px] mx-auto px-3 sm:px-4 py-4 space-y-4">
      <AdPlacement placement="browse_top" className="mb-3" />
      <AdSection sectionKey="browse_header" fallback={null} />

      {/* Header Title & Counter Badge */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[#00AEF0] tracking-tight">Browse Comics</h1>
        <p className="text-xs text-[#8b93a3] mt-1 font-medium">Discover your next favorite story</p>
        <div className="mt-2.5 inline-flex items-center gap-2 bg-[#15171c] border border-[#262a33] px-3 py-1 rounded-md text-xs font-semibold text-gray-200 shadow-sm">
          <span className="text-[#00AEF0] text-sm">📖</span>
          <span>{isLoading ? "…" : `${totalResults.toLocaleString()} Comics`}</span>
        </div>
      </div>

      {/* Main Browse Filter Container */}
      <div className="bg-[#15171c] border border-[#262a33] rounded-2xl p-4 sm:p-5 shadow-2xl space-y-4">
        {/* Top 4-Column Controls: Search, Status, Type, Sort By */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 items-end">
          {/* Search */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold text-[#8b93a3] uppercase tracking-wider">Search</label>
            <div className="relative flex items-center">
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && update({ search: searchInput.trim() })}
                aria-label="Search"
                placeholder="Search by title, author, artist..."
                className="w-full bg-[#101216] border border-[#262a33] rounded-lg px-3 py-2 pr-10 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0]"
              />
              <button
                type="button"
                onClick={() => update({ search: searchInput.trim() })}
                aria-label="Search now"
                className="absolute right-1 px-2.5 py-1 bg-[#00AEF0] text-white rounded-md text-xs hover:bg-[#0F5065] transition flex items-center justify-center"
              >
                <i className="fas fa-search text-xs"></i>
              </button>
            </div>
          </div>

          {/* Status */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold text-[#8b93a3] uppercase tracking-wider">Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full bg-[#101216] border border-[#262a33] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#00AEF0]"
            >
              <option value="">Any</option>
              <option value="ongoing">Ongoing</option>
              <option value="completed">Completed</option>
              <option value="hiatus">Hiatus</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </div>

          {/* Type */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold text-[#8b93a3] uppercase tracking-wider">Type</label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full bg-[#101216] border border-[#262a33] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#00AEF0]"
            >
              <option value="">Any</option>
              <option value="manga">Manga</option>
              <option value="manhwa">Manhwa</option>
              <option value="manhua">Manhua</option>
              <option value="comic">Comic</option>
              <option value="webtoon">Webtoon</option>
            </select>
          </div>

          {/* Sort By */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold text-[#8b93a3] uppercase tracking-wider">Sort By</label>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value)}
              className="w-full bg-[#101216] border border-[#262a33] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#00AEF0]"
            >
              <option value="latest">Latest update (Newest)</option>
              <option value="new">Recently added</option>
              <option value="views_today">Most Viewed (Today)</option>
              <option value="views_week">Most Viewed (This Week)</option>
              <option value="views_month">Most Viewed (This Month)</option>
              <option value="popular">Most Popular (All Time)</option>
              <option value="rating">Highest rating</option>
              <option value="az">Title A-Z</option>
              <option value="chapters">Chapter count</option>
            </select>
          </div>
        </div>

        {/* Sub-bar: Advanced Filters Toggle (Left) & Hide NSFW Switch + Reset Filters (Right) */}
        <div className="flex items-center justify-between pt-3 border-t border-[#262a33] flex-wrap gap-3 text-xs">
          <button
            type="button"
            onClick={() => setAdvancedCollapsed(!advancedCollapsed)}
            className="text-gray-300 hover:text-[#00AEF0] font-bold flex items-center gap-1.5 transition select-none"
          >
            <span>Advanced filters</span>
            <span className="text-xs">{advancedCollapsed ? "▼" : "▲"}</span>
          </button>

          <div className="flex items-center gap-4">
            {/* Green Hide NSFW Switch */}
            <label className={`flex items-center gap-2.5 select-none ${isUnder18 ? "cursor-not-allowed opacity-80" : "cursor-pointer"}`}>
              <div className="relative inline-flex items-center">
                <input
                  type="checkbox"
                  checked={isUnder18 ? true : safeMode}
                  disabled={isUnder18}
                  onChange={(e) => {
                    if (isUnder18) return;
                    setSafeMode(e.target.checked);
                    update({});
                  }}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-[#374151] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-[#10b981]"></div>
              </div>
              <span className="text-xs font-semibold text-gray-300 flex items-center gap-1">
                <span>Hide NSFW</span>
                {isUnder18 && (
                  <span className="text-[10px] text-amber-400 font-bold bg-amber-400/10 px-1.5 py-0.5 rounded border border-amber-400/20">
                    Locked (Under 18)
                  </span>
                )}
              </span>
            </label>

            {/* Reset Filters Button */}
            <button
              type="button"
              onClick={handleResetFilters}
              className="bg-[#1f2330] border border-[#374151] hover:border-[#00AEF0] text-gray-200 px-3.5 py-1 rounded-full font-semibold transition text-xs"
            >
              Reset filters
            </button>
          </div>
        </div>

        {/* 6-Card Grid: Row 1 (Include & Exclude side by side on phone, Tags), Row 2 (Chapter Count, Min Rating, Extra Options) */}
        {!advancedCollapsed && (
          <div className="pt-2">
            {/* Include & Exclude Genres Side-by-Side Container */}
            <div className="grid grid-cols-2 gap-2 sm:gap-3">
              {/* 1. INCLUDE GENRES */}
              <div className="bg-[#101216] border border-[#262a33] rounded-xl p-2.5 sm:p-3.5 flex flex-col justify-between">
                <div>
                  <div className="text-[11px] sm:text-xs font-bold text-gray-200 uppercase tracking-wider flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#10b981]"></span>
                    <span>Include</span>
                  </div>
                  <p className="text-[10px] sm:text-[11px] text-[#8b93a3] mt-0.5 mb-1.5 line-clamp-1">Match selected</p>
                  <div className="flex flex-wrap gap-1 max-h-36 sm:max-h-44 overflow-y-auto pr-1">
                    {ALL_GENRES.map((g) => {
                      const active = includeGenres.some((x) => x.toLowerCase() === g.toLowerCase());
                      return (
                        <button
                          key={`inc-${g}`}
                          type="button"
                          onClick={() => toggleIncludeGenre(g)}
                          className={`px-2 py-0.5 rounded-full text-[10px] sm:text-[11px] font-semibold transition border ${
                            active
                              ? "bg-[#10b981] border-[#10b981] text-white shadow-sm"
                              : "bg-[#1a1d24] border-[#2d3340] text-gray-300 hover:border-gray-400"
                          }`}
                        >
                          {g}
                        </button>
                      );
                    })}
                  </div>
                </div>
                {includeGenres.length > 0 && (
                  <div className="pt-1.5 mt-1.5 border-t border-[#262a33] flex items-center justify-between text-[10px] sm:text-[11px] text-[#10b981]">
                    <span>{includeGenres.length} selected</span>
                    <button
                      type="button"
                      onClick={() => update({ genre: [] })}
                      className="text-gray-400 hover:text-white underline text-[10px]"
                    >
                      Clear
                    </button>
                  </div>
                )}
              </div>

              {/* 2. EXCLUDE GENRES */}
              <div className="bg-[#101216] border border-[#262a33] rounded-xl p-2.5 sm:p-3.5 flex flex-col justify-between">
                <div>
                  <div className="text-[11px] sm:text-xs font-bold text-gray-200 uppercase tracking-wider flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#ef4444]"></span>
                    <span>Exclude</span>
                  </div>
                  <p className="text-[10px] sm:text-[11px] text-[#8b93a3] mt-0.5 mb-1.5 line-clamp-1">Hide selected</p>
                  <div className="flex flex-wrap gap-1 max-h-36 sm:max-h-44 overflow-y-auto pr-1">
                    {ALL_GENRES.map((g) => {
                      const active = excludeGenres.some((x) => x.toLowerCase() === g.toLowerCase());
                      return (
                        <button
                          key={`exc-${g}`}
                          type="button"
                          onClick={() => toggleExcludeGenre(g)}
                          className={`px-2 py-0.5 rounded-full text-[10px] sm:text-[11px] font-semibold transition border ${
                            active
                              ? "bg-[#ef4444] border-[#ef4444] text-white shadow-sm"
                              : "bg-[#1a1d24] border-[#2d3340] text-gray-300 hover:border-gray-400"
                          }`}
                        >
                          {g}
                        </button>
                      );
                    })}
                  </div>
                </div>
                {excludeGenres.length > 0 && (
                  <div className="pt-1.5 mt-1.5 border-t border-[#262a33] flex items-center justify-between text-[10px] sm:text-[11px] text-[#ef4444]">
                    <span>{excludeGenres.length} excluded</span>
                    <button
                      type="button"
                      onClick={() => update({ exclude: [] })}
                      className="text-gray-400 hover:text-white underline text-[10px]"
                    >
                      Clear
                    </button>
                  </div>
                )}
              </div>
            </div>

          </div>
        )}
      </div>

      {/* Grid / List View Toggle */}
      <div className="flex items-center justify-between flex-wrap gap-2 pt-1">
        <button
          type="button"
          onClick={() => setViewMode(viewMode === "grid" ? "list" : "grid")}
          className="px-3.5 py-1.5 rounded-lg bg-[#00AEF0] text-white text-xs font-bold flex items-center gap-1.5 shadow-sm hover:bg-[#0F5065] transition"
        >
          <i className={viewMode === "grid" ? "fas fa-th" : "fas fa-list"}></i>
          <span>{viewMode === "grid" ? "Grid" : "List"}</span>
        </button>
      </div>

      {/* Comics Grid View */}
      {isLoading ? (
        <div className="text-center py-16 text-[#8b93a3]">Loading comics...</div>
      ) : mangaItems.length === 0 ? (
        <div className="text-center py-16 text-[#8b93a3] bg-[#15171c] rounded-2xl border border-[#262a33]">
          <p className="font-semibold text-sm text-gray-300">No comics found matching your filters.</p>
          <button
            type="button"
            onClick={handleResetFilters}
            className="mt-3 px-4 py-1.5 bg-[#00AEF0] text-white text-xs font-bold rounded-lg hover:bg-[#0F5065] transition"
          >
            Reset All Filters
          </button>
        </div>
      ) : viewMode === "grid" ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3.5">
          {mangaItems.map((manga) => (
            <article
              key={manga.id}
              className="bg-[#15171c] border border-[#262a33] rounded-xl overflow-hidden shadow-lg flex flex-col group hover:border-[#00AEF0] transition-all hover:-translate-y-1"
            >
              {/* Cover */}
              <div className="relative aspect-[3/4] bg-black overflow-hidden">

                <Link to={`/manga/${manga.id}`} className="block w-full h-full">
                  <img
                    src={manga.cover_url || manga.cover_image}
                    alt={manga.title}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    loading="lazy"
                  />
                </Link>
              </div>

              {/* Title & Stats */}
              <div className="p-3 flex-1 flex flex-col justify-between gap-2">
                <div>
                  <h3 className="font-bold text-xs sm:text-sm text-white line-clamp-1 group-hover:text-[#00AEF0] transition">
                    <Link to={`/manga/${manga.id}`}>{manga.title}</Link>
                  </h3>
                  <div className="flex items-center justify-between text-[11px] text-[#8b93a3] mt-1">
                    <span className="text-amber-400 font-bold">
                      {manga.rating_count > 0 ? `⭐ ${Number(manga.rating).toFixed(1)}` : "Not rated"}
                    </span>
                    <span>{manga.chapters_count || 0} Ch.</span>
                  </div>
                </div>

                <Link
                  to={readNowLink(manga)}
                  className="w-full py-1.5 bg-[#00AEF0]/15 hover:bg-[#00AEF0] text-[#00AEF0] hover:text-white rounded-lg text-xs font-bold text-center transition block"
                >
                  ▶ Read Now
                </Link>
              </div>
            </article>
          ))}
        </div>
      ) : (
        /* List Mode View */
        <div className="flex flex-col gap-2.5">
          {mangaItems.map((manga) => (
            <article
              key={manga.id}
              className="flex items-center gap-3.5 bg-[#15171c] border border-[#262a33] rounded-xl p-3 hover:border-[#00AEF0] transition"
            >
              <Link to={`/manga/${manga.id}`} className="w-20 h-28 flex-none rounded-lg overflow-hidden bg-black shadow-md">
                <img
                  src={manga.cover_url || manga.cover_image}
                  alt={manga.title}
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
              </Link>
              <div className="flex-1 min-w-0 flex flex-col justify-between h-28 py-0.5">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-bold text-sm text-white truncate">
                      <Link to={`/manga/${manga.id}`} className="hover:text-[#00AEF0]">
                        {manga.title}
                      </Link>
                    </h3>
                  </div>
                  <p className="text-xs text-[#8b93a3] line-clamp-2 mt-1">{manga.description || ""}</p>
                </div>
                <div className="flex items-center justify-between text-xs pt-1">
                  <div className="flex items-center gap-3">
                    <span className="text-[#ef4444] font-bold">🔥 {(manga.views || 0).toLocaleString()}</span>
                    <span className="text-amber-400 font-bold">
                      {manga.rating_count > 0 ? `⭐ ${Number(manga.rating).toFixed(1)}` : "Not rated"}
                    </span>
                    <span className="text-gray-400">{manga.chapters_count || 0} Chapters</span>
                  </div>
                  <Link
                    to={readNowLink(manga)}
                    className="px-4 py-1.5 bg-[#00AEF0] text-white font-bold rounded-lg hover:bg-[#0F5065] transition"
                  >
                    ▶ Read Now
                  </Link>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Pagination Controls */}
      <div className="flex items-center justify-center gap-2 pt-4">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => setPage(page - 1)}
          className="px-3.5 py-1.5 rounded-lg bg-[#15171c] border border-[#262a33] text-gray-300 text-xs font-semibold hover:border-[#00AEF0] disabled:opacity-30 disabled:pointer-events-none"
        >
          « Prev
        </button>
        <span className="px-3.5 py-1.5 rounded-lg bg-[#00AEF0] text-white text-xs font-bold">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => setPage(page + 1)}
          className="px-3.5 py-1.5 rounded-lg bg-[#15171c] border border-[#262a33] text-gray-300 text-xs font-semibold hover:border-[#00AEF0] disabled:opacity-30 disabled:pointer-events-none"
        >
          Next »
        </button>
      </div>
    </div>
  );
}
