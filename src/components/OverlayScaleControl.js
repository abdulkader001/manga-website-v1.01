import React from "react";
import useReaderSettings from "../hooks/useReaderSettings";

// Quick text-size control in the reader. Saves to the account, so the size
// is the same in Settings and on every device.
const MIN = 10;
const MAX = 40;

export default function OverlayScaleControl() {
  const { settings, save, saving } = useReaderSettings();
  const size = Number(settings.overlay_font_size) || 20;

  const change = (next) => {
    const clamped = Math.min(MAX, Math.max(MIN, next));
    if (clamped !== size) save({ overlay_font_size: clamped }).catch(() => {});
  };

  return (
    <div className="flex items-center gap-1.5 bg-[#101216] border border-[#262a33] p-1 rounded-xl text-xs">
      <span className="text-[11px] font-bold text-gray-400 pl-1.5 hidden sm:inline-flex items-center gap-1.5">
        <i className="fas fa-text-height text-[#00AEF0]"></i>
        <span>Text size</span>
      </span>
      <button
        type="button"
        onClick={() => change(size - 2)}
        disabled={size <= MIN || saving}
        className="w-7 h-7 rounded-lg bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] text-gray-200 flex items-center justify-center transition disabled:opacity-30"
        aria-label="Smaller translated text"
      >
        <i className="fas fa-minus"></i>
      </button>
      <span className="w-10 text-center font-mono font-bold text-[#00AEF0]">{size}px</span>
      <button
        type="button"
        onClick={() => change(size + 2)}
        disabled={size >= MAX || saving}
        className="w-7 h-7 rounded-lg bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] text-gray-200 flex items-center justify-center transition disabled:opacity-30"
        aria-label="Larger translated text"
      >
        <i className="fas fa-plus"></i>
      </button>
    </div>
  );
}
