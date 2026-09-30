import React, { useState, useEffect } from "react";
import api from "../services/api";

export default function OverlayScaleControl({ chapterId, onScaleChange }) {
  const [fontScale, setFontScale] = useState(18);
  const [overlayStyle, setOverlayStyle] = useState("white_box");
  const [showDropdown, setShowDropdown] = useState(false);

  useEffect(() => {
    // Load persisted settings or local storage
    const local = localStorage.getItem("reader_font_settings");
    if (local) {
      try {
        const parsed = JSON.parse(local);
        if (parsed.fontScale) setFontScale(parsed.fontScale);
        if (parsed.overlayStyle) setOverlayStyle(parsed.overlayStyle);
      } catch (e) {}
    }

    api.get("/user/processing-settings")
      .then((res) => {
        if (res && res.font_scale) {
          setFontScale(Number(res.font_scale));
          if (res.overlay_style) setOverlayStyle(res.overlay_style);
        }
      })
      .catch(() => {});
  }, []);

  const updateScale = (newScale) => {
    const clamped = Math.min(44, Math.max(10, newScale));
    setFontScale(clamped);
    if (onScaleChange) onScaleChange(clamped);
    
    // Broadcast custom event so all ReaderOverlays on the page update instantly
    window.dispatchEvent(
      new CustomEvent("reader-font-scale-change", {
        detail: { fontScale: clamped, overlayStyle },
      })
    );

    localStorage.setItem(
      "reader_font_settings",
      JSON.stringify({ fontScale: clamped, overlayStyle })
    );

    // Debounced persist to user backend
    api.put("/user/processing-settings", { font_scale: clamped, overlay_style: overlayStyle }).catch(() => {});
  };

  const updateStyle = (newStyle) => {
    setOverlayStyle(newStyle);
    window.dispatchEvent(
      new CustomEvent("reader-font-scale-change", {
        detail: { fontScale, overlayStyle: newStyle },
      })
    );
    localStorage.setItem(
      "reader_font_settings",
      JSON.stringify({ fontScale, overlayStyle: newStyle })
    );
    api.put("/user/processing-settings", { font_scale: fontScale, overlay_style: newStyle }).catch(() => {});
  };

  return (
    <div className="flex items-center gap-2 bg-[#15171c] border border-[#262a33] p-1.5 rounded-xl text-xs shadow-md">
      <span className="text-[11px] font-bold text-gray-400 pl-2 flex items-center gap-1.5 hidden sm:inline-flex">
        <i className="fas fa-text-height text-[#00AEF0]"></i>
        <span>Font Zoom:</span>
      </span>

      {/* Zoom Out Button */}
      <button
        type="button"
        onClick={() => updateScale(fontScale - 2)}
        disabled={fontScale <= 10}
        className="w-7 h-7 rounded-lg bg-[#101216] hover:bg-[#1f2330] border border-[#262a33] text-gray-200 hover:text-white flex items-center justify-center font-bold text-xs transition disabled:opacity-30"
        title="Zoom Out (Make text smaller)"
      >
        <i className="fas fa-minus"></i>
      </button>

      {/* Font Size Indicator / Slider */}
      <div className="flex items-center gap-1.5 px-1">
        <input
          type="range"
          min="10"
          max="44"
          step="2"
          value={fontScale}
          onChange={(e) => updateScale(Number(e.target.value))}
          className="w-16 sm:w-24 h-1.5 bg-[#101216] rounded-lg appearance-none cursor-pointer accent-[#00AEF0]"
          title={`Font Scale: ${fontScale}px`}
        />
        <span className="text-[11px] font-mono font-bold text-[#00AEF0] min-w-[32px] text-center">
          {fontScale}px
        </span>
      </div>

      {/* Zoom In Button */}
      <button
        type="button"
        onClick={() => updateScale(fontScale + 2)}
        disabled={fontScale >= 44}
        className="w-7 h-7 rounded-lg bg-[#101216] hover:bg-[#1f2330] border border-[#262a33] text-gray-200 hover:text-white flex items-center justify-center font-bold text-xs transition disabled:opacity-30"
        title="Zoom In (Enlarge text)"
      >
        <i className="fas fa-plus"></i>
      </button>

      {/* Style Toggle Dropdown */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setShowDropdown(!showDropdown)}
          className="px-2 py-1 rounded-lg bg-[#101216] hover:bg-[#1f2330] border border-[#262a33] text-gray-300 hover:text-white text-[11px] font-semibold flex items-center gap-1 transition"
          title="Change Overlay Bubble Style"
        >
          <i className="fas fa-paint-brush text-[#00AEF0]"></i>
          <span className="hidden sm:inline">Style</span>
          <i className="fas fa-chevron-down text-[9px] text-gray-400"></i>
        </button>

        {showDropdown && (
          <div className="absolute right-0 mt-1.5 w-44 bg-[#15171c] border border-[#262a33] rounded-xl shadow-2xl py-1 z-30 animate-in fade-in">
            <button
              type="button"
              onClick={() => {
                updateStyle("white_box");
                setShowDropdown(false);
              }}
              className={`w-full text-left px-3 py-1.5 text-[11px] hover:bg-[#1f2330] transition flex items-center gap-2 ${
                overlayStyle === "white_box" ? "text-[#00AEF0] font-bold" : "text-gray-300"
              }`}
            >
              <span className="w-3 h-3 rounded-full bg-white border border-gray-400 flex-none"></span>
              <span>White Bubble Box</span>
            </button>
            <button
              type="button"
              onClick={() => {
                updateStyle("transparent_outline");
                setShowDropdown(false);
              }}
              className={`w-full text-left px-3 py-1.5 text-[11px] hover:bg-[#1f2330] transition flex items-center gap-2 ${
                overlayStyle === "transparent_outline" ? "text-[#00AEF0] font-bold" : "text-gray-300"
              }`}
            >
              <span className="w-3 h-3 rounded-full bg-transparent border-2 border-white flex-none"></span>
              <span>Transparent Stroke</span>
            </button>
            <button
              type="button"
              onClick={() => {
                updateStyle("dark_box");
                setShowDropdown(false);
              }}
              className={`w-full text-left px-3 py-1.5 text-[11px] hover:bg-[#1f2330] transition flex items-center gap-2 ${
                overlayStyle === "dark_box" ? "text-[#00AEF0] font-bold" : "text-gray-300"
              }`}
            >
              <span className="w-3 h-3 rounded-full bg-black border border-gray-600 flex-none"></span>
              <span>Dark Mode Box</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
