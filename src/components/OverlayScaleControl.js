import React, { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import useReaderSettings, { READER_SETTINGS_KEY } from "../hooks/useReaderSettings";
import {
  TEXT_SCALE_MAX,
  TEXT_SCALE_MIN,
  TEXT_SCALE_STEP,
  clampTextScale,
  textScaleToPx,
} from "../utils/overlayText";

// Quick size control for the translated text on the page (1-100, half
// steps; 100 = 70 px). Every overlay on the page resizes at once (the shared
// settings copy is updated in place); the account is saved shortly after the
// reader stops moving it, so the size is the same in Settings and on every
// device.
const SAVE_DELAY_MS = 500;

export default function OverlayScaleControl() {
  const { settings, save } = useReaderSettings();
  const queryClient = useQueryClient();
  const size = clampTextScale(settings.overlay_font_size);
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  const change = (next) => {
    const value = clampTextScale(next);
    queryClient.setQueryData(READER_SETTINGS_KEY, (old) => (old ? { ...old, overlay_font_size: value } : old));
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      save({ overlay_font_size: value }).catch(() =>
        queryClient.invalidateQueries({ queryKey: READER_SETTINGS_KEY })
      );
    }, SAVE_DELAY_MS);
  };

  const button =
    "w-7 h-7 rounded-lg bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] text-gray-200 flex items-center justify-center transition disabled:opacity-30";

  return (
    <div className="flex items-center gap-1.5 bg-[#101216] border border-[#262a33] p-1 rounded-xl text-xs">
      <span className="text-[11px] font-bold text-gray-400 pl-1.5 hidden sm:inline-flex items-center gap-1.5">
        <i className="fas fa-text-height text-[#00AEF0]"></i>
        <span>Text size</span>
      </span>
      <button
        type="button"
        onClick={() => change(size - TEXT_SCALE_STEP)}
        disabled={size <= TEXT_SCALE_MIN}
        className={button}
        aria-label="Smaller translated text"
      >
        <i className="fas fa-minus"></i>
      </button>
      <input
        type="range"
        min={TEXT_SCALE_MIN}
        max={TEXT_SCALE_MAX}
        step={TEXT_SCALE_STEP}
        value={size}
        onChange={(e) => change(e.target.value)}
        aria-label="Translated text size"
        aria-valuetext={`${size} (${textScaleToPx(size)} px)`}
        className="w-20 sm:w-28 accent-[#00AEF0]"
      />
      <button
        type="button"
        onClick={() => change(size + TEXT_SCALE_STEP)}
        disabled={size >= TEXT_SCALE_MAX}
        className={button}
        aria-label="Larger translated text"
      >
        <i className="fas fa-plus"></i>
      </button>
      <span className="w-10 text-center font-mono font-bold text-[#00AEF0]" title={`${textScaleToPx(size)} px`}>
        {size}
      </span>
    </div>
  );
}
