import React, { useState, useMemo, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
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

const POPULAR_TAGS = [
  "System", "Regression", "OP MC", "Reincarnation", "Dungeons", "Leveling",
  "Cultivation", "Murim", "Revenge", "Virtual Reality", "Game Elements",
  "Magic Academy", "Monsters", "Time Travel", "Apocalypse", "Necromancy",
  "Strong to Stronger", "Solo Hero", "Tower Climb", "Villain Protagonist"
];

export default function BrowseManga() {
  const { user } = useAuth();
  const isUnder18 = user?.is_under_18 === true || (user?.age != null && user.age < 18);

  const [searchQuery, setSearchQuery] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [sort, setSort] = useState("latest");
  const [safeMode, setSafeMode] = useState(true);
  const [advancedCollapsed, setAdvancedCollapsed] = useState(false);

  // Genre Filters
  const [includeGenres, setIncludeGenres] = useState([]);
  const [excludeGenres, setExcludeGenres] = useState([]);

  // Tags Filter
  const [tagInput, setTagInput] = useState("");
  const [selectedTags, setSelectedTags] = useState([]);

  // Sliders & Numeric Conditions
  const [minChapters, setMinChapters] = useState(0);
  const [maxChapters, setMaxChapters] = useState(9995);
  const [minRating, setMinRating] = useState(0);

  // Extra Options
  const [onlyCompleted, setOnlyCompleted] = useState(false);
  const [onlyTranslated, setOnlyTranslated] = useState(false);
  const [hideHiatus, setHideHiatus] = useState(false);

  // View state
  const [viewMode, setViewMode] = useState("grid"); // "grid" | "list"
  const [page, setPage] = useState(1);
  const location = useLocation();

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const g = params.get("genre");
    if (g) {
      setIncludeGenres([g]);
    }
  }, [location.search]);

  // Fetch manga data from API
  const { data: browseData, isLoading } = useQuery({
    queryKey: ["browseManga", searchQuery, status, type, sort, page],
    queryFn: async () => {
      const res = await api.manga.browse({
        search: searchQuery || undefined,
        status: status || undefined,
        type: type || undefined,
        sort: sort || "latest",
        page,
        per_page: 50,
      });
      return res;
    },
  });

  const mangaItems = Array.isArray(browseData?.items) ? browseData.items : [];
  const totalResults = browseData?.total ? browseData.total : 7004;

  // Filter items in memory according to all detailed conditions
  const filteredItems = useMemo(() => {
    return mangaItems.filter((item) => {
      const genres = Array.isArray(item.genres) ? item.genres : [];

      // Include genres (matches at least one selected genre)
      if (includeGenres.length > 0) {
        const hasInc = includeGenres.some((g) =>
          genres.some((ig) => ig.toLowerCase() === g.toLowerCase())
        );
        if (!hasInc) return false;
      }

      // Exclude genres (hides series that contain any selected genre)
      if (excludeGenres.length > 0) {
        const hasExc = excludeGenres.some((g) =>
          genres.some((eg) => eg.toLowerCase() === g.toLowerCase())
        );
        if (hasExc) return false;
      }

      // Tags filter
      if (selectedTags.length > 0) {
        const matchesTags = selectedTags.every((t) => {
          const lower = t.toLowerCase();
          const inGenres = genres.some((g) => g.toLowerCase().includes(lower));
          const inTitle = item.title?.toLowerCase().includes(lower);
          const inDesc = item.description?.toLowerCase().includes(lower);
          const inTags = Array.isArray(item.tags) && item.tags.some((tag) => tag.toLowerCase().includes(lower));
          return inGenres || inTitle || inDesc || inTags;
        });
        if (!matchesTags) return false;
      }

      // Chapter Count range
      const chaptersCount = item.chapters_count || 1;
      if (minChapters > 0 && chaptersCount < minChapters) {
        return false;
      }
      if (maxChapters < 9995 && chaptersCount > maxChapters) {
        return false;
      }

      // Minimum Rating filter
      const rating = item.rating || 4.0;
      if (minRating > 0 && rating < minRating) {
        return false;
      }

      // Extra Options
      if (onlyCompleted && item.status?.toLowerCase() !== "completed") {
        return false;
      }
      if (onlyTranslated && chaptersCount < 50) {
        return false;
      }
      if (hideHiatus && item.status?.toLowerCase() === "hiatus") {
        return false;
      }

      // Safe mode (Hide NSFW - strictly enforced if under 18)
      if (safeMode || isUnder18) {
        const nsfwKeywords = ["adult", "ecchi", "hentai", "smut", "gore", "mature", "18+"];
        const isNsfw = genres.some((g) => nsfwKeywords.includes(g.toLowerCase()));
        if (isNsfw) return false;
      }

      return true;
    });
  }, [
    mangaItems,
    includeGenres,
    excludeGenres,
    selectedTags,
    minChapters,
    maxChapters,
    minRating,
    onlyCompleted,
    onlyTranslated,
    hideHiatus,
    safeMode,
  ]);

  const toggleIncludeGenre = (genre) => {
    setIncludeGenres((prev) =>
      prev.includes(genre) ? prev.filter((g) => g !== genre) : [...prev, genre]
    );
  };

  const toggleExcludeGenre = (genre) => {
    setExcludeGenres((prev) =>
      prev.includes(genre) ? prev.filter((g) => g !== genre) : [...prev, genre]
    );
  };

  const handleAddTag = (tag) => {
    const trimmed = tag.trim();
    if (!trimmed) return;
    if (!selectedTags.includes(trimmed)) {
      setSelectedTags([...selectedTags, trimmed]);
    }
    setTagInput("");
  };

  const handleRemoveTag = (tagToRemove) => {
    setSelectedTags(selectedTags.filter((t) => t !== tagToRemove));
  };

  const handleResetFilters = () => {
    setSearchQuery("");
    setStatus("");
    setType("");
    setSort("latest");
    setIncludeGenres([]);
    setExcludeGenres([]);
    setSelectedTags([]);
    setTagInput("");
    setMinChapters(0);
    setMaxChapters(9995);
    setMinRating(0);
    setOnlyCompleted(false);
    setOnlyTranslated(false);
    setHideHiatus(false);
    setPage(1);
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
          <span>{totalResults} Comics</span>
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
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by title, author, artist..."
                className="w-full bg-[#101216] border border-[#262a33] rounded-lg px-3 py-2 pr-10 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0]"
              />
              <button
                type="button"
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
                  onChange={(e) => !isUnder18 && setSafeMode(e.target.checked)}
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
          <div className="pt-2 grid grid-cols-1 md:grid-cols-3 gap-2.5 sm:gap-3">
            {/* Include & Exclude Genres Side-by-Side Container */}
            <div className="grid grid-cols-2 gap-2 sm:gap-3 md:col-span-2">
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
                      const active = includeGenres.includes(g);
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
                      onClick={() => setIncludeGenres([])}
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
                      const active = excludeGenres.includes(g);
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
                      onClick={() => setExcludeGenres([])}
                      className="text-gray-400 hover:text-white underline text-[10px]"
                    >
                      Clear
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* 3. TAGS */}
            <div className="bg-[#101216] border border-[#262a33] rounded-xl p-3.5 flex flex-col justify-between">
              <div>
                <div className="text-xs font-bold text-gray-200 uppercase tracking-wider">Tags</div>
                <p className="text-[11px] text-[#8b93a3] mt-0.5 mb-2">Stack tags like system, regression, OP MC, etc.</p>
                
                {/* Tag Search Input */}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleAddTag(tagInput);
                  }}
                  className="relative flex items-center mb-2"
                >
                  <input
                    type="text"
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    placeholder="Search for tags..."
                    className="w-full bg-[#15171c] border border-[#262a33] rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0]"
                  />
                  {tagInput.trim() && (
                    <button
                      type="submit"
                      className="absolute right-1 px-2 py-0.5 bg-[#00AEF0] text-white text-[10px] font-bold rounded"
                    >
                      + Add
                    </button>
                  )}
                </form>

                {/* Selected Tags Chips */}
                {selectedTags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-2 p-1.5 bg-[#15171c] rounded-lg border border-[#262a33]">
                    {selectedTags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-1 bg-[#00AEF0]/20 text-[#00AEF0] border border-[#00AEF0]/40 px-2 py-0.5 rounded-full text-[11px] font-semibold"
                      >
                        <span>{tag}</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveTag(tag)}
                          className="hover:text-red-400 ml-0.5 text-xs leading-none"
                        >
                          ✕
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                {/* Popular Suggested Tags */}
                <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto pr-1">
                  {POPULAR_TAGS.map((tag) => {
                    const isSelected = selectedTags.includes(tag);
                    return (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => isSelected ? handleRemoveTag(tag) : handleAddTag(tag)}
                        className={`px-2 py-0.5 rounded-md text-[10px] font-medium transition border ${
                          isSelected
                            ? "bg-[#00AEF0] border-[#00AEF0] text-white"
                            : "bg-[#15171c] border-[#262a33] text-gray-400 hover:text-white hover:border-gray-500"
                        }`}
                      >
                        {tag}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* 4. CHAPTER COUNT */}
            <div className="bg-[#101216] border border-[#262a33] rounded-xl p-3.5 flex flex-col justify-between space-y-3">
              <div>
                <div className="text-xs font-bold text-gray-200 uppercase tracking-wider">Chapter Count</div>
                <p className="text-[11px] text-[#8b93a3] mt-0.5 mb-2.5">Target on-going binge (high max) or short completed reads (lower max).</p>
                
                {/* Min Chapters Slider */}
                <div className="space-y-1 mb-3">
                  <div className="flex justify-between text-xs font-semibold">
                    <span className="text-[#8b93a3]">Min chapters</span>
                    <span className="text-white">{minChapters === 0 ? "Any" : minChapters}</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="500"
                    step="5"
                    value={minChapters}
                    onChange={(e) => setMinChapters(Number(e.target.value))}
                    className="w-full accent-[#00AEF0] h-1.5 bg-[#252a38] rounded-lg cursor-pointer"
                  />
                </div>

                {/* Max Chapters Slider */}
                <div className="space-y-1">
                  <div className="flex justify-between text-xs font-semibold">
                    <span className="text-[#8b93a3]">Max chapters</span>
                    <span className="text-white">{maxChapters >= 9995 ? "9995" : maxChapters}</span>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="9995"
                    step="25"
                    value={maxChapters}
                    onChange={(e) => setMaxChapters(Number(e.target.value))}
                    className="w-full accent-[#00AEF0] h-1.5 bg-[#252a38] rounded-lg cursor-pointer"
                  />
                </div>
              </div>
            </div>

            {/* 5. MINIMUM RATING */}
            <div className="bg-[#101216] border border-[#262a33] rounded-xl p-3.5 flex flex-col justify-between space-y-3">
              <div>
                <div className="text-xs font-bold text-gray-200 uppercase tracking-wider">Minimum Rating</div>
                <p className="text-[11px] text-[#8b93a3] mt-0.5 mb-2.5">Filter out low-rated series.</p>
                
                <div className="space-y-1.5 pt-1">
                  <div className="flex justify-between text-xs font-semibold">
                    <span className="text-[#8b93a3]">Min rating</span>
                    <span className="text-white">{minRating === 0 ? "Any" : `${minRating.toFixed(1)} ★`}</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="5"
                    step="0.5"
                    value={minRating}
                    onChange={(e) => setMinRating(Number(e.target.value))}
                    className="w-full accent-[#00AEF0] h-1.5 bg-[#252a38] rounded-lg cursor-pointer"
                  />
                  <div className="flex justify-between text-[10px] text-gray-500 pt-1">
                    <span>Any</span>
                    <span>2.5 ★</span>
                    <span>5.0 ★</span>
                  </div>
                </div>
              </div>
            </div>

            {/* 6. EXTRA OPTIONS */}
            <div className="bg-[#101216] border border-[#262a33] rounded-xl p-3.5 flex flex-col justify-between">
              <div>
                <div className="text-xs font-bold text-gray-200 uppercase tracking-wider">Extra Options</div>
                <p className="text-[11px] text-[#8b93a3] mt-0.5 mb-2.5">Tighten search with more conditions.</p>
                
                <div className="space-y-2 text-xs font-medium text-gray-200">
                  <label className="flex items-center gap-2.5 cursor-pointer hover:text-white">
                    <input
                      type="checkbox"
                      checked={onlyCompleted}
                      onChange={(e) => setOnlyCompleted(e.target.checked)}
                      className="w-4 h-4 rounded bg-[#101216] border-[#374151] text-[#00AEF0] focus:ring-0 focus:outline-none"
                    />
                    <span>Only completed series</span>
                  </label>

                  <label className="flex items-center gap-2.5 cursor-pointer hover:text-white">
                    <input
                      type="checkbox"
                      checked={onlyTranslated}
                      onChange={(e) => setOnlyTranslated(e.target.checked)}
                      className="w-4 h-4 rounded bg-[#101216] border-[#374151] text-[#00AEF0] focus:ring-0 focus:outline-none"
                    />
                    <span>At least 50+ chapters translated</span>
                  </label>

                  <label className="flex items-center gap-2.5 cursor-pointer hover:text-white">
                    <input
                      type="checkbox"
                      checked={hideHiatus}
                      onChange={(e) => setHideHiatus(e.target.checked)}
                      className="w-4 h-4 rounded bg-[#101216] border-[#374151] text-[#00AEF0] focus:ring-0 focus:outline-none"
                    />
                    <span>Hide long hiatus (&gt; 6 months)</span>
                  </label>
                </div>
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
      ) : filteredItems.length === 0 ? (
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
          {filteredItems.map((manga) => (
            <article
              key={manga.id}
              className="bg-[#15171c] border border-[#262a33] rounded-xl overflow-hidden shadow-lg flex flex-col group hover:border-[#00AEF0] transition-all hover:-translate-y-1"
            >
              {/* Cover & Trending Badge */}
              <div className="relative aspect-[3/4] bg-black overflow-hidden">
                <span className="absolute top-2 left-2 z-10 px-2 py-0.5 rounded text-[10px] font-extrabold uppercase bg-[#ef4444] text-white tracking-wider shadow-md">
                  Trending
                </span>

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
                      ⭐ {(manga.rating || 4.5).toFixed(1)}
                    </span>
                    <span>{manga.chapters_count || 50}+ Ch.</span>
                  </div>
                </div>

                <Link
                  to={`/reader/${manga.id}/${manga.id * 100 + 1}`}
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
          {filteredItems.map((manga) => (
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
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-extrabold uppercase bg-[#ef4444] text-white">
                      Trending
                    </span>
                    <h3 className="font-bold text-sm text-white truncate">
                      <Link to={`/manga/${manga.id}`} className="hover:text-[#00AEF0]">
                        {manga.title}
                      </Link>
                    </h3>
                  </div>
                  <p className="text-xs text-[#8b93a3] line-clamp-2 mt-1">{manga.description || "Exciting storyline and captivating art."}</p>
                </div>
                <div className="flex items-center justify-between text-xs pt-1">
                  <div className="flex items-center gap-3">
                    <span className="text-[#ef4444] font-bold">🔥 {(manga.views || 482000).toLocaleString()}</span>
                    <span className="text-amber-400 font-bold">⭐ {(manga.rating || 4.5).toFixed(1)}</span>
                    <span className="text-gray-400">{manga.chapters_count || 50} Chapters</span>
                  </div>
                  <Link
                    to={`/reader/${manga.id}/${manga.id * 100 + 1}`}
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
          {page}
        </span>
        <button
          type="button"
          onClick={() => setPage(page + 1)}
          className="px-3.5 py-1.5 rounded-lg bg-[#15171c] border border-[#262a33] text-gray-300 text-xs font-semibold hover:border-[#00AEF0]"
        >
          Next »
        </button>
      </div>
    </div>
  );
}
