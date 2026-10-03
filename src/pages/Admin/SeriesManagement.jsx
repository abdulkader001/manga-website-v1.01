import { PAGE_PLACEHOLDER } from "../../utils/placeholders";
import React, { useState, useMemo, useEffect } from "react";
import { Link } from "react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { apiFetch } from "../../services/api";
import { auditUrlSecurity } from "../../utils/urlValidator";
import useStaffPermissions from "../../hooks/useStaffPermissions";
import TakedownPanel from "./TakedownPanel";

const FREQUENCY_PRESETS = [
  { key: "hourly_6", label: "Every 6 Hours (Fast Hot Release)", freq: "hourly", val: 6, unit: "hours" },
  { key: "hourly_12", label: "Every 12 Hours", freq: "hourly", val: 12, unit: "hours" },
  { key: "daily_1", label: "Every 1 Day (Daily)", freq: "daily", val: 1, unit: "days" },
  { key: "daily_3", label: "Every 3 Days", freq: "daily", val: 3, unit: "days" },
  { key: "weekly_7", label: "Every 7 Days (Weekly - Recommended)", freq: "weekly", val: 7, unit: "days" },
  { key: "biweekly_14", label: "Every 14 Days (Bi-Weekly)", freq: "biweekly", val: 14, unit: "days" },
  { key: "monthly_30", label: "Every 30 Days (Monthly)", freq: "monthly", val: 30, unit: "days" },
  { key: "custom", label: "Custom Interval", freq: "custom", val: 7, unit: "days" },
];

function formatTimeRemaining(isoDate) {
  if (!isoDate) return "Pending setup";
  try {
    const diff = new Date(isoDate).getTime() - Date.now();
    if (diff <= 0) return "Ready to scrape";
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(hours / 24);
    if (days > 0) return `in ${days}d ${hours % 24}h`;
    const minutes = Math.floor((diff % 3600000) / 60000);
    return `in ${hours}h ${minutes}m`;
  } catch {
    return "Scheduled";
  }
}

