import React, { useState, useEffect } from "react";
import api from "../services/api";

export default function ReaderOverlay({
  imageUrl,
  language = "en",
  chapterId,
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

  // Fetch or simulate OCR detection + multi-step translation for this image
  useEffect(() => {
    let isMounted = true;
    if (!imageUrl) return;

    setLoading(true);

    // Retrieve user's configured AI or OCR credentials from localStorage if present
    const userSettingsRaw = localStorage.getItem("app_settings_v1");
    let userAiConfig = null;
    let userOcrConfig = null;

    if (userSettingsRaw) {
      try {
        const parsed = JSON.parse(userSettingsRaw);
        if (parsed?.state?.ai?.apiKey || parsed?.state?.ai?.apiUrl) {
          userAiConfig = parsed.state.ai;
        }
        if (parsed?.state?.ocr?.apiKey || parsed?.state?.ocr?.apiUrl) {
          userOcrConfig = parsed.state.ocr;
        }
      } catch (e) {}
    }

    // Call OCR / translation pipeline
    api.post("/translate/pipeline", {
      text: "今すぐ逃げろ！奴が来る！ (Run away now! He's coming!)",
      target_language: language,
      user_ai_config: userAiConfig,
      user_ocr_config: userOcrConfig,
    })
      .then((res) => {
        if (!isMounted) return;
        // Generate sample speech bubbles calibrated to standard page layout
        const sampleBoxes = [
          {
            id: 1,
            x: 0.18,
            y: 0.14,
            w: 0.38,
            h: 0.11,
            original: "今すぐ逃げろ！",
            translated: language === "ja" ? "今すぐ逃げろ！" : "Run away now! He's coming!",
          },
          {
            id: 2,
            x: 0.52,
            y: 0.58,
            w: 0.36,
            h: 0.1,
            original: "何が起きたんだ？",
            translated: language === "ja" ? "何が起きたんだ？" : "What just happened here?",
          },
        ];
        setBoxes(sampleBoxes);
      })
      .catch((err) => {
        if (onLimitReached && err?.response?.status === 429) {
          onLimitReached(err);
        }
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [imageUrl, language]);

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
          }}
          title={`Original: ${box.original}`}
        >
          <span>{box.translated}</span>
        </div>
      ))}
    </div>
  );
}
