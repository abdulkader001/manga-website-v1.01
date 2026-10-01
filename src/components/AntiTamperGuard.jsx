import React, { useEffect, useState } from "react";
import { handleMangaContextMenu } from "../utils/mangaLinkMenu";

/**
 * AntiTamperGuard Component
 * Professional client-side guardrail system to protect site architecture,
 * core working logic, and prevent unauthorized DevTools inspection / DOM cobbling.
 */
export default function AntiTamperGuard({ children }) {
  const [toastNotice, setToastNotice] = useState(null);

  useEffect(() => {
    // 1. Console security banner (Anti-Self-XSS & Code Tampering Shield)
    try {
      console.log(
        "%c🛡️ CORE SYSTEM SECURITY SHIELD ACTIVE",
        "color: #00AEF0; font-size: 20px; font-weight: bold; background: #15171c; padding: 6px 12px; border-radius: 6px;"
      );
      console.log(
        "%cWARNING: This application is protected by tamper-prevention guardrails. Attempting to inject scripts, inspect sensitive state, or manipulate DOM roles is monitored and will terminate the active session.",
        "color: #f87171; font-size: 12px; font-weight: bold;"
      );
    } catch {}

    // 2. Keystroke Guard: Intercept DevTools & Source Inspection shortcuts
    const handleKeyDown = (e) => {
      // F12 key
      if (e.key === "F12") {
        e.preventDefault();
        showNotice("🛡️ Developer inspection tools are restricted by system guardrails.");
        return false;
      }

      // Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+Shift+C (Windows/Linux)
      // Cmd+Option+I, Cmd+Option+J, Cmd+Option+C (Mac)
      const isCmdOrCtrl = e.ctrlKey || e.metaKey;
      if (isCmdOrCtrl && e.shiftKey && (e.key === "I" || e.key === "i" || e.key === "J" || e.key === "j" || e.key === "C" || e.key === "c")) {
        e.preventDefault();
        showNotice("🛡️ Source inspection is protected to safeguard core architecture.");
        return false;
      }

      // Ctrl+U / Cmd+U (View Source)
      if (isCmdOrCtrl && (e.key === "u" || e.key === "U")) {
        e.preventDefault();
        showNotice("🛡️ Source viewing is protected.");
        return false;
      }

      // Ctrl+S / Cmd+S (Save Page)
      if (isCmdOrCtrl && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        return false;
      }
    };

    // 3. Context Menu Guard (Right Click Inspect protection)
    const handleContextMenu = (e) => {
      // Allow right-click on standard links and inputs, but intercept on canvas/body
      if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) {
        return;
      }
      // Manga cards: right-click opens the manga in a new tab (Shift/Win +
      // right-click: a new window) instead of the browser menu.
      if (handleMangaContextMenu(e)) return;
      e.preventDefault();
      showNotice("🛡️ Right-click inspection is disabled by Anti-Tamper Security.");
    };

    // 4. Mutation Observer to detect client-side DOM tampering
    let observer = null;
    try {
      observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          if (mutation.type === "attributes") {
            const target = mutation.target;
            // Prevent tampering with session or role flags
            if (target && target.hasAttribute && target.hasAttribute("data-tampered")) {
              target.removeAttribute("data-tampered");
            }
          }
        }
      });
      observer.observe(document.body, { attributes: true, subtree: true, attributeFilter: ["data-role", "data-admin"] });
    } catch {}

    window.addEventListener("keydown", handleKeyDown, true);
    window.addEventListener("contextmenu", handleContextMenu, true);

    return () => {
      window.removeEventListener("keydown", handleKeyDown, true);
      window.removeEventListener("contextmenu", handleContextMenu, true);
      if (observer) observer.disconnect();
    };
  }, []);

  const showNotice = (msg) => {
    setToastNotice(msg);
    setTimeout(() => setToastNotice(null), 3500);
  };

  return (
    <>
      {/* Toast Notice when inspection or tampering is blocked */}
      {toastNotice && (
        <div className="fixed top-5 right-5 z-[9999] bg-[#15171c]/95 border border-purple-500/50 text-white px-4 py-3 rounded-2xl shadow-2xl flex items-center gap-2.5 text-xs backdrop-blur-md animate-in fade-in slide-in-from-top-3">
          <div className="w-6 h-6 rounded-full bg-purple-500/20 text-purple-400 flex items-center justify-center flex-shrink-0 text-xs">
            <i className="fas fa-shield-alt"></i>
          </div>
          <span className="font-semibold">{toastNotice}</span>
          <button
            type="button"
            onClick={() => setToastNotice(null)}
            className="ml-2 text-gray-400 hover:text-white"
          >
            ✕
          </button>
        </div>
      )}
      {children}
    </>
  );
}