// Long scraper jobs run on a background worker: start them, then poll the task
// row until the worker reports "done" or "failed".
async function waitForTask(taskId, { intervalMs = 1500, timeoutMs = 240000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const task = await api.scraper.getTask(taskId);
    if (task?.status === "done" || task?.status === "failed") return task;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("The scraper worker took too long to answer. Check that a worker is running.");
}

export default function SeriesManagement() {
  const queryClient = useQueryClient();
  // The Scraper AI (its API key and Custom Parser) is main-admin only; the
  // server refuses sub-admins as well, this just keeps the page honest.
  // Owner powers: the owner always, an Admin while the owner leaves them on.
  const { can } = useStaffPermissions();
  const canAi = can("configure_scraper_ai");
  const canParser = can("trigger_scraper_ai");
  const canTakedown = can("set_takedown");
  const [takedownManga, setTakedownManga] = useState(null);

  // Search and Filter Tab state
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState("all");

  // Dedicated Scraper AI API Configuration State
  const [scraperAiKey, setScraperAiKey] = useState("");
  const [scraperAiModel, setScraperAiModel] = useState("gemini-2.5-flash");
  const [scraperEndpointUrl, setScraperEndpointUrl] = useState("");
  const [savingAiKey, setSavingAiKey] = useState(false);
  const [aiConfigOpen, setAiConfigOpen] = useState(false);
  const [showAiKey, setShowAiKey] = useState(false);

  // Custom parser (per-website extraction rules written by the Scraper AI)
  const [parserOpen, setParserOpen] = useState(false);
  const [parserUrl, setParserUrl] = useState("");
  const [parserBusy, setParserBusy] = useState(false);
  const [parserResult, setParserResult] = useState(null);
  const [parsers, setParsers] = useState([]);

  // Auto-detect AI provider live from key format (Global, Chinese, French, US)
  const detectedProvider = useMemo(() => {
    const k = (scraperAiKey || "").trim();
    if (!k) return null;
    if (k.startsWith("AIzaSy")) {
      return { name: "Google Gemini", defaultModel: "gemini-2.5-flash", icon: "fab fa-google", color: "text-blue-400 bg-blue-500/15 border-blue-500/40" };
    }
    if (k.startsWith("sk-ant-")) {
      return { name: "Anthropic Claude", defaultModel: "claude-3-7-sonnet", icon: "fas fa-feather-alt", color: "text-amber-400 bg-amber-500/15 border-amber-500/40" };
    }
    if (k.startsWith("sk-proj-") || (k.startsWith("sk-") && !k.includes("ant"))) {
      return { name: "OpenAI / ChatGPT", defaultModel: "gpt-4o-mini", icon: "fas fa-bolt", color: "text-emerald-400 bg-emerald-500/15 border-emerald-500/40" };
    }
    if (k.toLowerCase().includes("deepseek") || k.startsWith("ds-")) {
      return { name: "🇨🇳 DeepSeek AI (China)", defaultModel: "deepseek-r1", icon: "fas fa-code-branch", color: "text-indigo-400 bg-indigo-500/15 border-indigo-500/40" };
    }
    if (k.toLowerCase().includes("qwen") || k.startsWith("sk-qw")) {
      return { name: "🇨🇳 Alibaba Qwen (China)", defaultModel: "qwen-2.5-72b", icon: "fas fa-brain", color: "text-amber-400 bg-amber-500/15 border-amber-500/40" };
    }
    if (k.toLowerCase().includes("glm") || k.toLowerCase().includes("zhipu")) {
      return { name: "🇨🇳 Zhipu AI GLM (China)", defaultModel: "glm-4-plus", icon: "fas fa-cube", color: "text-cyan-400 bg-cyan-500/15 border-cyan-500/40" };
    }
    if (k.toLowerCase().includes("kimi") || k.toLowerCase().includes("moonshot")) {
      return { name: "🇨🇳 Moonshot AI Kimi (China)", defaultModel: "moonshot-v1", icon: "fas fa-moon", color: "text-purple-400 bg-purple-500/15 border-purple-500/40" };
    }
    if (k.toLowerCase().includes("mistral") || k.startsWith("mis-")) {
      return { name: "🇫🇷 Mistral AI (France)", defaultModel: "mistral-large-latest", icon: "fas fa-wind", color: "text-orange-400 bg-orange-500/15 border-orange-500/40" };
    }
    if (k.startsWith("gsk_")) {
      return { name: "Groq Cloud (Ultra Fast)", defaultModel: "llama-3.3-70b-groq", icon: "fas fa-tachometer-alt", color: "text-rose-400 bg-rose-500/15 border-rose-500/40" };
    }
    if (k.startsWith("co-") || k.toLowerCase().includes("cohere")) {
      return { name: "Cohere Command", defaultModel: "command-r-plus", icon: "fas fa-layer-group", color: "text-teal-400 bg-teal-500/15 border-teal-500/40" };
    }
    return { name: "Custom Verified AI Key", defaultModel: scraperAiModel, icon: "fas fa-key", color: "text-purple-400 bg-purple-500/15 border-purple-500/40" };
  }, [scraperAiKey, scraperAiModel]);

  const handleKeyChange = (newKey) => {
    setScraperAiKey(newKey);
    const k = (newKey || "").trim();
    if (k.startsWith("AIzaSy")) setScraperAiModel("gemini-2.5-flash");
    else if (k.startsWith("sk-ant-")) setScraperAiModel("claude-3-7-sonnet");
    else if (k.startsWith("sk-proj-") || (k.startsWith("sk-") && !k.includes("ant"))) setScraperAiModel("gpt-4o-mini");
    else if (k.toLowerCase().includes("deepseek") || k.startsWith("ds-")) setScraperAiModel("deepseek-r1");
    else if (k.toLowerCase().includes("qwen") || k.startsWith("sk-qw")) setScraperAiModel("qwen-2.5-72b");
    else if (k.toLowerCase().includes("glm") || k.toLowerCase().includes("zhipu")) setScraperAiModel("glm-4-plus");
    else if (k.toLowerCase().includes("kimi") || k.toLowerCase().includes("moonshot")) setScraperAiModel("moonshot-v1");
    else if (k.toLowerCase().includes("mistral") || k.startsWith("mis-")) setScraperAiModel("mistral-large-latest");
    else if (k.startsWith("gsk_")) setScraperAiModel("llama-3.3-70b-groq");
  };

  // Add / Import Series Form State
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [mangaupdatesUrl, setMangaupdatesUrl] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [seriesUrl, setSeriesUrl] = useState("");
  const [customTitle, setCustomTitle] = useState("");
  const [customChapterCount, setCustomChapterCount] = useState("");
  const [customDescription, setCustomDescription] = useState("");
  const [customAuthor, setCustomAuthor] = useState("");
  const [customCover, setCustomCover] = useState("");
  const [type, setType] = useState("manhwa");
  const [textLanguage, setTextLanguage] = useState("");
  // How the source lays its chapters/pages out (see backend chapter_grouping).
  const [groupSize, setGroupSize] = useState("");
  const [sourceFormat, setSourceFormat] = useState("auto");
  const [readingDir, setReadingDir] = useState("auto");
  const [selectedPreset, setSelectedPreset] = useState("weekly_7");
  const [customVal, setCustomVal] = useState(7);
  const [customUnit, setCustomUnit] = useState("days");
  const [adding, setAdding] = useState(false);

  // Live Scraper Extraction Preview State
  const [previewData, setPreviewData] = useState(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

  // Edit Schedule Modal State
  const [editingManga, setEditingManga] = useState(null);
  const [editFreq, setEditFreq] = useState("weekly");
  const [editVal, setEditVal] = useState(7);
  const [editUnit, setEditUnit] = useState("days");
  const [editEnabled, setEditEnabled] = useState(true);
  const [editSourceUrl, setEditSourceUrl] = useState("");
  const [savingSchedule, setSavingSchedule] = useState(false);

  // Picture Layout Modal State
  const [layoutManga, setLayoutManga] = useState(null);
  const [layoutSpread, setLayoutSpread] = useState("auto");
  const [layoutDirection, setLayoutDirection] = useState("rtl");
  const [layoutTextLanguage, setLayoutTextLanguage] = useState("");
  const [savingLayout, setSavingLayout] = useState(false);

  // Notice banner
  const [notice, setNotice] = useState(null);

  // Fetch scraper AI API config (main admin only)
  useEffect(() => {
    if (!canAi) return;
    apiFetch("/api/v1/admin/scraper/ai-config")
      .then((r) => r.json())
      .then((d) => {
        if (d?.apiKey) setScraperAiKey(d.apiKey);
        if (d?.model) setScraperAiModel(d.model);
      })
      .catch(() => {});
  }, [canAi]);

  const handleSaveScraperAi = async (e) => {
    e.preventDefault();
    setSavingAiKey(true);
    try {
      const res = await apiFetch("/api/v1/admin/scraper/ai-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          apiKey: scraperAiKey.trim(),
          model: scraperAiModel,
          endpointUrl: scraperEndpointUrl.trim() || undefined,
          enabled: true,
        }),
      });
      const data = await res.json();
      setNotice({
        type: "success",
        message: data.message || "Dedicated Scraper AI API saved & validated successfully!",
      });
      setAiConfigOpen(false);
    } catch {
      setNotice({ type: "error", message: "Failed to save Scraper AI configuration." });
    } finally {
      setSavingAiKey(false);
    }
  };

  // Test and Live Preview Scraper Extraction
  const handleTestPreview = async () => {
    const muTarget = mangaupdatesUrl.trim();
    const sourceTarget = seriesUrl.trim() || baseUrl.trim();

    if (!muTarget && !sourceTarget) {
      setNotice({ type: "error", message: "Please enter a MangaUpdates URL and a Source Series URL to preview." });
      return;
    }

    if (muTarget && !/mangaupdates\.com\/series|anime-planet\.com\/manga\/[^/]+/.test(muTarget)) {
      setNotice({
        type: "error",
        message:
          "Metadata link must be a MangaUpdates series (https://www.mangaupdates.com/series/<id>/<slug>) or an Anime-Planet manga page (https://www.anime-planet.com/manga/<name>).",
      });
      return;
    }

    setIsPreviewing(true);
    setNotice(null);
    try {
      const started = await api.scraper.startPreview({
        mangaupdates_url: muTarget || undefined,
        url: seriesUrl.trim() || undefined,
        base_url: baseUrl.trim() || undefined,
        title: customTitle.trim() || undefined,
      });
      const task = await waitForTask(started.task_id);
      if (task.status === "failed" || !task.ok) {
        throw new Error(task.message || task.error || "The source could not be read.");
      }
      const preview = task.preview;
      if (preview) {
        setPreviewData(preview);
        if (!customTitle && preview.title) setCustomTitle(preview.title);
        if (preview.detectedChapterCount) setCustomChapterCount(String(preview.detectedChapterCount));
        if (preview.description) setCustomDescription(preview.description);
        if (preview.author) setCustomAuthor(preview.author);
        if (preview.coverImage) setCustomCover(preview.coverImage);
        const source = preview.chapters || preview.detectedChapterCount
          ? ` + ${preview.detectedChapterCount ?? 0} chapters from the source site`
          : "";
        const layoutHint = preview.layout_hint;
        if (layoutHint) {
          // What the scan of real chapters found: pre-fill the layout choices
          // (still editable) instead of making the admin guess.
          if (layoutHint.suggested_source_format && sourceFormat === "auto") {
            setSourceFormat(layoutHint.suggested_source_format);
          }
          if (layoutHint.suggested_group_size && !groupSize) {
            setGroupSize(String(layoutHint.suggested_group_size));
          }
        }
        const warn = (task.warnings || []).length ? ` (${task.warnings.join("; ")})` : "";
        setNotice({
          type: "success",
          message: `Preview complete: "${preview.title}"${source}.${warn}${
            layoutHint?.message ? " " + layoutHint.message : ""
          }`,
        });
      }
    } catch (err) {
      setNotice({ type: "error", message: "Preview extraction failed: " + (err.message || "Unknown error") });
    } finally {
      setIsPreviewing(false);
    }
  };

  const loadParsers = async () => {
    try {
      const data = await api.scraper.listParsers();
      setParsers(Array.isArray(data?.items) ? data.items : []);
    } catch {
      setParsers([]);
    }
  };

  useEffect(() => {
    if (parserOpen && canParser) loadParsers();
  }, [parserOpen, canParser]);

  // Ask the Scraper AI to write extraction rules for any website address.
  const handleGenerateParser = async (e) => {
    e.preventDefault();
    const target = parserUrl.trim();
    if (!target || parserBusy) return;
    const audit = auditUrlSecurity(target.includes("://") ? target : `https://${target}`);
    if (!audit.isSafe) {
      setNotice({ type: "error", message: `Security Alert: unsafe URL blocked. ${audit.flags.join(", ")}` });
      return;
    }
    setParserBusy(true);
    setParserResult(null);
    setNotice(null);
    try {
      const started = await api.scraper.startParserGeneration(target);
      const task = await waitForTask(started.task_id);
      setParserResult(task);
      setNotice({
        type: task.ok ? "success" : "error",
        message: task.message || (task.ok ? "Parser created." : "Could not create a parser for that site."),
      });
      loadParsers();
    } catch (err) {
      setNotice({ type: "error", message: err.message || "Parser generation failed." });
    } finally {
      setParserBusy(false);
    }
  };

  // Fetch manga catalog
  const { data: mangaList, isLoading } = useQuery({
    queryKey: ["mangaCatalogAdmin"],
    queryFn: () => api.manga.browse({ limit: 150 }),
  });

  const manga = useMemo(() => {
    const raw = Array.isArray(mangaList?.items) ? mangaList.items : Array.isArray(mangaList) ? mangaList : [];
    const seen = new Set();
    return raw.filter((m) => {
      const uniqueKey = m.id ? `id_${m.id}` : `slug_${m.slug || m.title}`;
      if (seen.has(uniqueKey)) return false;
      seen.add(uniqueKey);
      return true;
    });
  }, [mangaList]);

  // Filtered list by Tab and Search
  const filteredManga = useMemo(() => {
    return manga.filter((m) => {
      if (activeTab === "hourly" && m.scrape_interval_unit !== "hours" && m.scrape_frequency !== "hourly") return false;
      if (activeTab === "daily" && m.scrape_frequency !== "daily" && (m.scrape_interval_unit !== "days" || m.scrape_interval_value > 3)) return false;
      if (activeTab === "weekly" && m.scrape_frequency !== "weekly" && (m.scrape_interval_unit !== "days" || m.scrape_interval_value < 4 || m.scrape_interval_value > 10)) return false;
      if (activeTab === "monthly" && m.scrape_frequency !== "monthly" && m.scrape_frequency !== "biweekly" && (m.scrape_interval_unit !== "days" || m.scrape_interval_value < 14)) return false;
      if (activeTab === "paused" && m.auto_scrape_enabled !== false) return false;

      if (search.trim()) {
        const q = search.toLowerCase();
        return m.title.toLowerCase().includes(q) || (m.author && m.author.toLowerCase().includes(q));
      }
      return true;
    });
  }, [manga, activeTab, search]);

  const tabCounts = useMemo(() => {
    return {
      all: manga.length,
      hourly: manga.filter((m) => m.scrape_interval_unit === "hours" || m.scrape_frequency === "hourly").length,
      daily: manga.filter((m) => m.scrape_frequency === "daily" || (m.scrape_interval_unit === "days" && m.scrape_interval_value <= 3)).length,
      weekly: manga.filter((m) => m.scrape_frequency === "weekly" || (m.scrape_interval_unit === "days" && m.scrape_interval_value >= 4 && m.scrape_interval_value <= 10)).length,
      monthly: manga.filter((m) => m.scrape_frequency === "monthly" || m.scrape_frequency === "biweekly" || (m.scrape_interval_unit === "days" && m.scrape_interval_value >= 14)).length,
      paused: manga.filter((m) => m.auto_scrape_enabled === false).length,
    };
  }, [manga]);

  // Handle Add / Full Import Series with Automatic Chapter Detection
  const handleAddSeries = async (e) => {
    e.preventDefault();
    if ((!seriesUrl.trim() && !baseUrl.trim()) || adding) return;
    setAdding(true);
    setNotice(null);

    let val = customVal;
    let unit = customUnit;
    let freq = "weekly";
    const preset = FREQUENCY_PRESETS.find((p) => p.key === selectedPreset);
    if (preset && preset.key !== "custom") {
      val = preset.val;
      unit = preset.unit;
      freq = preset.freq;
    }

    // Verify URLs against threat intelligence & anti-virus checks
    const baseAudit = auditUrlSecurity(baseUrl.trim());
    const seriesAudit = auditUrlSecurity(seriesUrl.trim());
    if (!baseAudit.isSafe || !seriesAudit.isSafe) {
      setNotice({
        type: "error",
        message: `🛡️ Security Alert: Malicious or unsafe URL blocked. Flags: ${[...baseAudit.flags, ...seriesAudit.flags].join(", ") || "Untrusted domain"}`,
      });
      setAdding(false);
      return;
    }

    try {
      const res = await api.admin.series.add({
        mangaupdates_url: mangaupdatesUrl.trim(),
        base_url: baseUrl.trim(),
        url: seriesUrl.trim(),
        source_url: seriesUrl.trim() || baseUrl.trim(),
        title: customTitle.trim(),
        type,
        scrape_frequency: freq,
        scrape_interval_value: val,
        scrape_interval_unit: unit,
        chapters_to_scrape: customChapterCount ? Number(customChapterCount) : undefined,
        chapter_group_size: groupSize ? Number(groupSize) : undefined,
        source_format: sourceFormat === "auto" ? undefined : sourceFormat,
        reading_direction: readingDir === "auto" ? undefined : readingDir,
        custom_description: customDescription.trim() || undefined,
        custom_cover_image: customCover.trim() || undefined,
        author: customAuthor.trim() || undefined,
        text_language: textLanguage || undefined,
      });

      setNotice({
        type: "success",
        message: `✅ ${res?.message || `Successfully scraped & ingested all chapters automatically without caps! Auto-scrape crawler active every ${val} ${unit}.`}`,
      });
      setBaseUrl("");
      setSeriesUrl("");
      setCustomTitle("");
      setCustomChapterCount("");
      setCustomDescription("");
      setCustomAuthor("");
      setCustomCover("");
      setGroupSize("");
      setSourceFormat("auto");
      setReadingDir("auto");
      setPreviewData(null);
      setImportModalOpen(false);
      queryClient.invalidateQueries({ queryKey: ["mangaCatalogAdmin"] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    } catch (err) {
      setNotice({ type: "error", message: "Failed to import series: " + (err.message || "Unknown error") });
    } finally {
      setAdding(false);
    }
  };

  const handleOpenEditSchedule = (item) => {
    setEditingManga(item);
    setEditFreq(item.scrape_frequency || "weekly");
    setEditVal(item.scrape_interval_value || 7);
    setEditUnit(item.scrape_interval_unit || "days");
    setEditEnabled(item.auto_scrape_enabled !== false);
    setEditSourceUrl(item.source_url || "");
  };

  const handleSaveSchedule = async (e) => {
    e.preventDefault();
    if (!editingManga) return;
    setSavingSchedule(true);
    try {
      await api.admin.series.updateSchedule(editingManga.id, {
        scrape_frequency: editFreq,
        scrape_interval_value: Number(editVal),
        scrape_interval_unit: editUnit,
        auto_scrape_enabled: editEnabled,
        source_url: editSourceUrl.trim(),
      });
      setNotice({
        type: "success",
        message: `✅ Updated scraping timer for "${editingManga.title}" to every ${editVal} ${editUnit}!`,
      });
      setEditingManga(null);
      queryClient.invalidateQueries({ queryKey: ["mangaCatalogAdmin"] });
    } catch (err) {
      setNotice({ type: "error", message: "Failed to update schedule: " + err.message });
    } finally {
      setSavingSchedule(false);
    }
  };

  const handleMirrorImages = async (id, title) => {
    try {
      const res = await api.admin.series.mirrorImages(id);
      setNotice({ type: "success", message: `✅ ${res?.message || `Compressing pictures for "${title}".`}` });
      queryClient.invalidateQueries({ queryKey: ["mangaCatalogAdmin"] });
    } catch (err) {
      setNotice({ type: "error", message: "Picture compression failed: " + err.message });
    }
  };

  const handleOpenLayout = (m) => {
    const stored = m.scrape_layout || {};
    setLayoutManga(m);
    setLayoutSpread(stored.spread_mode || "auto");
    setLayoutDirection(stored.reading_direction || (m.type === "manga" ? "rtl" : "ltr"));
    setLayoutTextLanguage(m.language || "");
  };

  const handleSaveLayout = async (e) => {
    e.preventDefault();
    if (!layoutManga) return;
    setSavingLayout(true);
    try {
      const res = await api.admin.series.updateLayout(layoutManga.id, {
        spread_mode: layoutSpread,
        reading_direction: layoutDirection,
        text_language: layoutTextLanguage,
      });
      setNotice({ type: "success", message: `✅ ${res?.message || `Layout saved for "${layoutManga.title}".`}` });
      setLayoutManga(null);
      queryClient.invalidateQueries({ queryKey: ["mangaCatalogAdmin"] });
    } catch (err) {
      setNotice({ type: "error", message: "Failed to save layout: " + err.message });
    } finally {
      setSavingLayout(false);
    }
  };

  const handleRescrape = async (id, title) => {
    const typed = window.prompt(
      `Re-scrape every chapter of "${title}" from the source?\nType the series name to confirm:`,
      ""
    );
    if (typed === null) return;
    if (typed.trim() !== (title || "").trim()) {
      setNotice({ type: "error", message: "Re-scrape cancelled: the name you typed doesn't match the series name." });
      return;
    }
    try {
      const res = await api.admin.series.rescrape(id, typed.trim());
      setNotice({
        type: "success",
        message: `✅ ${res?.message || `Re-scrape of "${title}" started. Chapters are re-fetched in the background.`}`,
      });
      queryClient.invalidateQueries({ queryKey: ["mangaCatalogAdmin"] });
    } catch (err) {
      setNotice({ type: "error", message: "Re-scrape failed: " + err.message });
    }
  };

  const handleToggleAutoScrape = async (item) => {
    const nextState = !item.auto_scrape_enabled;
    try {
      await api.admin.series.updateSchedule(item.id, {
        auto_scrape_enabled: nextState,
      });
      queryClient.invalidateQueries({ queryKey: ["mangaCatalogAdmin"] });
      setNotice({
        type: "success",
        message: `${nextState ? "Resumed" : "Paused"} auto-scraping timer for "${item.title}".`,
      });
    } catch (err) {
      setNotice({ type: "error", message: "Failed to toggle schedule: " + err.message });
    }
  };

  const handleDelete = async (id, title) => {
    if (!window.confirm(`Delete "${title}", all its chapters and stored pictures? This can't be undone.`)) return;
    try {
      await api.admin.series.remove(id);
      queryClient.invalidateQueries({ queryKey: ["mangaCatalogAdmin"] });
      setNotice({ type: "success", message: `"${title}" was removed.` });
    } catch (err) {
      setNotice({ type: "error", message: "Delete failed: " + err.message });
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#262a33] pb-4">
        <div>
          <Link to="/admin" className="text-xs text-[#00AEF0] hover:underline mb-1 block font-semibold">
            ← Back to Admin Console
          </Link>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center gap-2.5">
            <i className="fas fa-spider text-[#00AEF0]"></i>
            <span>Series &amp; AI Scraper Management</span>
          </h1>
          <p className="text-xs sm:text-sm text-[#8b93a3] mt-0.5">
            Automated crawler pipeline with auto chapter detection and dedicated Scraper AI parsing engine.
          </p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          {canAi && (
          <button
            type="button"
            onClick={() => setAiConfigOpen(!aiConfigOpen)}
            className="px-3.5 py-2.5 rounded-xl bg-[#15171c] hover:bg-[#1f2330] border border-purple-500/40 text-purple-300 font-bold text-xs transition flex items-center gap-2 shadow"
          >
            <i className="fas fa-robot text-purple-400"></i>
            <span>Scraper AI API</span>
          </button>
          )}

          {canParser && (
          <button
            type="button"
            onClick={() => setParserOpen(!parserOpen)}
            className="px-3.5 py-2.5 rounded-xl bg-[#15171c] hover:bg-[#1f2330] border border-cyan-500/40 text-cyan-300 font-bold text-xs transition flex items-center gap-2 shadow"
          >
            <i className="fas fa-code text-cyan-400"></i>
            <span>Custom Parser</span>
          </button>
          )}

          <button
            type="button"
            onClick={() => setImportModalOpen(true)}
            className="px-4 py-2.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-extrabold text-xs transition flex items-center gap-2 shadow-lg"
          >
            <i className="fas fa-plus"></i>
            <span>Import &amp; Scrape Manga</span>
          </button>
        </div>
      </div>

      {/* Dedicated Scraper AI API Box (main admin only) */}
      {canAi && aiConfigOpen && (
        <div className="bg-[#15171c] border border-purple-500/50 p-5 rounded-2xl shadow-2xl space-y-4 animate-in fade-in">
          <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-full bg-purple-500/20 border border-purple-500/40 flex items-center justify-center text-purple-300">
                <i className="fas fa-brain"></i>
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Dedicated Scraper AI API Engine</h3>
                <p className="text-xs text-[#8b93a3]">
                  Dedicated AI endpoint specifically used to validate websites, parse layout trees, and detect all chapter listings.
                </p>
              </div>
            </div>
            <button type="button" onClick={() => setAiConfigOpen(false)} className="text-gray-400 hover:text-white">✕</button>
          </div>

          <form onSubmit={handleSaveScraperAi} className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="sm:col-span-2 space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-gray-300 block">Scraper Dedicated AI API Key</label>
                {detectedProvider && (
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border flex items-center gap-1.5 ${detectedProvider.color}`}>
                    <i className={detectedProvider.icon}></i>
                    <span>Detected: {detectedProvider.name}</span>
                  </span>
                )}
              </div>
              <div className="relative">
                <input
                  type={showAiKey ? "text" : "password"}
                  value={scraperAiKey}
                  onChange={(e) => handleKeyChange(e.target.value)}
                  placeholder="Paste AI key (auto-detects Gemini, Claude, OpenAI, DeepSeek, Mistral)"
                  className="w-full px-3.5 py-2.5 pr-10 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-purple-400 font-mono"
                />
                <button
                  type="button"
                  onClick={() => setShowAiKey(!showAiKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white p-1 text-xs"
                  title={showAiKey ? "Hide API key" : "Show API key"}
                >
                  <i className={showAiKey ? "fas fa-eye-slash" : "fas fa-eye"}></i>
                </button>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-gray-300 block">AI Phrasing &amp; Extraction Model</label>
              <select
                value={scraperAiModel}
                onChange={(e) => setScraperAiModel(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-purple-400 font-medium"
              >
                <optgroup label="🇨🇳 Chinese Verified AI Models (Premier for Manhua &amp; Webtoons)">
                  <option value="deepseek-r1">DeepSeek R1 (Advanced Reasoning &amp; Translation)</option>
                  <option value="deepseek-v3">DeepSeek V3 (671B Flagship MoE)</option>
                  <option value="qwen-2.5-72b">Alibaba Cloud Qwen 2.5 72B (Leader in Asian Phrasing)</option>
                  <option value="qwen-max">Alibaba Cloud Qwen Max</option>
                  <option value="glm-4-plus">Zhipu AI GLM-4 Plus</option>
                  <option value="glm-4-flash">Zhipu AI GLM-4 Flash (High Speed)</option>
                  <option value="moonshot-v1">Moonshot AI / Kimi (128k Context)</option>
                  <option value="ernie-4.0-turbo">Baidu ERNIE 4.0 Turbo</option>
                </optgroup>
                <optgroup label="🇫🇷 French &amp; European Verified AI Models">
                  <option value="mistral-large-latest">Mistral Large 2 (Paris Flagship)</option>
                  <option value="mistral-nemo">Mistral NeMo 12B</option>
                  <option value="codestral-latest">Mistral Codestral</option>
                  <option value="pixtral-12b">Mistral Pixtral 12B (Multimodal Vision)</option>
                </optgroup>
                <optgroup label="🌐 Global &amp; US Frontier AI Models">
                  <option value="gemini-2.5-flash">Google Gemini 2.5 Flash (Ultra Fast)</option>
                  <option value="gemini-2.5-pro">Google Gemini 2.5 Pro (Deep Multimodal)</option>
                  <option value="claude-3-7-sonnet">Claude 3.7 Sonnet (Advanced Reasoning)</option>
                  <option value="claude-3-5-sonnet">Claude 3.5 Sonnet</option>
                  <option value="gpt-4o">OpenAI GPT-4o</option>
                  <option value="gpt-4o-mini">OpenAI GPT-4o Mini</option>
                  <option value="llama-3.3-70b-groq">Groq Cloud (Llama 3.3 70B Ultra Fast)</option>
                  <option value="command-r-plus">Cohere Command R+</option>
                  <option value="sonar-reasoning">Perplexity AI Sonar</option>
                </optgroup>
                <optgroup label="⚙️ Custom Endpoint">
                  <option value="custom">Custom Verified AI API Endpoint</option>
                </optgroup>
              </select>
            </div>

            {/* Custom Verified AI API Endpoint URL */}
            <div className="sm:col-span-3 space-y-1">
              <label className="text-xs font-semibold text-gray-300 block">
                Custom Verified API Endpoint Base URL (Optional / International Proxy)
              </label>
              <input
                type="url"
                value={scraperEndpointUrl}
                onChange={(e) => setScraperEndpointUrl(e.target.value)}
                placeholder="e.g. https://api.deepseek.com/v1, https://dashscope.aliyuncs.com/compatible-mode/v1, or https://api.mistral.ai/v1"
                className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-purple-400 font-mono"
              />
              <span className="text-[10px] text-gray-400">
                Supports verified endpoints from Chinese, French, European, or custom enterprise providers.
              </span>
            </div>

            <div className="sm:col-span-3 flex justify-end">
              <button
                type="submit"
                disabled={savingAiKey}
                className="px-5 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-bold text-xs transition flex items-center gap-2 shadow"
              >
                <i className={savingAiKey ? "fas fa-spinner fa-spin" : "fas fa-save"}></i>
                <span>{savingAiKey ? "Validating & Saving…" : "Save Scraper AI Configuration"}</span>
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Custom parser: enter any website, the Scraper AI writes its extraction rules (main admin only) */}
      {canParser && parserOpen && (
        <div className="bg-[#15171c] border border-cyan-500/50 p-5 rounded-2xl shadow-2xl space-y-4">
          <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-full bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-300">
                <i className="fas fa-code"></i>
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Custom Parser for a Website</h3>
                <p className="text-xs text-[#8b93a3]">
                  Paste a series page (best) or the site address. Known layouts and moved domains are matched automatically; otherwise the Scraper AI writes and tests the rules.
                </p>
                <p className="text-[11px] text-[#6b7383] mt-1">
                  Best results: open one series in your browser, copy the address of the page that lists its chapters, and paste it here. Use a series with at least two chapters.
                </p>
              </div>
            </div>
            <button type="button" onClick={() => setParserOpen(false)} className="text-gray-400 hover:text-white">✕</button>
          </div>

          <form onSubmit={handleGenerateParser} className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              value={parserUrl}
              onChange={(e) => setParserUrl(e.target.value)}
              placeholder="https://newsite.example/manga/some-series"
              className="flex-1 px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-cyan-400 font-mono"
            />
            <button
              type="submit"
              disabled={parserBusy || !parserUrl.trim()}
              className="px-5 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-700 disabled:opacity-50 text-white font-bold text-xs transition flex items-center justify-center gap-2 shadow"
            >
              <i className={parserBusy ? "fas fa-spinner fa-spin" : "fas fa-magic"}></i>
              <span>{parserBusy ? "Analyzing site…" : "Generate Parser"}</span>
            </button>
          </form>

          {parserResult && (
            <div className={`p-3 rounded-xl border text-xs space-y-1 ${parserResult.ok ? "border-emerald-500/40 text-emerald-300 bg-emerald-950/30" : "border-red-500/40 text-red-300 bg-red-950/30"}`}>
              <div className="font-bold">{parserResult.message}</div>
              {parserResult.domain && (
                <div className="font-mono text-[11px] opacity-80">
                  {parserResult.domain}
                  {parserResult.parser?.source ? ` · ${parserResult.parser.source}` : ""}
                  {parserResult.parser?.status ? ` · ${parserResult.parser.status}` : ""}
                </div>
              )}
              {!parserResult.ok && Array.isArray(parserResult.next_steps) && parserResult.next_steps.length > 0 && (
                <div className="pt-1">
                  <div className="font-semibold opacity-90">What to do next</div>
                  <ol className="list-decimal ml-4 space-y-0.5 opacity-90">
                    {parserResult.next_steps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                </div>
              )}
              {!parserResult.ok && Array.isArray(parserResult.site_signals) && parserResult.site_signals.length > 0 && (
                <details className="pt-1 opacity-80">
                  <summary className="cursor-pointer">What the scraper saw on the page</summary>
                  <ul className="list-disc ml-4 space-y-0.5 font-mono text-[11px]">
                    {parserResult.site_signals.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </details>
              )}
              {parserResult.sample?.title && (
                <div className="opacity-80">
                  Sample: {parserResult.sample.title} — {parserResult.sample.chapters_found ?? 0} chapters found
                  {parserResult.approved ? " · website approved for scraping" : ""}
                </div>
              )}
            </div>
          )}

          {parsers.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] font-bold uppercase tracking-wide text-gray-400">Parsers on file</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                {parsers.map((item) => (
                  <div key={item.id} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[#101216] border border-[#262a33] text-xs">
                    <span className="font-mono text-gray-200 truncate">{item.domain}</span>
                    <span className={`ml-2 shrink-0 px-2 py-0.5 rounded-full text-[10px] font-bold ${item.status === "active" ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"}`}>
                      v{item.version} · {item.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {notice && (
        <div className={`p-3.5 rounded-xl border text-xs flex items-center justify-between ${
          notice.type === "error" ? "bg-red-950/40 border-red-500/40 text-red-300" : "bg-emerald-950/40 border-emerald-500/40 text-emerald-300"
        }`}>
          <span>{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-gray-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Search & Filter Tabs */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs font-semibold">
          {[
            { id: "all", label: "All Series", count: tabCounts.all },
            { id: "hourly", label: "Hourly (Hot)", count: tabCounts.hourly },
            { id: "daily", label: "Daily", count: tabCounts.daily },
            { id: "weekly", label: "Weekly", count: tabCounts.weekly },
            { id: "monthly", label: "Monthly", count: tabCounts.monthly },
            { id: "paused", label: "Paused", count: tabCounts.paused },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1.5 rounded-xl transition whitespace-nowrap flex items-center gap-1.5 ${
                activeTab === tab.id
                  ? "bg-[#00AEF0] text-white shadow"
                  : "bg-[#15171c] text-gray-400 hover:text-white border border-[#262a33]"
              }`}
            >
              <span>{tab.label}</span>
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-black/30 text-white font-mono">{tab.count}</span>
            </button>
          ))}
        </div>

        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by title or author…"
          className="px-3.5 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0] max-w-xs w-full"
        />
      </div>

      {/* Series Catalog Table */}
      <div className="bg-[#15171c] border border-[#262a33] rounded-2xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#101216] text-[#8b93a3] uppercase font-bold border-b border-[#262a33]">
              <tr>
                <th className="p-3.5">Series Title</th>
                <th className="p-3.5">Type &amp; Origin</th>
                <th className="p-3.5">Total Chapters</th>
                <th className="p-3.5">Scrape Interval</th>
                <th className="p-3.5">Next Scrape</th>
                <th className="p-3.5">Status</th>
                <th className="p-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#262a33]">
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-[#8b93a3]">
                    Loading series and crawler schedules…
                  </td>
                </tr>
              ) : filteredManga.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-[#8b93a3]">
                    No series found matching your criteria.
                  </td>
                </tr>
              ) : (
                filteredManga.map((m, idx) => {
                  const isPaused = m.auto_scrape_enabled === false;
                  return (
                    <tr key={m.id ? `series_${m.id}_${idx}` : `series_idx_${idx}`} className="hover:bg-[#101216]/50 transition group">
                      <td className="p-3.5">
                        <div className="flex items-center gap-3">
                          <Link to={`/manga/${m.id}`} target="_blank" className="flex-shrink-0 hover:opacity-85 transition" title={`Open ${m.title}`}>
                            <img
                              src={m.cover_image || m.cover_url}
                              alt={m.title}
                              className="w-10 h-14 object-cover rounded-lg border border-[#262a33]"
                            />
                          </Link>
                          <div>
                            <Link
                              to={`/manga/${m.id}`}
                              target="_blank"
                              className="font-bold text-white hover:text-[#00AEF0] transition flex items-center gap-1.5 text-sm"
                              title={`View ${m.title}`}
                            >
                              <span>{m.title}</span>
                              <i className="fas fa-external-link-alt text-[10px] text-[#00AEF0]"></i>
                            </Link>
                            <span className="text-[11px] text-[#8b93a3]">{m.author || "Unknown Author"}</span>
                          </div>
                        </div>
                      </td>
                      <td className="p-3.5">
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-blue-500/15 text-[#00AEF0] border border-blue-500/30">
                          {m.type || "manhwa"}
                        </span>
                      </td>
                      <td className="p-3.5 font-bold text-white">
                        {m.chapters_count || 0} Chapters
                      </td>
                      <td className="p-3.5">
                        <span className="text-gray-300 font-semibold">
                          Every {m.scrape_interval_value || 7} {m.scrape_interval_unit || "days"}
                        </span>
                      </td>
                      <td className="p-3.5">
                        <span className="text-emerald-400 font-semibold">
                          {isPaused ? "Paused" : formatTimeRemaining(m.next_scrape_at)}
                        </span>
                      </td>
                      <td className="p-3.5">
                        <button
                          type="button"
                          onClick={() => handleToggleAutoScrape(m)}
                          className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase transition ${
                            !isPaused
                              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                              : "bg-gray-800 text-gray-400 border border-gray-700"
                          }`}
                        >
                          {!isPaused ? "Active" : "Paused"}
                        </button>
                      </td>
                      <td className="p-3.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Link
                            to={`/manga/${m.id}`}
                            target="_blank"
                            className="p-2 rounded-xl bg-[#101216] hover:bg-[#00AEF0] text-[#00AEF0] hover:text-white border border-[#262a33] transition"
                            title="Directly View Manga Page"
                          >
                            <i className="fas fa-external-link-alt text-xs"></i>
                          </Link>
                          <button
                            type="button"
                            onClick={() => handleRescrape(m.id, m.title)}
                            className="p-2 rounded-xl bg-[#101216] hover:bg-[#00AEF0] text-gray-300 hover:text-white border border-[#262a33] transition"
                            title="Rescrape & sync now"
                          >
                            <i className="fas fa-sync-alt text-xs"></i>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleMirrorImages(m.id, m.title)}
                            className="p-2 rounded-xl bg-[#101216] hover:bg-[#00AEF0] text-gray-300 hover:text-white border border-[#262a33] transition"
                            title="Compress pictures stored on the source site"
                          >
                            <i className="fas fa-compress-arrows-alt text-xs"></i>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenLayout(m)}
                            className="p-2 rounded-xl bg-[#101216] hover:bg-[#1f2330] text-[#00AEF0] border border-[#262a33] transition"
                            title="Picture layout (spreads, reading direction)"
                          >
                            <i className="fas fa-columns text-xs"></i>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenEditSchedule(m)}
                            className="p-2 rounded-xl bg-[#101216] hover:bg-[#1f2330] text-[#00AEF0] border border-[#262a33] transition"
                            title="Edit schedule"
                          >
                            <i className="fas fa-clock text-xs"></i>
                          </button>
                          {canTakedown && (
                            <button
                              type="button"
                              onClick={() => setTakedownManga(m)}
                              className={`p-2 rounded-xl bg-[#101216] hover:bg-amber-500 hover:text-white border border-[#262a33] transition ${
                                m.takedown_status === "taken_down" ? "text-red-400" : m.takedown_status === "requested" ? "text-amber-400" : "text-gray-300"
                              }`}
                              title={`Takedown (${m.takedown_status || "none"})`}
                            >
                              <i className="fas fa-ban text-xs"></i>
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => handleDelete(m.id, m.title)}
                            className="p-2 rounded-xl bg-red-500/10 hover:bg-red-500 text-red-400 hover:text-white border border-red-500/30 transition"
                            title="Delete"
                          >
                            <i className="fas fa-trash-alt text-xs"></i>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Import & Auto Chapter Detection Modal */}
      {importModalOpen && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <form
            onSubmit={handleAddSeries}
            className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-lg w-full max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain p-6 space-y-4 shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-[#00AEF0]/20 border border-[#00AEF0]/40 flex items-center justify-center text-sm text-[#00AEF0]">
                  <i className="fas fa-spider"></i>
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">Import &amp; Auto-Scrape Series</h3>
                  <p className="text-[11px] text-[#8b93a3]">
                    Automatically crawls and ingests all available chapters from the target source.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setImportModalOpen(false)}
                className="text-gray-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs">
              {/* 1. MangaUpdates Series URL (Metadata Only) */}
              <div>
                <label className="font-semibold text-purple-400 flex items-center justify-between mb-1">
                  <span>Metadata link: MangaUpdates or Anime-Planet (metadata only)</span>
                  <span className="text-[10px] text-gray-400">one link per series</span>
                </label>
                <input
                  type="url"
                  value={mangaupdatesUrl}
                  onChange={(e) => setMangaupdatesUrl(e.target.value)}
                  placeholder="https://www.mangaupdates.com/series/… or https://www.anime-planet.com/manga/…"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-purple-500/40 text-xs text-white focus:outline-none focus:border-purple-400 font-mono"
                />
              </div>

              {/* 2. Target Website Base URL */}
              <div>
                <label className="font-semibold text-gray-300 block mb-1">
                  Target Source Base URL <span className="text-[#00AEF0]">*</span>
                </label>
                <input
                  type="url"
                  required
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="e.g. https://baozimh.com or https://rawkuma.com"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                />
              </div>

              {/* 2. Manga / Series URL */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="font-semibold text-gray-300 block">
                    Manga / Series URL <span className="text-[#00AEF0]">*</span>
                  </label>
                  <button
                    type="button"
                    onClick={handleTestPreview}
                    disabled={isPreviewing || (!seriesUrl.trim() && !baseUrl.trim())}
                    className="text-[11px] font-bold text-[#00AEF0] hover:underline flex items-center gap-1 disabled:opacity-50"
                  >
                    <i className={isPreviewing ? "fas fa-spinner fa-spin" : "fas fa-search"}></i>
                    <span>{isPreviewing ? "Analyzing…" : "Test & Live Preview Extraction"}</span>
                  </button>
                </div>
                <input
                  type="url"
                  required
                  value={seriesUrl}
                  onChange={(e) => setSeriesUrl(e.target.value)}
                  placeholder="e.g. https://asuracomic.net/series/solo-leveling-abc or https://mangadex.org/title/..."
                  className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                />
              </div>

              {/* Live Preview Extraction Box */}
              {previewData && (
                <div className="p-3.5 rounded-xl bg-[#101216] border border-emerald-500/40 space-y-2.5 animate-in fade-in">
                  <div className="flex items-center justify-between border-b border-[#262a33] pb-2">
                    <span className="text-[11px] font-extrabold text-emerald-400 flex items-center gap-1.5">
                      <i className="fas fa-check-circle"></i>
                      <span>Extraction Validated: {previewData.detectedChapterCount} Total Chapters Detected</span>
                    </span>
                    <span className="text-[10px] text-gray-400 font-mono">100% Full Uncapped Pull</span>
                  </div>

                  <div className="flex gap-3">
                    <img
                      src={previewData.coverImage || previewData.cover_url || previewData.cover || PAGE_PLACEHOLDER}
                      alt="Cover Preview"
                      className="w-16 h-24 object-cover rounded-lg border border-[#262a33] flex-none shadow-md"
                      referrerPolicy="no-referrer"
                      onError={(e) => {
                        e.currentTarget.onerror = null;
                        e.currentTarget.src = PAGE_PLACEHOLDER;
                      }}
                    />
                    <div className="min-w-0 space-y-1">
                      <div className="font-bold text-white text-xs truncate">{previewData.title}</div>
                      <div className="text-[10px] text-gray-400">Author: <span className="text-gray-200">{previewData.author || "Auto-parsed"}</span></div>
                      <div className="flex gap-1 flex-wrap">
                        {(previewData.genres || []).map((g, idx) => (
                          <span key={idx} className="text-[9px] px-1.5 py-0.5 rounded bg-[#1f2330] text-gray-300 border border-[#262a33]">{g}</span>
                        ))}
                      </div>
                      {previewData.description && (
                        <p className="text-[10px] text-gray-400 line-clamp-2 leading-relaxed">{previewData.description}</p>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* 3. Title & Total Chapters to Scrape */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="font-semibold text-gray-300 block mb-1">Series Title (Optional)</label>
                  <input
                    type="text"
                    value={customTitle}
                    onChange={(e) => setCustomTitle(e.target.value)}
                    placeholder="Auto-detected from URL if blank"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  />
                </div>

                <div>
                  <label className="font-semibold text-gray-300 block mb-1">
                    Chapters to Scrape (e.g. 279)
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={customChapterCount}
                    onChange={(e) => setCustomChapterCount(e.target.value)}
                    placeholder="e.g. 279 (or leave blank to auto-detect all)"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                  />
                </div>
              </div>

              {/* Content Origin & Author */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="font-semibold text-gray-300 block mb-1">Content Origin / Type</label>
                  <select
                    value={type}
                    onChange={(e) => setType(e.target.value)}
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  >
                    <option value="manhwa">Korean Manhwa (Vertical Webtoon)</option>
                    <option value="manga">Japanese Manga (Black &amp; White)</option>
                    <option value="manhua">Chinese Manhua (Color Comic)</option>
                  </select>
                </div>

                <div>
                  <label className="font-semibold text-gray-300 block mb-1">Text language on pages</label>
                  <select
                    value={textLanguage}
                    onChange={(e) => setTextLanguage(e.target.value)}
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  >
                    <option value="">Auto-detect</option>
                    <option value="ko">Korean</option>
                    <option value="ja">Japanese</option>
                    <option value="zh">Chinese</option>
                    <option value="en">English</option>
                  </select>
                  <p className="text-[10px] text-[#8b93a3] mt-1">
                    What the lettering on the source site is written in. It can differ from the origin
                    (e.g. a Chinese manhua on a Korean site). Used by OCR.
                  </p>
                </div>

                <div>
                  <label className="font-semibold text-gray-300 block mb-1">Author Name (Optional)</label>
                  <input
                    type="text"
                    value={customAuthor}
                    onChange={(e) => setCustomAuthor(e.target.value)}
                    placeholder="Auto-detected if blank"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  />
                </div>
              </div>

              {/* Page layout: grouping of one-page chapters, book-format scans */}
              <div>
                <label className="font-semibold text-gray-300 block mb-1">Page Layout</label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <select
                    value={groupSize}
                    onChange={(e) => setGroupSize(e.target.value)}
                    title="Merge consecutive source chapters into one long vertical chapter"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  >
                    <option value="">Keep source chapters as they are</option>
                    <option value="5">Group every 5 source chapters into 1</option>
                    <option value="10">Group every 10 source chapters into 1</option>
                    <option value="20">Group every 20 source chapters into 1</option>
                  </select>
                  <select
                    value={sourceFormat}
                    onChange={(e) => {
                      setSourceFormat(e.target.value);
                      if (e.target.value === "single" && !groupSize) setGroupSize("10");
                    }}
                    title="Tell the scraper how this website lays out its pictures"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  >
                    <option value="auto">Source format: detect automatically</option>
                    <option value="vertical">Vertical strips / normal pages (keep as is)</option>
                    <option value="double">Book format: two pages per picture (split)</option>
                    <option value="single">One page per chapter (group chapters)</option>
                  </select>
                  <select
                    value={readingDir}
                    onChange={(e) => setReadingDir(e.target.value)}
                    title="Which half of a two-page scan is read first"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  >
                    <option value="auto">Reading order: automatic (by type)</option>
                    <option value="rtl">Right-to-left (Japanese manga)</option>
                    <option value="ltr">Left-to-right (manhwa / manhua)</option>
                  </select>
                </div>
                {groupSize && (
                  <p className="text-[11px] text-gray-500 mt-1.5">
                    Chapters are merged in order (1, 2, 3 …) into one long top-to-bottom chapter. Full groups
                    are published as they complete; the last partial group appears once enough chapters exist
                    or the series is marked completed.
                  </p>
                )}
              </div>

              {/* 4. Scraper Schedule */}
              <div>
                <label className="font-semibold text-gray-300 block mb-1">Scraper Crawl Schedule</label>
                <div className="flex gap-2">
                  <input
                    type="number"
                    min={1}
                    value={customVal}
                    onChange={(e) => setCustomVal(Number(e.target.value))}
                    className="w-1/2 px-3 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                    placeholder="e.g. 30"
                  />
                  <select
                    value={customUnit}
                    onChange={(e) => setCustomUnit(e.target.value)}
                    className="w-1/2 px-3 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  >
                    <option value="minutes">Minutes</option>
                    <option value="hours">Hours</option>
                    <option value="days">Days</option>
                  </select>
                </div>
              </div>

              {/* 5. Automatic Chapter Detection Badge */}
              <div className="p-3.5 bg-[#00AEF0]/10 border border-[#00AEF0]/30 rounded-xl space-y-1">
                <div className="flex items-center gap-2 text-[#00AEF0] font-bold text-xs">
                  <i className="fas fa-magic"></i>
                  <span>Uncapped Full Chapter Ingestion</span>
                </div>
                <p className="text-[11px] text-gray-300 leading-relaxed">
                  The scraper crawls and ingests all available chapters (e.g. all 279 chapters) into the database with authentic reading strips and sequential chapter numbering.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setImportModalOpen(false)}
                className="px-4 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-gray-300 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={adding}
                className="px-5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs transition flex items-center gap-1.5 shadow-lg disabled:opacity-50"
              >
                <i className={adding ? "fas fa-spinner fa-spin" : "fas fa-spider"}></i>
                <span>{adding ? "Scanning & Ingesting…" : "Start Auto-Scrape"}</span>
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Edit Schedule Modal */}
      {editingManga && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <form
            onSubmit={handleSaveSchedule}
            className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-md w-full max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain p-6 space-y-4 shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <div>
                <h3 className="text-sm font-bold text-white">Edit Scraper Schedule</h3>
                <p className="text-[11px] text-[#8b93a3]">{editingManga.title}</p>
              </div>
              <button type="button" onClick={() => setEditingManga(null)} className="text-gray-400 hover:text-white">✕</button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-semibold text-gray-300 block mb-1">Crawl Interval Value</label>
                <div className="flex gap-2">
                  <input
                    type="number"
                    min={1}
                    value={editVal}
                    onChange={(e) => setEditVal(e.target.value)}
                    className="w-1/2 px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  />
                  <select
                    value={editUnit}
                    onChange={(e) => setEditUnit(e.target.value)}
                    className="w-1/2 px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  >
                    <option value="minutes">Minutes</option>
                    <option value="hours">Hours</option>
                    <option value="days">Days</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="flex items-center gap-2 cursor-pointer pt-2">
                  <input
                    type="checkbox"
                    checked={editEnabled}
                    onChange={(e) => setEditEnabled(e.target.checked)}
                    className="rounded border-[#262a33] text-[#00AEF0] focus:ring-0"
                  />
                  <span className="font-semibold text-gray-200">Auto-Scrape Timer Enabled</span>
                </label>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setEditingManga(null)}
                className="px-4 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-gray-300 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={savingSchedule}
                className="px-5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs transition"
              >
                {savingSchedule ? "Saving…" : "Save Schedule"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Picture Layout Modal */}
      {takedownManga && (
        <TakedownPanel
          manga={takedownManga}
          onClose={() => setTakedownManga(null)}
          onSaved={(_res, status) => {
            setNotice({ type: "success", message: `Takedown status of "${takedownManga.title}" is now ${status}.` });
            setTakedownManga(null);
            queryClient.invalidateQueries({ queryKey: ["mangaCatalogAdmin"] });
          }}
        />
      )}
      {layoutManga && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <form
            onSubmit={handleSaveLayout}
            className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-md w-full max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain p-6 space-y-4 shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <div>
                <h3 className="text-sm font-bold text-white">Picture Layout</h3>
                <p className="text-[11px] text-[#8b93a3]">{layoutManga.title}</p>
              </div>
              <button type="button" onClick={() => setLayoutManga(null)} className="text-gray-400 hover:text-white">✕</button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-semibold text-gray-300 block mb-1">Two-page scans</label>
                <select
                  value={layoutSpread}
                  onChange={(e) => setLayoutSpread(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                >
                  <option value="auto">Split wide images automatically</option>
                  <option value="always">Always split (book format)</option>
                  <option value="never">Never split</option>
                </select>
              </div>
              <div>
                <label className="font-semibold text-gray-300 block mb-1">Reading direction (which half comes first)</label>
                <select
                  value={layoutDirection}
                  onChange={(e) => setLayoutDirection(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                >
                  <option value="rtl">Right to left (manga)</option>
                  <option value="ltr">Left to right (manhwa, manhua)</option>
                </select>
              </div>
              <div>
                <label className="font-semibold text-gray-300 block mb-1">Text language on pages (for OCR)</label>
                <select
                    value={layoutTextLanguage}
                    onChange={(e) => setLayoutTextLanguage(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                  >
                    <option value="">Auto-detect</option>
                    <option value="ko">Korean</option>
                    <option value="ja">Japanese</option>
                    <option value="zh">Chinese</option>
                    <option value="en">English</option>
                  </select>
              </div>
              <p className="text-[11px] text-[#8b93a3]">
                Changing the split or direction rebuilds this series' stored pictures from the source site in the background. Chapter grouping is fixed at import and cannot be changed here.
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setLayoutManga(null)}
                className="px-4 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-gray-300 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={savingLayout}
                className="px-5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs transition"
              >
                {savingLayout ? "Saving…" : "Save Layout"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
