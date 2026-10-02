import React, { useState, useEffect } from "react";
import { apiFetch } from "../services/api";
import OverlayBox from "./OverlayBox";

// Server-side OCR + translation for one page (cached per page/language),
// drawn as boxes over the original lettering only.
export default function ReaderOverlay({
  imageUrl,
  chapterId,
  pageIndex,
  settings,
  translatable = true,
  onLimitReached,
  onError,
}) {
  const [boxes, setBoxes] = useState([]);
  const language = settings.target_language || "en";

  useEffect(() => {
    let isMounted = true;
    setBoxes([]);
    if (!imageUrl || !chapterId || pageIndex === undefined || pageIndex === null || !translatable) {
      return undefined;
    }

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
        if (res.status === 429) {
          if (onLimitReached) onLimitReached(res);
          return;
        }
        if (!res.ok) {
          if (onError) onError(res.status);
          return;
        }
        if (!size || !size.w || !size.h) return;
        const data = await res.json();
        if (!isMounted) return;
        const withText = (data.regions || []).filter((r) => r.coordinates && String(r.text || "").trim());
        // A region whose "translation" is the source text unchanged was not
        // translated (no provider answered): covering it helps nobody.
        const translated = withText.filter(
          (r) => String(r.text).trim() !== String(r.source_text || "").trim()
        );
        if (withText.length && !translated.length && onError) onError("untranslated");
        const found = translated
          .map((r, i) => ({
            id: r.index ?? i,
            x: r.coordinates.x / size.w,
            y: r.coordinates.y / size.h,
            w: r.coordinates.width / size.w,
            h: r.coordinates.height / size.h,
            original: r.source_text || "",
            translated: r.text,
            // Bubble fill and lettering colour sampled around the original
            // text; only trusted when the surrounding art is plain.
            bg: r.background_clean ? r.background : null,
            fg: r.background_clean ? r.text_color : null,
            // The speech bubble around the text, when the server found a
            // closed one (text drawn straight onto the art has none).
            bubble:
              r.background_clean && r.bubble && r.bubble.width > 0 && r.bubble.height > 0
                ? {
                    shape: r.bubble.shape,
                    polygon: r.bubble.polygon,
                    inner: r.bubble.inner,
                    x: r.bubble.x / size.w,
                    y: r.bubble.y / size.h,
                    w: r.bubble.width / size.w,
                    h: r.bubble.height / size.h,
                  }
                : null,
          }));
        setBoxes(found);
      } catch {
        // The overlay is optional: the page itself is already readable.
      }
    })();

    return () => {
      isMounted = false;
    };
    // onLimitReached/onError are notification callbacks, not inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageUrl, language, chapterId, pageIndex, translatable]);

  if (!boxes.length) return null;

  return (
    <div className="absolute inset-0 pointer-events-none z-10 overflow-hidden">
      {boxes.map((box) => {
        // "Match the bubble shape" (default on): fill the bubble; off, or no
        // bubble found: the original text area, as a plain box.
        const shaped = settings.overlay_match_bubble !== false && box.bubble;
        const area = shaped ? box.bubble : box;
        return (
          <OverlayBox
            key={box.id}
            region={shaped ? box : { ...box, bubble: null }}
            settings={settings}
            title={`Original: ${box.original}`}
            style={{
              left: `${area.x * 100}%`,
              top: `${area.y * 100}%`,
              width: `${area.w * 100}%`,
              height: `${area.h * 100}%`,
            }}
          />
        );
      })}
    </div>
  );
}
