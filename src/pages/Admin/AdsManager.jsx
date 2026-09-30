import React, { useState, useRef, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../../services/api";

const PREVIEW_PAGES = [
  { id: "homepage", label: "Homepage", defaultPlacement: "homepage_top" },
  { id: "reader", label: "Chapter Reader", defaultPlacement: "reader_sidebar" },
  { id: "manga_detail", label: "Manga Detail", defaultPlacement: "manga_detail_header" },
  { id: "browse", label: "Browse Catalog", defaultPlacement: "browse_top" },
];

export default function AdsManager() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("slots"); // "slots" | "manager"
  const [previewPage, setPreviewPage] = useState("homepage");
  const [notice, setNotice] = useState(null);

  // --- Visual Canvas Drag State ---
  const canvasRef = useRef(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPos, setStartPos] = useState({ x: 0, y: 0 });
  const [currentRect, setCurrentRect] = useState(null); // { x, y, width, height }
  const [newSlotModal, setNewSlotModal] = useState(null);
  const [newSlotName, setNewSlotName] = useState("");
  const [newSlotKey, setNewSlotKey] = useState("");

  // --- Global AdSense / Multiple Auto-Ads Networks State ---
  const [newNetworkName, setNewNetworkName] = useState("");
  const [newNetworkPublisherId, setNewNetworkPublisherId] = useState("");
  const [newNetworkScript, setNewNetworkScript] = useState("");
  const [newNetworkFallbackUrl, setNewNetworkFallbackUrl] = useState("https://images.unsplash.com/photo-1563089145-599997674d42?w=1200&auto=format&fit=crop&q=80");
  const [newNetworkFallbackLink, setNewNetworkFallbackLink] = useState("https://google.com");

  // --- Fetch Ad Slots ---
  const { data: slotsData = [], isLoading: loadingSlots } = useQuery({
    queryKey: ["adSlotsList"],
    queryFn: () => api.adSlots.list(),
  });

  const slots = useMemo(() => (Array.isArray(slotsData) ? slotsData : []), [slotsData]);

  // --- Fetch Global Auto-Ad Networks ---
  const { data: networksData = [], isLoading: loadingNetworks } = useQuery({
    queryKey: ["globalNetworksList"],
    queryFn: async () => {
      try {
        const res = await fetch("/api/v1/ads/global-networks");
        return res.ok ? await res.json() : [];
      } catch {
        return [];
      }
    },
  });

  const networks = useMemo(() => (Array.isArray(networksData) ? networksData : []), [networksData]);

  // --- Mutations ---
  const createSlotMutation = useMutation({
    mutationFn: (payload) => api.adSlots.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adSlotsList"] });
      setNotice({ type: "success", message: "✅ Visual Ad Slot saved at exact coordinates!" });
      setNewSlotModal(null);
      setCurrentRect(null);
    },
    onError: (err) => setNotice({ type: "error", message: err.message || "Failed to create slot" }),
  });

  const updateSlotMutation = useMutation({
    mutationFn: ({ id, payload }) => api.adSlots.update(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adSlotsList"] });
      setNotice({ type: "success", message: "✅ Ad slot updated successfully!" });
    },
    onError: (err) => setNotice({ type: "error", message: err.message || "Failed to update slot" }),
  });

  const deleteSlotMutation = useMutation({
    mutationFn: (id) => api.adSlots.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adSlotsList"] });
      setNotice({ type: "success", message: "🗑️ Ad slot deleted successfully." });
    },
    onError: (err) => setNotice({ type: "error", message: err.message || "Failed to delete slot" }),
  });

  // Global Network Mutations
  const createNetworkMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await fetch("/api/v1/ads/global-networks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["globalNetworksList"] });
      setNotice({ type: "success", message: "✅ Auto-Ad Network added successfully!" });
      setNewNetworkName("");
      setNewNetworkPublisherId("");
      setNewNetworkScript("");
    },
  });

  const deleteNetworkMutation = useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`/api/v1/ads/global-networks/${id}`, { method: "DELETE" });
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["globalNetworksList"] });
      setNotice({ type: "success", message: "🗑️ Auto-Ad Network removed." });
    },
  });

  const toggleNetworkMutation = useMutation({
    mutationFn: async ({ id, enabled }) => {
      const res = await fetch(`/api/v1/ads/global-networks/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["globalNetworksList"] });
    },
  });

  // --- Canvas Mouse Handlers ---
  const handleMouseDown = (e) => {
    if (!canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = Math.round(e.clientX - rect.left);
    const y = Math.round(e.clientY - rect.top);
    setStartPos({ x, y });
    setCurrentRect({ x, y, width: 0, height: 0 });
    setIsDrawing(true);
  };

  const handleMouseMove = (e) => {
    if (!isDrawing || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const currentX = Math.round(e.clientX - rect.left);
    const currentY = Math.round(e.clientY - rect.top);

    const x = Math.min(startPos.x, currentX);
    const y = Math.min(startPos.y, currentY);
    const width = Math.abs(currentX - startPos.x);
    const height = Math.abs(currentY - startPos.y);

    setCurrentRect({ x, y, width, height });
  };

  const handleMouseUp = () => {
    if (!isDrawing) return;
    setIsDrawing(false);
    if (currentRect && currentRect.width > 40 && currentRect.height > 25) {
      const autoKey = `slot_${previewPage}_${Date.now().toString().slice(-4)}`;
      const autoName = `${previewPage.replace("_", " ").toUpperCase()} Ad (${currentRect.width}x${currentRect.height})`;
      setNewSlotName(autoName);
      setNewSlotKey(autoKey);
      setNewSlotModal({
        ...currentRect,
        page_target: previewPage,
        placement:
          previewPage === "homepage"
            ? "homepage_top"
            : previewPage === "reader"
            ? "reader_sidebar"
            : previewPage === "manga_detail"
            ? "manga_detail_header"
            : "browse_top",
      });
    } else {
      setCurrentRect(null);
    }
  };

  const handleConfirmNewSlot = (e) => {
    e.preventDefault();
    if (!newSlotName.trim() || !newSlotKey.trim() || !newSlotModal) return;

    createSlotMutation.mutate({
      name: newSlotName.trim(),
      slot_key: newSlotKey.trim(),
      placement: newSlotModal.placement,
      page_target: previewPage,
      canvas_x: newSlotModal.x,
      canvas_y: newSlotModal.y,
      width_px: newSlotModal.width,
      height_px: newSlotModal.height,
      max_width_px: newSlotModal.width,
      type: "image",
      enabled: true,
      image_url: "https://images.unsplash.com/photo-1563089145-599997674d42?w=1200&auto=format&fit=crop&q=80",
      link_url: "https://google.com",
      alt_text: newSlotName,
    });
  };

  const handleAddNetwork = (e) => {
    e.preventDefault();
    if (!newNetworkName.trim()) return;
    createNetworkMutation.mutate({
      name: newNetworkName.trim(),
      publisher_id: newNetworkPublisherId.trim(),
      script_code: newNetworkScript.trim(),
      fallback_ad_url: newNetworkFallbackUrl.trim(),
      fallback_link: newNetworkFallbackLink.trim(),
      enabled: true,
    });
  };

  // Filter slots for current preview page
  const pageSpecificSlots = slots.filter(
    (s) => s.page_target === previewPage || (!s.page_target && previewPage === "homepage")
  );

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header & Sub-page Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#262a33] pb-4">
        <div>
          <Link to="/admin" className="text-xs text-[#00AEF0] hover:underline mb-1 block font-semibold">
            ← Back to Admin Console
          </Link>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center gap-2.5">
            <i className="fas fa-layer-group text-[#00AEF0]"></i>
            <span>Ad Management</span>
          </h1>
          <p className="text-xs sm:text-sm text-[#8b93a3] mt-0.5">
            Visually place custom rectangular slots on exact page layouts and manage your multi-network auto-ads.
          </p>
        </div>

        {/* Sub-Pages Selector */}
        <div className="flex rounded-xl bg-[#15171c] p-1 border border-[#262a33] text-xs font-bold">
          <button
            type="button"
            onClick={() => setActiveTab("slots")}
            className={`px-4 py-2 rounded-lg transition flex items-center gap-2 ${
              activeTab === "slots" ? "bg-[#00AEF0] text-white shadow" : "text-gray-400 hover:text-white"
            }`}
          >
            <i className="fas fa-vector-square"></i>
            <span>1. Ad Slots (Visual Drag Placer)</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("manager")}
            className={`px-4 py-2 rounded-lg transition flex items-center gap-2 ${
              activeTab === "manager" ? "bg-[#00AEF0] text-white shadow" : "text-gray-400 hover:text-white"
            }`}
          >
            <i className="fas fa-ad"></i>
            <span>2. Ad Manager &amp; Creatives</span>
          </button>
        </div>
      </div>

      {notice && (
        <div className={`p-3.5 rounded-xl border text-xs flex items-center justify-between shadow ${
          notice.type === "error" ? "bg-red-950/40 border-red-500/40 text-red-300" : "bg-emerald-950/40 border-emerald-500/40 text-emerald-300"
        }`}>
          <span>{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-gray-400 hover:text-white">✕</button>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SUB-PAGE 1: AD SLOTS (VISUAL DRAG CANVAS FOR ALL 4 PAGES)                 */}
      {/* ========================================================================= */}
      {activeTab === "slots" && (
        <div className="space-y-6 animate-in fade-in">
          {/* Target Page Selector Toolbar */}
          <div className="bg-[#15171c] border border-[#262a33] p-4 rounded-2xl flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-md">
            <div>
              <span className="text-xs font-bold text-white block">Visual Interactive Canvas</span>
              <p className="text-[11px] text-[#8b93a3]">
                Click and drag your mouse across the preview below to draw a rectangle where the ad will sit.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400 font-semibold">Select Page Layout:</span>
              <div className="flex gap-1.5 flex-wrap">
                {PREVIEW_PAGES.map((page) => (
                  <button
                    key={page.id}
                    type="button"
                    onClick={() => {
                      setPreviewPage(page.id);
                      setCurrentRect(null);
                    }}
                    className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 ${
                      previewPage === page.id
                        ? "bg-[#00AEF0] text-white shadow"
                        : "bg-[#101216] border border-[#262a33] text-gray-400 hover:text-white"
                    }`}
                  >
                    <i className={
                      page.id === "homepage"
                        ? "fas fa-home"
                        : page.id === "reader"
                        ? "fas fa-book-open"
                        : page.id === "manga_detail"
                        ? "fas fa-info-circle"
                        : "fas fa-th-list"
                    }></i>
                    <span>{page.label}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Interactive Webpage Mock Canvas with Distinct Visuals for all 4 pages */}
          <div className="bg-[#0b0d10] border-2 border-dashed border-[#00AEF0]/40 rounded-2xl p-4 shadow-2xl relative select-none">
            <div className="text-[10px] uppercase font-mono text-[#00AEF0] font-bold mb-2 flex items-center justify-between">
              <span>🖥️ {previewPage.toUpperCase()} Canvas — Click &amp; Drag Anywhere To Draw Ad Rectangle</span>
              <span className="text-gray-400">Target: {previewPage}</span>
            </div>

            <div
              ref={canvasRef}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              className="relative w-full h-[460px] bg-[#15171c] border border-[#262a33] rounded-xl overflow-hidden cursor-crosshair"
            >
              {/* PAGE 1 MOCK: HOMEPAGE */}
              {previewPage === "homepage" && (
                <div className="p-4 space-y-3 pointer-events-none opacity-40">
                  <div className="h-8 bg-[#101216] rounded-lg border border-[#262a33] flex items-center justify-between px-3">
                    <div className="w-24 h-3 bg-[#00AEF0] rounded"></div>
                    <div className="flex gap-2">
                      <div className="w-12 h-2.5 bg-gray-600 rounded"></div>
                      <div className="w-12 h-2.5 bg-gray-600 rounded"></div>
                    </div>
                  </div>
                  <div className="h-10 bg-[#101216] rounded-xl border border-blue-500/30 p-2 flex items-center gap-2">
                    <span className="text-xs">📢</span>
                    <div className="w-48 h-2.5 bg-gray-500 rounded"></div>
                  </div>
                  <div className="h-28 bg-[#101216] rounded-xl border border-[#262a33] p-2 flex gap-2 overflow-hidden">
                    {[1, 2, 3, 4, 5].map((i) => (
                      <div key={i} className="w-24 h-full bg-gray-800 rounded-lg flex-none"></div>
                    ))}
                  </div>
                  <div className="grid grid-cols-4 gap-2">
                    {[1, 2, 3, 4].map((i) => (
                      <div key={i} className="h-32 bg-[#101216] rounded-xl border border-[#262a33] p-2"></div>
                    ))}
                  </div>
                </div>
              )}

              {/* PAGE 2 MOCK: CHAPTER READER */}
              {previewPage === "reader" && (
                <div className="p-4 space-y-3 pointer-events-none opacity-40">
                  <div className="h-8 bg-[#101216] rounded-lg border border-[#262a33] flex items-center justify-between px-3">
                    <div className="w-36 h-3 bg-[#00AEF0] rounded"></div>
                    <div className="w-24 h-5 bg-gray-700 rounded"></div>
                  </div>
                  <div className="flex gap-4 h-[360px]">
                    <div className="flex-1 bg-[#101216] rounded-xl border border-[#262a33] flex flex-col items-center justify-center p-4">
                      <div className="w-3/4 h-full bg-gray-900 border border-gray-800 rounded-lg flex items-center justify-center text-gray-600 text-xs">
                        [Manga Chapter Page Strip]
                      </div>
                    </div>
                    <div className="w-48 bg-[#101216] rounded-xl border border-[#262a33] p-3 space-y-2">
                      <div className="w-full h-4 bg-gray-700 rounded"></div>
                      <div className="w-full h-24 bg-gray-800 rounded"></div>
                    </div>
                  </div>
                </div>
              )}

              {/* PAGE 3 MOCK: MANGA DETAIL */}
              {previewPage === "manga_detail" && (
                <div className="p-4 space-y-3 pointer-events-none opacity-40">
                  <div className="flex gap-4 h-48 bg-[#101216] rounded-xl border border-[#262a33] p-3">
                    <div className="w-32 h-full bg-gray-800 rounded-lg flex-none"></div>
                    <div className="flex-1 space-y-2">
                      <div className="w-48 h-5 bg-gray-400 rounded"></div>
                      <div className="w-32 h-3 bg-gray-600 rounded"></div>
                      <div className="w-full h-16 bg-gray-900 rounded"></div>
                    </div>
                  </div>
                  <div className="h-44 bg-[#101216] rounded-xl border border-[#262a33] p-3 space-y-2">
                    <div className="w-36 h-4 bg-[#00AEF0] rounded"></div>
                    <div className="grid grid-cols-3 gap-2">
                      {[1, 2, 3, 4, 5, 6].map((i) => (
                        <div key={i} className="h-8 bg-gray-800 rounded"></div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* PAGE 4 MOCK: BROWSE CATALOG */}
              {previewPage === "browse" && (
                <div className="p-4 space-y-3 pointer-events-none opacity-40">
                  <div className="h-16 bg-[#101216] rounded-xl border border-[#262a33] p-3 flex gap-3">
                    <div className="w-48 h-8 bg-gray-800 rounded"></div>
                    <div className="w-28 h-8 bg-gray-800 rounded"></div>
                    <div className="w-28 h-8 bg-gray-800 rounded"></div>
                  </div>
                  <div className="grid grid-cols-5 gap-2">
                    {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => (
                      <div key={i} className="h-32 bg-[#101216] rounded-xl border border-[#262a33] p-2"></div>
                    ))}
                  </div>
                </div>
              )}

              {/* Render Saved Slots at exact coordinates */}
              {pageSpecificSlots.map((slot) => {
                const hasCustomCoords = slot.canvas_x != null && slot.canvas_y != null && slot.width_px != null;
                return (
                  <div
                    key={slot.id}
                    className="absolute border-2 border-emerald-500 bg-emerald-500/20 rounded-lg p-2 text-emerald-300 font-bold text-xs flex flex-col justify-between shadow-lg pointer-events-none"
                    style={{
                      left: hasCustomCoords ? `${slot.canvas_x}px` : "5%",
                      top: hasCustomCoords ? `${slot.canvas_y}px` : "45px",
                      width: hasCustomCoords ? `${slot.width_px}px` : "90%",
                      height: hasCustomCoords ? `${slot.height_px}px` : "70px",
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <span className="bg-emerald-950/80 px-2 py-0.5 rounded text-[10px] font-mono border border-emerald-500/50">
                        🎯 {slot.name || slot.slot_key}
                      </span>
                      <span className="text-[10px] text-emerald-400 font-mono">
                        {slot.width_px || slot.max_width_px || 728}x{slot.height_px || 90}px
                      </span>
                    </div>
                    <span className="text-[9px] text-gray-300">Exact Canvas Bounding Box</span>
                  </div>
                );
              })}

              {/* Active Dragging Rectangle */}
              {currentRect && currentRect.width > 0 && (
                <div
                  className="absolute border-2 border-dashed border-[#00AEF0] bg-[#00AEF0]/25 rounded-lg pointer-events-none shadow-[0_0_15px_#00AEF0]"
                  style={{
                    left: `${currentRect.x}px`,
                    top: `${currentRect.y}px`,
                    width: `${currentRect.width}px`,
                    height: `${currentRect.height}px`,
                  }}
                >
                  <span className="absolute top-1 left-1 bg-black/80 text-[#00AEF0] text-[10px] font-mono font-bold px-1.5 py-0.5 rounded">
                    {currentRect.width} x {currentRect.height} px ({currentRect.x}, {currentRect.y})
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* New Slot Creation Dialog */}
          {newSlotModal && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
              <form
                onSubmit={handleConfirmNewSlot}
                className="bg-[#15171c] border border-[#00AEF0] p-6 rounded-2xl max-w-md w-full space-y-4 shadow-2xl"
              >
                <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <i className="fas fa-vector-square text-[#00AEF0]"></i>
                    <span>Confirm Visual Placement</span>
                  </h3>
                  <button type="button" onClick={() => setNewSlotModal(null)} className="text-gray-400 hover:text-white">✕</button>
                </div>

                <div className="p-3 bg-[#101216] border border-[#262a33] rounded-xl text-xs space-y-1">
                  <div className="flex justify-between text-gray-400 font-mono">
                    <span>Captured Dimensions:</span>
                    <strong className="text-white">{newSlotModal.width}px W × {newSlotModal.height}px H</strong>
                  </div>
                  <div className="flex justify-between text-gray-400 font-mono">
                    <span>Coordinates (X, Y):</span>
                    <strong className="text-[#00AEF0]">{newSlotModal.x}px, {newSlotModal.y}px</strong>
                  </div>
                  <div className="flex justify-between text-gray-400 font-mono">
                    <span>Target Page:</span>
                    <strong className="text-emerald-400 capitalize">{previewPage}</strong>
                  </div>
                </div>

                <div className="space-y-3 text-xs">
                  <div>
                    <label className="font-semibold text-gray-300 block mb-1">Ad Slot Name</label>
                    <input
                      type="text"
                      required
                      value={newSlotName}
                      onChange={(e) => setNewSlotName(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                    />
                  </div>

                  <div>
                    <label className="font-semibold text-gray-300 block mb-1">Unique Slot Key</label>
                    <input
                      type="text"
                      required
                      value={newSlotKey}
                      onChange={(e) => setNewSlotKey(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white font-mono focus:outline-none focus:border-[#00AEF0]"
                    />
                  </div>

                  <div>
                    <label className="font-semibold text-gray-300 block mb-1">Placement Section</label>
                    <select
                      value={newSlotModal.placement}
                      onChange={(e) => setNewSlotModal({ ...newSlotModal, placement: e.target.value })}
                      className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                    >
                      <option value="homepage_top">Homepage Header Leaderboard</option>
                      <option value="homepage_middle">Homepage Middle Banner</option>
                      <option value="reader_sidebar">Reader Sidebar Banner</option>
                      <option value="reader_between_pages">Reader Between-Pages Banner</option>
                      <option value="manga_detail_header">Manga Detail Header</option>
                      <option value="manga_detail_sidebar">Manga Detail Sidebar Sponsor</option>
                      <option value="browse_top">Browse Catalog Header</option>
                      <option value="browse_grid">Browse In-Grid Sponsor</option>
                      <option value="global_top">Global Top</option>
                      <option value="global_bottom">Global Bottom</option>
                    </select>
                  </div>
                </div>

                <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#262a33]">
                  <button
                    type="button"
                    onClick={() => setNewSlotModal(null)}
                    className="px-4 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-gray-300 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={createSlotMutation.isPending}
                    className="px-5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs shadow-lg transition"
                  >
                    {createSlotMutation.isPending ? "Saving..." : "Confirm & Save Exact Placement"}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Defined Slots List with Clear Delete Actions */}
          <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <i className="fas fa-list-ul text-[#00AEF0]"></i>
                <span>Defined Ad Slots ({slots.length})</span>
              </h3>
              <span className="text-xs text-[#8b93a3]">All active rectangular positions across all 4 layouts</span>
            </div>

            {loadingSlots ? (
              <div className="p-8 text-center text-xs text-[#8b93a3]">Loading slots…</div>
            ) : slots.length === 0 ? (
              <div className="p-8 text-center text-xs text-[#8b93a3]">
                No ad slots created yet. Select a page above and drag a rectangle to create one.
              </div>
            ) : (
              <div className="divide-y divide-[#262a33]">
                {slots.map((s) => (
                  <div key={s.id} className="py-3.5 flex items-center justify-between gap-4 flex-wrap">
                    <div className="space-y-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-sm">{s.name}</span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-blue-500/20 text-[#00AEF0] border border-blue-500/40">
                          {s.slot_key}
                        </span>
                        <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-gray-800 text-gray-300">
                          {s.page_target || "homepage"}
                        </span>
                      </div>
                      <div className="text-[11px] text-[#8b93a3] flex items-center gap-3">
                        <span>Placement: <strong className="text-gray-300">{s.placement || "homepage_top"}</strong></span>
                        <span>Dimensions: <strong className="text-gray-300">{s.width_px || s.max_width_px || 728}x{s.height_px || 90}px</strong></span>
                        <span className={s.enabled !== false ? "text-emerald-400 font-semibold" : "text-gray-500"}>
                          {s.enabled !== false ? "● Active" : "○ Disabled"}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2.5">
                      <button
                        type="button"
                        onClick={() => updateSlotMutation.mutate({ id: s.id, payload: { enabled: !s.enabled } })}
                        className={`px-3 py-1.5 rounded-xl text-xs font-bold border transition ${
                          s.enabled !== false
                            ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                            : "bg-gray-800 border-gray-700 text-gray-400"
                        }`}
                      >
                        {s.enabled !== false ? "Disable" : "Enable"}
                      </button>

                      <button
                        type="button"
                        onClick={() => deleteSlotMutation.mutate(s.id)}
                        className="px-3.5 py-1.5 rounded-xl bg-red-600/20 hover:bg-red-600 text-red-300 hover:text-white border border-red-500/50 text-xs font-bold transition flex items-center gap-1.5"
                        title={`Delete slot ${s.name}`}
                      >
                        <i className="fas fa-trash-alt text-xs"></i>
                        <span>Delete</span>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SUB-PAGE 2: AD MANAGER & MULTI-NETWORK CREATIVES                           */}
      {/* ========================================================================= */}
      {activeTab === "manager" && (
        <div className="space-y-6 animate-in fade-in">
          {/* Section 1: Global AdSense & Multiple Auto-Ad Networks Creation Form (Always Present) */}
          <div className="bg-[#15171c] border border-[#00AEF0]/40 p-5 sm:p-6 rounded-2xl shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-full bg-[#00AEF0]/20 border border-[#00AEF0]/40 flex items-center justify-center text-[#00AEF0]">
                  <i className="fas fa-globe text-base"></i>
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">Global Auto-Ads &amp; Ad Networks Engine</h3>
                  <p className="text-xs text-[#8b93a3]">
                    Add one, multiple, or no auto-ad networks. If an ad slot has no direct creative, enabled networks randomly display across the site.
                  </p>
                </div>
              </div>
            </div>

            {/* Creation Form Prompt (Always stays at top) */}
            <form onSubmit={handleAddNetwork} className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs bg-[#101216] p-4 rounded-xl border border-[#262a33]">
              <div>
                <label className="font-semibold text-gray-300 block mb-1">Network / Campaign Name</label>
                <input
                  type="text"
                  required
                  value={newNetworkName}
                  onChange={(e) => setNewNetworkName(e.target.value)}
                  placeholder="e.g. Google AdSense, PropellerAds, Sponsor Affiliate"
                  className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                />
              </div>

              <div>
                <label className="font-semibold text-gray-300 block mb-1">Publisher Tag / Client ID</label>
                <input
                  type="text"
                  value={newNetworkPublisherId}
                  onChange={(e) => setNewNetworkPublisherId(e.target.value)}
                  placeholder="ca-pub-9821430981239812"
                  className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                />
              </div>

              <div>
                <label className="font-semibold text-gray-300 block mb-1">Fallback Banner Graphic URL</label>
                <input
                  type="url"
                  value={newNetworkFallbackUrl}
                  onChange={(e) => setNewNetworkFallbackUrl(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                />
              </div>

              <div>
                <label className="font-semibold text-gray-300 block mb-1">Fallback Destination Link</label>
                <input
                  type="url"
                  value={newNetworkFallbackLink}
                  onChange={(e) => setNewNetworkFallbackLink(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                />
              </div>

              <div className="sm:col-span-2">
                <label className="font-semibold text-gray-300 block mb-1">Embed Script Code / Tag</label>
                <textarea
                  rows={2}
                  value={newNetworkScript}
                  onChange={(e) => setNewNetworkScript(e.target.value)}
                  placeholder='<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"></script>'
                  className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                />
              </div>

              <div className="sm:col-span-2 flex justify-end">
                <button
                  type="submit"
                  disabled={createNetworkMutation.isPending}
                  className="px-5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs shadow-lg transition flex items-center gap-2"
                >
                  <i className="fas fa-plus"></i>
                  <span>Add Global Auto-Ad Network</span>
                </button>
              </div>
            </form>

            {/* List of Configured Networks (All Deletable) */}
            <div className="space-y-3 pt-2">
              <span className="text-xs font-bold text-gray-300 block">Active Global Networks ({networks.length})</span>
              {loadingNetworks ? (
                <div className="text-xs text-[#8b93a3] text-center py-4">Loading networks…</div>
              ) : networks.length === 0 ? (
                <div className="text-xs text-[#8b93a3] text-center py-4">No global networks added. You can add one above or rely solely on direct slot creatives.</div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {networks.map((net) => (
                    <div key={net.id} className="p-3.5 bg-[#101216] border border-[#262a33] rounded-xl flex items-center justify-between gap-3">
                      <div className="space-y-0.5 min-w-0">
                        <span className="font-bold text-white text-xs block truncate">{net.name}</span>
                        <span className="text-[10px] text-[#00AEF0] font-mono block truncate">{net.publisher_id || "Direct Script / URL"}</span>
                        <span className="text-[10px] text-gray-400">
                          {net.enabled ? "● Auto-Rotating" : "○ Paused"} · {net.impressions || 0} impressions
                        </span>
                      </div>

                      <div className="flex items-center gap-2 flex-none">
                        <button
                          type="button"
                          onClick={() => toggleNetworkMutation.mutate({ id: net.id, enabled: !net.enabled })}
                          className={`px-2.5 py-1 rounded-lg text-[10px] font-bold border transition ${
                            net.enabled ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300" : "bg-gray-800 border-gray-700 text-gray-400"
                          }`}
                        >
                          {net.enabled ? "Active" : "Paused"}
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteNetworkMutation.mutate(net.id)}
                          className="px-2.5 py-1 rounded-lg bg-red-500/20 hover:bg-red-600 text-red-300 hover:text-white border border-red-500/50 text-[10px] font-bold transition flex items-center gap-1"
                        >
                          <i className="fas fa-trash-alt"></i>
                          <span>Delete</span>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Section 2: Slot Creative Assignment */}
          <div className="bg-[#15171c] border border-[#262a33] p-5 sm:p-6 rounded-2xl shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <i className="fas fa-bullhorn text-amber-400"></i>
                <span>Slot Creative Provisioning</span>
              </h3>
              <span className="text-xs text-[#8b93a3]">Assign specific banner graphics or destination links to your visual slots</span>
            </div>

            {slots.length === 0 ? (
              <div className="p-8 text-center text-xs text-[#8b93a3]">
                No slots found. Draw visual rectangle slots in the <strong>"1. Ad Slots"</strong> tab first.
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {slots.map((slot) => (
                  <div key={slot.id} className="p-4 bg-[#101216] border border-[#262a33] rounded-2xl space-y-3 shadow-md">
                    <div className="flex items-center justify-between border-b border-[#262a33] pb-2">
                      <div>
                        <span className="font-bold text-white text-xs block">{slot.name}</span>
                        <span className="text-[10px] text-[#00AEF0] font-mono">{slot.slot_key} ({slot.page_target || "homepage"})</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => deleteSlotMutation.mutate(slot.id)}
                        className="px-3 py-1.5 rounded-xl bg-red-500/20 hover:bg-red-600 text-red-300 hover:text-white border border-red-500/50 text-xs font-bold transition flex items-center gap-1"
                      >
                        <i className="fas fa-trash-alt text-xs"></i>
                        <span>Delete</span>
                      </button>
                    </div>

                    <div className="space-y-2 text-xs">
                      <div>
                        <label className="text-[10px] font-semibold text-gray-400 block mb-0.5">Banner Image URL</label>
                        <input
                          type="url"
                          value={slot.image_url || ""}
                          onChange={(e) => updateSlotMutation.mutate({ id: slot.id, payload: { image_url: e.target.value } })}
                          placeholder="https://images.unsplash.com/... banner.png"
                          className="w-full px-3 py-1.5 rounded-lg bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                        />
                      </div>

                      <div>
                        <label className="text-[10px] font-semibold text-gray-400 block mb-0.5">Destination Click URL</label>
                        <input
                          type="url"
                          value={slot.link_url || ""}
                          onChange={(e) => updateSlotMutation.mutate({ id: slot.id, payload: { link_url: e.target.value } })}
                          placeholder="https://sponsor.com/signup"
                          className="w-full px-3 py-1.5 rounded-lg bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                        />
                      </div>

                      {slot.image_url && (
                        <div className="mt-2 rounded-lg overflow-hidden border border-[#262a33] h-20 bg-black flex items-center justify-center">
                          <img src={slot.image_url} alt={slot.name} className="h-full w-full object-cover" />
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
