import React, { useState, useEffect } from "react";
import api from "../services/api";

const FONT_FAMILIES = [
  { key: "sans-serif", label: "Clean Sans-Serif (Default)", fontClass: "font-sans" },
  { key: "comic", label: "Anime / Manga Comic", fontClass: "font-comic" },
  { key: "impact", label: "Dynamic Bold Action", fontClass: "font-extrabold" },
  { key: "serif", label: "Classic Serif / Novel", fontClass: "font-serif" },
  { key: "monospace", label: "Modern Monospace", fontClass: "font-mono" },
];

const OVERLAY_STYLES = [
  { key: "white_box", label: "White Box (Highest Legibility)", bg: "bg-white text-black", desc: "Solid white bubble fill with black text" },
  { key: "transparent_outline", label: "Transparent + Text Stroke", bg: "bg-transparent text-white drop-shadow-[0_2px_2px_rgba(0,0,0,0.9)]", desc: "Preserves art underneath with black outline" },
  { key: "dark_box", label: "Dark Contrast Box", bg: "bg-black/90 text-white border border-gray-700", desc: "Dark mode box with crisp white text" },
];

export default function OverlayFontPicker() {
  const [fontScale, setFontScale] = useState(20);
  const [fontFamily, setFontFamily] = useState("sans-serif");
  const [overlayStyle, setOverlayStyle] = useState("white_box");
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState(false);

  useEffect(() => {
    api.get("/user/processing-settings")
      .then((res) => {
        if (res) {
          if (res.font_scale) setFontScale(Number(res.font_scale));
          if (res.font_family) setFontFamily(res.font_family);
          if (res.overlay_style) setOverlayStyle(res.overlay_style);
        }
      })
      .catch(() => {});
  }, []);

  const handleZoomIn = () => {
    setFontScale((prev) => Math.min(48, prev + 2));
  };

  const handleZoomOut = () => {
    setFontScale((prev) => Math.max(10, prev - 2));
  };

  const handleSavePreferences = async () => {
    setSaving(true);
    try {
      await api.put("/user/processing-settings", {
        font_scale: fontScale,
        font_family: fontFamily,
        overlay_style: overlayStyle,
      });
      setSavedNotice(true);
      setTimeout(() => setSavedNotice(false), 3000);
    } catch (err) {
      console.error("Failed to save font settings", err);
    } finally {
      setSaving(false);
    }
  };

  const selectedStyleObj = OVERLAY_STYLES.find((s) => s.key === overlayStyle) || OVERLAY_STYLES[0];

  return (
    <div className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 sm:p-6 shadow-xl space-y-5 text-xs">
      <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <i className="fas fa-font text-[#00AEF0]"></i>
            <span>Translation Overlay Typography &amp; Font Zoom Controls</span>
          </h3>
          <p className="text-[11px] text-[#8b93a3] mt-0.5">
            Enlarge or reduce reading font size, customize dialogue box styles, and preview in real time.
          </p>
        </div>

        {/* Quick Zoom Buttons */}
        <div className="flex items-center gap-1.5 bg-[#101216] border border-[#262a33] p-1 rounded-xl">
          <button
            type="button"
            onClick={handleZoomOut}
            disabled={fontScale <= 10}
            className="w-8 h-8 rounded-lg bg-[#15171c] hover:bg-[#252a38] text-gray-200 hover:text-white flex items-center justify-center font-bold text-sm transition disabled:opacity-40"
            title="Zoom Out (Make text smaller)"
          >
            <i className="fas fa-search-minus"></i>
          </button>
          <span className="text-xs font-bold text-[#00AEF0] px-2 min-w-[3rem] text-center font-mono">
            {fontScale}px
          </span>
          <button
            type="button"
            onClick={handleZoomIn}
            disabled={fontScale >= 48}
            className="w-8 h-8 rounded-lg bg-[#15171c] hover:bg-[#252a38] text-gray-200 hover:text-white flex items-center justify-center font-bold text-sm transition disabled:opacity-40"
            title="Zoom In (Enlarge text size)"
          >
            <i className="fas fa-search-plus"></i>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Controls Column */}
        <div className="space-y-4">
          {/* Font Size Slider */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="font-bold text-gray-300">Font Size / Zoom Scale</label>
              <span className="text-xs text-[#00AEF0] font-mono font-bold">{fontScale}px</span>
            </div>
            <input
              type="range"
              min={10}
              max={48}
              step={1}
              value={fontScale}
              onChange={(e) => setFontScale(Number(e.target.value))}
              className="w-full h-2 bg-[#101216] rounded-lg appearance-none cursor-pointer accent-[#00AEF0]"
            />
            {/* Preset Buttons */}
            <div className="flex flex-wrap gap-1.5 pt-1">
              {[
                { label: "Compact (14px)", val: 14 },
                { label: "Normal (18px)", val: 18 },
                { label: "Large (24px)", val: 24 },
                { label: "Extra Large (32px)", val: 32 },
                { label: "Max Zoom (42px)", val: 42 },
              ].map((preset) => (
                <button
                  key={preset.val}
                  type="button"
                  onClick={() => setFontScale(preset.val)}
                  className={`px-2.5 py-1 rounded-lg text-[10px] font-semibold transition ${
                    fontScale === preset.val
                      ? "bg-[#00AEF0] text-white"
                      : "bg-[#101216] text-[#8b93a3] hover:text-white border border-[#262a33]"
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          {/* Font Family Selection */}
          <div className="space-y-1.5">
            <label className="font-bold text-gray-300 block">Font Typography</label>
            <select
              value={fontFamily}
              onChange={(e) => setFontFamily(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
            >
              {FONT_FAMILIES.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>

          {/* Dialogue Bubble Style */}
          <div className="space-y-1.5">
            <label className="font-bold text-gray-300 block">Dialogue Bubble Fill &amp; Stroke</label>
            <div className="grid grid-cols-1 gap-2">
              {OVERLAY_STYLES.map((style) => (
                <button
                  key={style.key}
                  type="button"
                  onClick={() => setOverlayStyle(style.key)}
                  className={`p-2.5 rounded-xl border text-left transition flex items-start justify-between gap-2 ${
                    overlayStyle === style.key
                      ? "bg-[#00AEF0]/15 border-[#00AEF0] ring-1 ring-[#00AEF0]"
                      : "bg-[#101216] border-[#262a33] text-gray-400 hover:text-white"
                  }`}
                >
                  <div>
                    <span className="font-bold text-white text-xs block">{style.label}</span>
                    <span className="text-[10px] text-[#8b93a3]">{style.desc}</span>
                  </div>
                  {overlayStyle === style.key && <i className="fas fa-check text-[#00AEF0] text-xs mt-1"></i>}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Live Interactive Preview Box Column */}
        <div className="space-y-3">
          <label className="font-bold text-gray-300 block">Live Manga Bubble Simulator</label>
          <div className="p-6 rounded-2xl bg-[#0a0c0f] border border-[#262a33] flex flex-col items-center justify-center min-h-[260px] relative overflow-hidden shadow-inner">
            {/* Manga Background Mock Art Lines */}
            <div className="absolute inset-0 opacity-10 bg-[radial-gradient(#00AEF0_1px,transparent_1px)] [background-size:16px_16px]"></div>

            {/* Speech Bubble Simulator */}
            <div
              className={`relative z-10 max-w-xs p-4 rounded-2xl text-center shadow-2xl transition-all duration-150 ${selectedStyleObj.bg}`}
              style={{
                fontSize: `${fontScale}px`,
                lineHeight: "1.35",
                fontFamily:
                  fontFamily === "comic"
                    ? '"Comic Sans MS", cursive, sans-serif'
                    : fontFamily === "serif"
                    ? 'Georgia, serif'
                    : fontFamily === "monospace"
                    ? 'monospace'
                    : 'inherit',
                fontWeight: fontFamily === "impact" ? 900 : 700,
              }}
            >
              <span>"ARISE, MY SHADOW SOLDIERS!"</span>
              {/* Speech bubble tail indicator */}
              <div
                className={`w-3 h-3 rotate-45 mx-auto -mb-5 mt-2 ${
                  overlayStyle === "white_box"
                    ? "bg-white"
                    : overlayStyle === "dark_box"
                    ? "bg-black border-r border-b border-gray-700"
                    : "hidden"
                }`}
              ></div>
            </div>

            <span className="absolute bottom-2 text-[10px] text-[#8b93a3] tracking-wider uppercase font-semibold">
              Live Scaled: {fontScale}px • {fontFamily}
            </span>
          </div>

          <div className="flex items-center justify-between pt-2">
            {savedNotice ? (
              <span className="text-emerald-400 font-bold text-xs flex items-center gap-1.5 animate-in fade-in">
                <i className="fas fa-check-circle"></i>
                <span>Typography preferences saved!</span>
              </span>
            ) : (
              <span className="text-[11px] text-[#8b93a3]">
                Changes apply instantly across all manga reader chapters.
              </span>
            )}

            <button
              type="button"
              onClick={handleSavePreferences}
              disabled={saving}
              className="px-5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs shadow-lg transition flex items-center gap-1.5 disabled:opacity-50"
            >
              <i className={saving ? "fas fa-spinner fa-spin" : "fas fa-save"}></i>
              <span>{saving ? "Saving…" : "Save Typography"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
