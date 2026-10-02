import React, { useLayoutEffect, useRef } from "react";
import { fontStyleFor } from "../fonts/overlayFonts";
import { textScaleToPx } from "../utils/overlayText";

// One translated text block, drawn over the original lettering. When the
// server recognised the speech bubble around it, the fill takes the bubble's
// own shape (ellipse, rectangle or freeform outline) and the text sits in the
// largest box inside it; otherwise it covers exactly the original text area.
// The fill hides the source text (sampled from the bubble when the art
// around it is plain), and the font shrinks until the translation fits.

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

/** Outline around the letters: the reader's colour, else dark glass gets black. */
export function outlineShadow(settings, colors) {
  const color = settings.overlay_outline_color || (colors.outline ? "#000000" : null);
  if (!color) return undefined;
  const w = "0.07em";
  const offsets = [
    [w, "0"], [`-${w}`, "0"], ["0", w], ["0", `-${w}`],
    [w, w], [`-${w}`, w], [w, `-${w}`], [`-${w}`, `-${w}`],
  ];
  return offsets.map(([x, y]) => `${x} ${y} 0 ${color}`).join(", ");
}

const INSET_PX = 3; // keep clear of the bubble's drawn outline

/** CSS clip-path that cuts the fill to the bubble's own shape. */
export function bubbleClipPath(bubble) {
  if (!bubble) return undefined;
  if (bubble.shape === "ellipse") {
    return `ellipse(calc(50% - ${INSET_PX}px) calc(50% - ${INSET_PX}px) at 50% 50%)`;
  }
  if (bubble.shape === "rectangle") return `inset(${INSET_PX}px round 6px)`;
  const points = Array.isArray(bubble.polygon) ? bubble.polygon : [];
  if (points.length < 3) return `inset(${INSET_PX}px round 6px)`;
  return `polygon(${points
    .map(([x, y]) => {
      const dx = 0.5 - x;
      const dy = 0.5 - y;
      const len = Math.hypot(dx, dy) || 1;
      const ox = ((dx / len) * INSET_PX).toFixed(2);
      const oy = ((dy / len) * INSET_PX).toFixed(2);
      return `calc(${(x * 100).toFixed(2)}% + ${ox}px) calc(${(y * 100).toFixed(2)}% + ${oy}px)`;
    })
    .join(", ")})`;
}

export default function OverlayBox({ region, settings, style, title = undefined }) {
  const ref = useRef(null);
  const maxSize = textScaleToPx(settings.overlay_font_size);
  const minSize = Math.min(MIN_FONT_PX, maxSize);
  const colors = boxColors(settings, region);
  // The translation fills the recognised bubble shape; text goes in the
  // largest box that fits inside it. Without one: the original text area.
  const bubble = region?.bubble || null;
  const inner = bubble?.inner || { x: 0, y: 0, width: 1, height: 1 };

  // Shrink-to-fit: start at the reader's size and step down until the text
  // no longer overflows its area.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const overflowing = () => el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1;
    const fit = () => {
      // Whole words first: a word too long for the line overflows sideways
      // and makes the text shrink, instead of being split mid-word.
      el.style.overflowWrap = "normal";
      let size = maxSize;
      el.style.fontSize = `${size}px`;
      while (size > minSize && overflowing()) {
        size = Math.max(minSize, size - 0.5);
        el.style.fontSize = `${size}px`;
      }
      // Already at the smallest size and still too wide: split as a last resort.
      if (overflowing()) el.style.overflowWrap = "anywhere";
    };
    fit();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, [region?.translated, maxSize, minSize, settings.overlay_font, bubble?.shape, inner.width, inner.height]);

  return (
    <div
      title={title}
      data-shape={bubble?.shape || "box"}
      className="absolute pointer-events-auto select-text"
      style={{
        ...style,
        background: colors.background,
        borderRadius: bubble ? undefined : "0.4em",
        clipPath: bubbleClipPath(bubble),
      }}
    >
      <div
        ref={ref}
        className="absolute flex items-center justify-center text-center overflow-hidden"
        style={{
          left: `${inner.x * 100}%`,
          top: `${inner.y * 100}%`,
          width: `${inner.width * 100}%`,
          height: `${inner.height * 100}%`,
          ...fontStyleFor(settings.overlay_font),
          color: colors.color,
          padding: "0.1em 0.2em",
          lineHeight: 1.15,
          hyphens: "manual",
          textShadow: outlineShadow(settings, colors),
        }}
      >
        <span>{region?.translated}</span>
      </div>
    </div>
  );
}
