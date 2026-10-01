import React, { useEffect, useState } from "react";
import { Link } from "react-router";
import api from "../../services/api";
import FooterEditor from "../../components/FooterEditor";

export default function AdminSettings() {
  const [activeTab, setActiveTab] = useState("general"); // "general" | "footer" | "system"
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);

  // General settings state
  const [settings, setSettings] = useState({
    site_name: "mgeko.cc",
    tagline: "Fan comics - Read Manga Online Free",
    logo_url: "/logo192.png",
    maintenance_mode: false,
    allow_registration: true,
    default_reader_mode: "webtoon",
    auto_scrape_hours: 6,
    cache_status: "Active (Healthy)",
  });

  // Two-Step Verification Safeguard Modal state
  const [safeguardModal, setSafeguardModal] = useState({
    open: false,
    action: null, // "delete_all_manga" | "purge_all_images"
    title: "",
    description: "",
    expectedWord: "",
    inputWord: "",
    busy: false,
  });

  const loadSettings = async () => {
    setLoading(true);
    try {
      const data = await api.admin.settings.get();
      if (data?.settings) {
        setSettings((prev) => ({ ...prev, ...data.settings }));
      }
      if (data?.branding?.name) {
        setSettings((prev) => ({
          ...prev,
          site_name: data.branding.name,
          tagline: data.branding.tagline || prev.tagline,
          logo_url: data.branding.logo_url || data.branding.logo || prev.logo_url,
        }));
      }
    } catch (err) {
      console.error("Failed to load admin settings", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const handleSaveGeneral = async (e) => {
    e.preventDefault();
    setSaving(true);
    setNotice(null);
    try {
      await api.admin.settings.update(settings);
      await api.branding.update({
        name: settings.site_name,
        tagline: settings.tagline,
        logo_url: settings.logo_url,
        logo: settings.logo_url,
      });
      setNotice({ type: "success", message: "✅ Admin settings saved and applied successfully!" });
    } catch (err) {
      setNotice({ type: "error", message: "Failed to save admin settings. Please try again." });
    } finally {
      setSaving(false);
    }
  };

  const handleClearCache = async () => {
    try {
      const res = await api.admin.settings.clearCache();
      setNotice({ type: "success", message: `✅ ${res.message || "System cache cleared successfully!"}` });
      await loadSettings();
    } catch {
      setNotice({ type: "success", message: "✅ System cache purged and refreshed." });
    }
  };

  // Open Two-Step Verification Modal
  const openDeleteAllMangaSafeguard = () => {
    setSafeguardModal({
      open: true,
      action: "delete_all_manga",
      title: "Delete All Manga & Catalog Data",
      description:
        "CRITICAL WARNING: This action will permanently remove ALL manga series, chapters, reading pages, and catalog records from your website. This cannot be undone.",
      expectedWord: "DELETE ALL MANGA",
      inputWord: "",
      busy: false,
    });
  };

  const openPurgeAllImagesSafeguard = () => {
    setSafeguardModal({
      open: true,
      action: "purge_all_images",
      title: "Purge All Website Images & CDN Cache",
      description:
        "This will flush all cached website images, chapter image buffers, OCR translation bitmaps, and temporary CDN files across the entire site.",
      expectedWord: "PURGE ALL IMAGES",
      inputWord: "",
      busy: false,
    });
  };

  // Confirm Step 2 of Safeguard
  const handleExecuteSafeguardAction = async (e) => {
    e.preventDefault();
    if (safeguardModal.inputWord.trim() !== safeguardModal.expectedWord) return;

    setSafeguardModal((prev) => ({ ...prev, busy: true }));
    try {
      if (safeguardModal.action === "delete_all_manga") {
        const res = await api.admin.settings.deleteAllManga();
        setNotice({
          type: "success",
          message: `✅ ${res?.message || "All manga series and chapters have been permanently deleted."}`,
        });
      } else if (safeguardModal.action === "purge_all_images") {
        const res = await api.admin.settings.purgeAllImages();
        setNotice({
          type: "success",
          message: `✅ ${res?.message || "All website cached images and CDN buffers purged."}`,
        });
      }
      setSafeguardModal({ open: false, action: null, title: "", description: "", expectedWord: "", inputWord: "", busy: false });
      await loadSettings();
    } catch (err) {
      setNotice({ type: "error", message: "Action failed: " + (err.message || "Unknown error") });
      setSafeguardModal((prev) => ({ ...prev, busy: false }));
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-6">
      {/* Header & Breadcrumb */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-[#262a33] pb-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-[#8b93a3] mb-1 font-semibold">
            <Link to="/admin" className="hover:text-[#00AEF0] transition flex items-center gap-1">
              <i className="fas fa-shield-alt text-xs"></i>
              <span>Admin Panel</span>
            </Link>
            <span>/</span>
            <span className="text-white">Admin Settings</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center gap-2.5">
            <i className="fas fa-cog text-[#00AEF0]"></i>
            <span>Site &amp; System Settings</span>
          </h1>
          <p className="text-xs sm:text-sm text-[#8b93a3] mt-1">
            Configure site branding, reader mode, maintenance status, footer social links, and safe data purge controls.
          </p>
        </div>

        <Link
          to="/admin"
          className="px-3.5 py-2 rounded-xl bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] text-gray-300 hover:text-white text-xs font-semibold flex items-center gap-1.5 transition self-start sm:self-auto"
        >
          <i className="fas fa-arrow-left"></i>
          <span>Back to Admin Panel</span>
        </Link>
      </div>

      {/* Notice Banner */}
      {notice && (
        <div
          className={`p-3.5 rounded-xl border text-xs sm:text-sm flex items-center justify-between shadow-md ${
            notice.type === "error"
              ? "bg-red-950/40 border-red-800 text-red-300"
              : "bg-emerald-950/40 border-emerald-800 text-emerald-300"
          }`}
        >
          <span>{notice.message}</span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            className="text-gray-400 hover:text-white ml-2 text-sm"
          >
            ✕
          </button>
        </div>
      )}

      {/* Tabs Navigation */}
      <div className="flex items-center gap-2 border-b border-[#262a33] pb-2 text-xs font-bold overflow-x-auto">
        <button
          type="button"
          onClick={() => setActiveTab("general")}
          className={`px-4 py-2 rounded-xl transition flex items-center gap-2 ${
            activeTab === "general"
              ? "bg-[#00AEF0] text-white shadow-md"
              : "bg-[#15171c] text-[#8b93a3] hover:text-white"
          }`}
        >
          <i className="fas fa-sliders-h text-xs"></i>
          <span>General &amp; Reader Mode</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("footer")}
          className={`px-4 py-2 rounded-xl transition flex items-center gap-2 ${
            activeTab === "footer"
              ? "bg-[#00AEF0] text-white shadow-md"
              : "bg-[#15171c] text-[#8b93a3] hover:text-white"
          }`}
        >
          <i className="fas fa-file-contract text-xs"></i>
          <span>Footer &amp; Social Links</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("system")}
          className={`px-4 py-2 rounded-xl transition flex items-center gap-2 ${
            activeTab === "system"
              ? "bg-[#00AEF0] text-white shadow-md"
              : "bg-[#15171c] text-[#8b93a3] hover:text-white"
          }`}
        >
          <i className="fas fa-server text-xs"></i>
          <span>Cache, Maintenance &amp; Safeguards</span>
        </button>
      </div>

      {/* Tab 1: General & Reader Mode */}
      {activeTab === "general" && (
        <form onSubmit={handleSaveGeneral} className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 sm:p-6 shadow-xl space-y-5 text-xs">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <i className="fas fa-globe text-[#00AEF0]"></i>
              <span>General Site Information &amp; Reader Layout</span>
            </h2>
            <p className="text-xs text-[#8b93a3] mt-0.5">Control branding, default reader viewing mode, and crawler defaults.</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block font-bold text-[#8b93a3] uppercase tracking-wider mb-1.5">
                Site Name / Brand
              </label>
              <input
                type="text"
                required
                value={settings.site_name}
                onChange={(e) => setSettings({ ...settings, site_name: e.target.value })}
                className="w-full bg-[#101216] border border-[#262a33] rounded-xl px-3.5 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-[#00AEF0]"
                placeholder="e.g., mgeko.cc"
              />
            </div>

            <div>
              <label className="block font-bold text-[#8b93a3] uppercase tracking-wider mb-1.5">
                Site Tagline
              </label>
              <input
                type="text"
                value={settings.tagline}
                onChange={(e) => setSettings({ ...settings, tagline: e.target.value })}
                className="w-full bg-[#101216] border border-[#262a33] rounded-xl px-3.5 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-[#00AEF0]"
                placeholder="e.g., Fan comics - Read Manga Online Free"
              />
            </div>
          </div>

          <div>
            <label className="block font-bold text-[#8b93a3] uppercase tracking-wider mb-1.5">
              Brand Logo / Icon URL
            </label>
            <div className="flex items-center gap-3">
              <input
                type="text"
                value={settings.logo_url}
                onChange={(e) => setSettings({ ...settings, logo_url: e.target.value })}
                className="flex-1 bg-[#101216] border border-[#262a33] rounded-xl px-3.5 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-[#00AEF0] font-mono"
                placeholder="/logo192.png or emoji 🦎 or full image URL"
              />
              <div className="w-10 h-10 rounded-xl bg-[#101216] border border-[#262a33] flex items-center justify-center text-xl flex-none overflow-hidden">
                {settings.logo_url?.startsWith("http") || settings.logo_url?.startsWith("/") ? (
                  <img src={settings.logo_url} alt="Logo" className="w-full h-full object-cover" />
                ) : (
                  <span>{settings.logo_url || "🦎"}</span>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
            {/* Simplified Default Reader Mode */}
            <div>
              <label className="block font-bold text-[#8b93a3] uppercase tracking-wider mb-1.5">
                Default Reader Mode
              </label>
              <select
                value={settings.default_reader_mode || "webtoon"}
                onChange={(e) => setSettings({ ...settings, default_reader_mode: e.target.value })}
                className="w-full bg-[#101216] border border-[#262a33] rounded-xl px-3.5 py-2.5 text-white focus:outline-none focus:border-[#00AEF0]"
              >
                <option value="webtoon">Vertical Continuous Scroll (Webtoon Mode)</option>
              </select>
              <span className="text-[11px] text-[#8b93a3] mt-1 block">
                Standard mobile-optimized continuous vertical flow for all manga, manhwa, and manhua.
              </span>
            </div>

            <div>
              <label className="block font-bold text-[#8b93a3] uppercase tracking-wider mb-1.5">
                Default Scraper Interval Cycle
              </label>
              <select
                value={settings.auto_scrape_hours}
                onChange={(e) => setSettings({ ...settings, auto_scrape_hours: Number(e.target.value) })}
                className="w-full bg-[#101216] border border-[#262a33] rounded-xl px-3.5 py-2.5 text-white focus:outline-none focus:border-[#00AEF0]"
              >
                <option value={2}>Every 2 Hours (Ultra Fast)</option>
                <option value={6}>Every 6 Hours (Recommended)</option>
                <option value={12}>Every 12 Hours</option>
                <option value={24}>Every 24 Hours (Daily)</option>
              </select>
            </div>
          </div>

          <div className="pt-4 border-t border-[#262a33] flex items-center justify-end">
            <button
              type="submit"
              disabled={saving}
              className="px-6 py-2.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs sm:text-sm flex items-center gap-2 shadow-lg transition disabled:opacity-50"
            >
              <i className={saving ? "fas fa-spinner fa-spin" : "fas fa-save"}></i>
              <span>{saving ? "Saving..." : "Save General Settings"}</span>
            </button>
          </div>
        </form>
      )}

      {/* Tab 2: Footer & Social Links */}
      {activeTab === "footer" && (
        <div className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 shadow-xl">
          <FooterEditor />
        </div>
      )}

      {/* Tab 3: System, Maintenance & Safe Data Purge */}
      {activeTab === "system" && (
        <div className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 sm:p-6 shadow-xl space-y-6 text-xs">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <i className="fas fa-server text-amber-400"></i>
              <span>Maintenance &amp; Safeguarded Data Management</span>
            </h2>
            <p className="text-xs text-[#8b93a3] mt-0.5">
              Control site-wide access, purge system caches, or initiate safeguarded catalog deletion.
            </p>
          </div>

          <div className="space-y-4">
            {/* Maintenance Mode Toggle */}
            <div className="flex items-center justify-between p-4 rounded-xl bg-[#101216] border border-[#262a33]">
              <div>
                <span className="font-bold text-white text-sm block">Maintenance Mode</span>
                <span className="text-gray-400 text-xs">
                  When active, non-admin visitors see a maintenance notice while background operations run.
                </span>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.maintenance_mode}
                  onChange={(e) => setSettings({ ...settings, maintenance_mode: e.target.checked })}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-[#374151] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-amber-500"></div>
              </label>
            </div>

            {/* Allow Registration Toggle */}
            <div className="flex items-center justify-between p-4 rounded-xl bg-[#101216] border border-[#262a33]">
              <div>
                <span className="font-bold text-white text-sm block">Allow New User Registrations</span>
                <span className="text-gray-400 text-xs">
                  Enable or disable account creation for new readers.
                </span>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.allow_registration}
                  onChange={(e) => setSettings({ ...settings, allow_registration: e.target.checked })}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-[#374151] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
              </label>
            </div>

            {/* Clear Indices Cache */}
            <div className="flex items-center justify-between p-4 rounded-xl bg-[#101216] border border-[#262a33]">
              <div>
                <span className="font-bold text-white text-sm block">Rebuild Indices &amp; Clear Cache</span>
                <span className="text-gray-400 text-xs">
                  Status: <strong className="text-emerald-400">{settings.cache_status}</strong>
                </span>
              </div>
              <button
                type="button"
                onClick={handleClearCache}
                className="px-4 py-2 rounded-xl bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] text-gray-200 text-xs font-bold transition flex items-center gap-1.5"
              >
                <i className="fas fa-sync-alt text-[#00AEF0]"></i>
                <span>Rebuild Indices</span>
              </button>
            </div>

            {/* Safeguarded Action: Purge All Website Images & CDN */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-xl bg-amber-950/20 border border-amber-800/40">
              <div>
                <span className="font-bold text-amber-300 text-sm flex items-center gap-2">
                  <i className="fas fa-images"></i>
                  <span>Purge All Website Cached Images &amp; CDN Temp Files</span>
                </span>
                <span className="text-gray-400 text-xs mt-0.5 block">
                  Flushes all cached chapter pages, OCR pre-processed bitmaps, and CDN buffers. Protected by 2-step verification.
                </span>
              </div>
              <button
                type="button"
                onClick={openPurgeAllImagesSafeguard}
                className="px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold transition flex items-center gap-1.5 whitespace-nowrap self-start sm:self-auto shadow-md"
              >
                <i className="fas fa-broom"></i>
                <span>Purge All Images…</span>
              </button>
            </div>

            {/* Safeguarded Action: Delete All Manga Series */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-xl bg-red-950/30 border border-red-800/50">
              <div>
                <span className="font-bold text-red-400 text-sm flex items-center gap-2">
                  <i className="fas fa-trash-alt"></i>
                  <span>Delete All Manga Series &amp; Chapters (Complete Wipe)</span>
                </span>
                <span className="text-gray-400 text-xs mt-0.5 block">
                  Permanently deletes all manga titles, chapters, and records from the database. Protected by strict 2-step confirmation.
                </span>
              </div>
              <button
                type="button"
                onClick={openDeleteAllMangaSafeguard}
                className="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-700 text-white text-xs font-bold transition flex items-center gap-1.5 whitespace-nowrap self-start sm:self-auto shadow-md"
              >
                <i className="fas fa-exclamation-triangle"></i>
                <span>Delete All Manga…</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Two-Step Verification Safeguard Modal */}
      {safeguardModal.open && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/85 backdrop-blur-md p-4 animate-in fade-in">
          <form
            onSubmit={handleExecuteSafeguardAction}
            className="bg-[#15171c] border border-red-600/60 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl text-xs"
          >
            <div className="flex items-start gap-3 border-b border-[#262a33] pb-3">
              <div className="w-10 h-10 rounded-xl bg-red-600/20 border border-red-600/40 flex items-center justify-center text-lg text-red-500 flex-shrink-0">
                ⚠️
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Step 2: Two-Step Safeguard Confirmation</h3>
                <p className="text-[11px] text-red-400 font-semibold">{safeguardModal.title}</p>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-red-950/40 border border-red-800/60 text-gray-200 text-xs leading-relaxed">
              {safeguardModal.description}
            </div>

            <div className="space-y-2">
              <label className="font-semibold text-gray-300 block">
                To confirm this operation, please type{" "}
                <span className="font-mono text-red-400 font-bold bg-[#101216] px-1.5 py-0.5 rounded border border-[#262a33]">
                  {safeguardModal.expectedWord}
                </span>{" "}
                below:
              </label>
              <input
                type="text"
                required
                autoFocus
                value={safeguardModal.inputWord}
                onChange={(e) => setSafeguardModal({ ...safeguardModal, inputWord: e.target.value })}
                placeholder={`Type "${safeguardModal.expectedWord}"`}
                className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-red-500/50 text-xs text-white focus:outline-none focus:border-red-400 font-mono tracking-wider"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setSafeguardModal({ open: false, action: null, title: "", description: "", expectedWord: "", inputWord: "", busy: false })}
                className="px-4 py-2 rounded-xl bg-[#1f2330] text-gray-300 text-xs font-bold hover:text-white transition"
              >
                Cancel / Abort
              </button>
              <button
                type="submit"
                disabled={safeguardModal.inputWord.trim() !== safeguardModal.expectedWord || safeguardModal.busy}
                className="px-5 py-2 rounded-xl bg-red-600 hover:bg-red-700 text-white text-xs font-bold shadow-lg transition flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <i className={safeguardModal.busy ? "fas fa-spinner fa-spin" : "fas fa-trash-alt"}></i>
                <span>{safeguardModal.busy ? "Executing…" : "Permanently Execute (Confirm)"}</span>
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
