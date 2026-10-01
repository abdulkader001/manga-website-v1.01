import React, { useLayoutEffect, useRef } from "react";
import { fontStyleFor } from "../fonts/overlayFonts";

// One translated text block, drawn exactly over the original lettering.
// The fill hides the source text (sampled from the bubble when the art
// around it is plain), and the font shrinks until the translation fits the
// same area, so the page layout is not covered beyond the text itself.

const MIN_FONT_PX = 8;

function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function parseColor(color) {
  if (!color) return null;
  const rgb = hexToRgb(color);
  if (rgb) return rgb;
  const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/i.exec(color);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

function readableTextOn(fill) {
  const rgb = parseColor(fill) || [255, 255, 255];
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return luminance > 0.4 ? "#111111" : "#ffffff";
}

function withOpacity(color, opacityPct) {
  const rgb = parseColor(color) || [255, 255, 255];
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${Math.max(0, Math.min(100, opacityPct)) / 100})`;
}

/** Fill and text colour for one region under the reader's settings. */
export function boxColors(settings, region) {
  const style = settings.overlay_style;
  const opacity = settings.overlay_box_opacity ?? 100;
  if (style === "transparent_box") {
    return {
      background: "rgba(10, 10, 15, 0.55)",
      color: settings.overlay_text_color || "#ffffff",
      outline: true,
    };
  }
  const fill =
    style === "colored_box"
      ? settings.overlay_box_color || "#ffffff"
      : settings.overlay_box_color || region?.bg || "#ffffff";
  const text =
    settings.overlay_text_color ||
    (style !== "colored_box" && !settings.overlay_box_color && region?.fg) ||
    readableTextOn(fill);
  return { background: withOpacity(fill, opacity), color: text, outline: false };
}

export default function OverlayBox({ region, settings, style, title = undefined }) {
  const ref = useRef(null);
  const maxSize = Number(settings.overlay_font_size) || 20;
  const colors = boxColors(settings, region);

  // Shrink-to-fit: start at the reader's size and step down until the text
  // no longer overflows the original text area.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const fit = () => {
      let size = maxSize;
      el.style.fontSize = `${size}px`;
      while (size > MIN_FONT_PX && (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1)) {
        size -= 1;
        el.style.fontSize = `${size}px`;
      }
    };
    fit();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, [region?.translated, maxSize, settings.overlay_font]);

  return (
    <div
      ref={ref}
      title={title}
      className="absolute flex items-center justify-center text-center overflow-hidden pointer-events-auto select-text"
      style={{
        ...style,
        ...fontStyleFor(settings.overlay_font),
        background: colors.background,
        color: colors.color,
        borderRadius: "0.4em",
        padding: "0.1em 0.2em",
        lineHeight: 1.15,
        wordBreak: "break-word",
        hyphens: "auto",
        textShadow: colors.outline
          ? "0 0 2px #000, 0 0 2px #000, 0 1px 3px rgba(0,0,0,0.9)"
          : undefined,
      }}
    >
      <span>{region?.translated}</span>
    </div>
  );
}
