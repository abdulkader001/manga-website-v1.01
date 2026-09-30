import React, { useState, useEffect } from "react";
import { apiFetch } from "../services/api";

export default function ReaderOverlay({
  imageUrl,
  language = "en",
  chapterId,
  pageIndex,
  mangaId,
  translatable = true,
  onLimitReached,
}) {
  const [boxes, setBoxes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [fontScale, setFontScale] = useState(18);
  const [overlayStyle, setOverlayStyle] = useState("white_box");

  // Load local font scale and listen for live changes from OverlayScaleControl
  useEffect(() => {
    const local = localStorage.getItem("reader_font_settings");
    if (local) {
      try {
        const parsed = JSON.parse(local);
        if (parsed.fontScale) setFontScale(parsed.fontScale);
        if (parsed.overlayStyle) setOverlayStyle(parsed.overlayStyle);
      } catch (e) {}
    }

    const handleScaleChange = (e) => {
      if (e.detail) {
        if (e.detail.fontScale) setFontScale(e.detail.fontScale);
        if (e.detail.overlayStyle) setOverlayStyle(e.detail.overlayStyle);
      }
    };

    window.addEventListener("reader-font-scale-change", handleScaleChange);
    return () => window.removeEventListener("reader-font-scale-change", handleScaleChange);
  }, []);

  // Real OCR + translation for this page (server-side, cached per page/language).
  useEffect(() => {
    let isMounted = true;
    setBoxes([]);
    if (!imageUrl || !chapterId || pageIndex === undefined || pageIndex === null || !translatable) {
      return undefined;
    }

    setLoading(true);

    const naturalSize = () =>
      new Promise((resolve) => {
        const probe = new Image();
        probe.referrerPolicy = "no-referrer";
        probe.onload = () => resolve({ w: probe.naturalWidth, h: probe.naturalHeight });
        probe.onerror = () => resolve(null);
        probe.src = imageUrl;
      });

    (async () => {
      try {
        const [res, size] = await Promise.all([
          apiFetch(
            `/processing/chapter/${encodeURIComponent(chapterId)}/page/${pageIndex}?target=${encodeURIComponent(language)}`
          ),
          naturalSize(),
        ]);
        if (!isMounted) return;
        if (res.status === 429 && onLimitReached) {
          onLimitReached(res);
          return;
        }
        if (!res.ok || !size || !size.w || !size.h) return;
        const data = await res.json();
        if (!isMounted) return;
        const found = (data.regions || [])
          .filter((r) => r.coordinates && String(r.text || "").trim())
          .map((r, i) => ({
            id: r.index ?? i,
            x: r.coordinates.x / size.w,
            y: r.coordinates.y / size.h,
            w: r.coordinates.width / size.w,
            h: r.coordinates.height / size.h,
            original: r.source_text || "",
            translated: r.text,
            // Bubble's own fill, sampled just outside the original lettering,
            // so the translation replaces the text instead of sitting in a
            // white patch. Only used when the surrounding art is plain.
            bg: r.background_clean ? r.background : null,
            fg: r.background_clean ? r.text_color : null,
          }));
        setBoxes(found);
      } catch {
        // Overlay is optional: the page itself is already readable.
      } finally {
        if (isMounted) setLoading(false);
      }
    })();

    return () => {
      isMounted = false;
    };
  }, [imageUrl, language, chapterId, pageIndex, translatable]);

  if (!boxes.length) return null;

  const styleClasses = {
    white_box: "bg-white text-gray-950 font-semibold border border-gray-300 shadow-md",
    transparent_outline: "bg-black/40 text-white font-extrabold drop-shadow-[0_2px_4px_rgba(0,0,0,1)] border border-white/40",
    dark_box: "bg-[#101216]/95 text-white font-semibold border border-gray-700 shadow-lg",
  }[overlayStyle] || "bg-white text-gray-950 font-semibold border border-gray-300 shadow-md";

  return (
    <div className="absolute inset-0 pointer-events-none z-10 overflow-hidden">
      {boxes.map((box) => (
        <div
          key={box.id}
          className={`absolute rounded-xl px-2.5 py-1.5 flex items-center justify-center text-center transition-all duration-150 pointer-events-auto select-text hover:ring-2 hover:ring-[#00AEF0] ${styleClasses}`}
          style={{
            left: `${box.x * 100}%`,
            top: `${box.y * 100}%`,
            width: `${box.w * 100}%`,
            minHeight: `${box.h * 100}%`,
            fontSize: `${fontScale}px`,
            lineHeight: 1.25,
            ...(overlayStyle === "white_box" && box.bg
              ? { backgroundColor: box.bg, color: box.fg }
              : {}),
          }}
          title={`Original: ${box.original}`}
        >
          <span>{box.translated}</span>
        </div>
      ))}
    </div>
  );
}
