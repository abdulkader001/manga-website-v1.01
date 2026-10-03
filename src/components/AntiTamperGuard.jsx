import React, { useCallback, useEffect, useRef, useState } from "react";
import { handleMangaContextMenu } from "../utils/mangaLinkMenu";

/**
 * AntiTamperGuard
 *
 * Makes casual inspection harder: blocks the browser's right-click menu (its
 * "Inspect" entry) and the developer-tools / view-source shortcuts.
 *
 * This is a speed bump, not security. Anyone can still open the developer
 * tools from the browser's own menu or switch JavaScript off. What actually
 * keeps the site safe is on the server: every API and admin route checks the
 * sign-in, the role and the authenticator code, and no secret is ever sent
 * to the browser.
 *
 * Text boxes used to get the browser menu (so readers could paste), which put
 * "Inspect" one click away. They now get a small menu of our own with Cut,
 * Copy, Paste and Select all. On touch screens the phone's own text tools are
 * left alone: they have no "Inspect" entry, and blocking them breaks pasting.
 */

// Ctrl/Cmd + Shift/Option + one of these opens a developer tool in some
// browser: I (inspector), J (console), C (element picker), K (Firefox
// console), M (responsive mode), E (Firefox network).
const DEVTOOLS_KEYS = new Set(["KeyI", "KeyJ", "KeyC", "KeyK", "KeyM", "KeyE"]);

function isTextField(el) {
  if (!el || el.nodeType !== 1) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "TEXTAREA") return !el.disabled;
  if (tag !== "INPUT") return false;
  const type = (el.getAttribute("type") || "text").toLowerCase();
  return !el.disabled && ["text", "search", "email", "url", "tel", "number", "password"].includes(type);
}

function isTouchPress(e) {
  if (e.pointerType) return e.pointerType === "touch" || e.pointerType === "pen";
  if (e.sourceCapabilities && e.sourceCapabilities.firesTouchEvents) return true;
  try {
    return window.matchMedia("(pointer: coarse)").matches && !window.matchMedia("(any-pointer: fine)").matches;
  } catch {
    return false;
  }
}

export function isDevtoolsShortcut(e) {
  if (e.key === "F12" || e.code === "F12") return "inspect";
  const code = e.code || (e.key && e.key.length === 1 ? `Key${e.key.toUpperCase()}` : "");
  // Windows / Linux use Ctrl+Shift, a Mac uses Cmd+Option (or Cmd+Shift).
  // Ctrl+Alt is left alone: it is AltGr on many keyboards (AltGr+E types €).
  const pcCombo = e.ctrlKey && e.shiftKey && !e.altKey;
  const macCombo = e.metaKey && (e.altKey || e.shiftKey);
  if ((pcCombo || macCombo) && DEVTOOLS_KEYS.has(code)) return "inspect";
  const plain = (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey;
  // View source: Ctrl+U, and Cmd+Option+U on a Mac.
  if (code === "KeyU" && (plain || (e.metaKey && e.altKey))) return "source";
  if (code === "KeyS" && plain) return "save";
  return null;
}

function TextFieldMenu({ menu, onClose }) {
  const ref = useRef(null);

  useEffect(() => {
    const close = (e) => {
      if (ref.current && ref.current.contains(e.target)) return;
      onClose();
    };
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("mousedown", close, true);
    window.addEventListener("scroll", onClose, true);
    window.addEventListener("resize", onClose);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("mousedown", close, true);
      window.removeEventListener("scroll", onClose, true);
      window.removeEventListener("resize", onClose);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [onClose]);

  const field = menu.field;
  const run = async (action) => {
    onClose();
    try {
      field.focus();
      if (action === "selectAll") {
        if (typeof field.select === "function") field.select();
        else document.execCommand("selectAll");
        return;
      }
      if (action === "paste") {
        let text = "";
        try {
          text = navigator.clipboard ? await navigator.clipboard.readText() : "";
        } catch {
          text = "";
        }
        if (text) document.execCommand("insertText", false, text);
        return;
      }
      document.execCommand(action);
    } catch {
      /* the keyboard shortcuts still work */
    }
  };

  const item = "block w-full text-left px-3 py-1.5 hover:bg-[#262a33] rounded-lg";
  const left = Math.min(menu.x, (window.innerWidth || 1024) - 170);
  const top = Math.min(menu.y, (window.innerHeight || 768) - 170);
  return (
    <div
      ref={ref}
      role="menu"
      className="fixed z-[10000] w-40 p-1 bg-[#15171c] border border-[#262a33] rounded-xl shadow-2xl text-xs text-white"
      style={{ left, top }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <button type="button" role="menuitem" className={item} onClick={() => run("cut")} disabled={menu.readOnly}>
        Cut
      </button>
      <button type="button" role="menuitem" className={item} onClick={() => run("copy")}>
        Copy
      </button>
      <button type="button" role="menuitem" className={item} onClick={() => run("paste")} disabled={menu.readOnly}>
        Paste
      </button>
      <button type="button" role="menuitem" className={item} onClick={() => run("selectAll")}>
        Select all
      </button>
    </div>
  );
}

export default function AntiTamperGuard({ children }) {
  const [toastNotice, setToastNotice] = useState(null);
  const [fieldMenu, setFieldMenu] = useState(null);
  const toastTimer = useRef(null);
  const closeFieldMenu = useCallback(() => setFieldMenu(null), []);

  useEffect(() => {
    const showNotice = (msg) => {
      setToastNotice(msg);
      clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setToastNotice(null), 3500);
    };

    // Warn people who are told to paste something into the console (self-XSS).
    try {
      console.log(
        "%cStop!",
        "color: #f87171; font-size: 28px; font-weight: bold;"
      );
      console.log(
        "%cThis is a browser feature for developers. If someone told you to paste something here, it is a scam that can give them your account.",
        "font-size: 13px;"
      );
    } catch {
      /* no console */
    }

    const handleKeyDown = (e) => {
      const hit = isDevtoolsShortcut(e);
      if (!hit) return;
      e.preventDefault();
      e.stopPropagation();
      if (hit === "inspect") showNotice("Developer tools are turned off on this site.");
      else if (hit === "source") showNotice("Viewing the page source is turned off.");
    };

    const handleContextMenu = (e) => {
      const target = e.target;
      if (isTextField(target)) {
        if (isTouchPress(e)) return;
        e.preventDefault();
        setFieldMenu({
          x: e.clientX,
          y: e.clientY,
          field: target,
          readOnly: Boolean(target.readOnly),
        });
        return;
      }
      // Manga cards: right-click opens the manga in a new tab (Shift/Win +
      // right-click: a new window) instead of the browser menu.
      if (handleMangaContextMenu(e)) return;
      e.preventDefault();
      showNotice("Right-click is turned off on this site.");
    };

    window.addEventListener("keydown", handleKeyDown, true);
    window.addEventListener("contextmenu", handleContextMenu, true);

    return () => {
      clearTimeout(toastTimer.current);
      window.removeEventListener("keydown", handleKeyDown, true);
      window.removeEventListener("contextmenu", handleContextMenu, true);
    };
  }, []);

  return (
    <>
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
      {fieldMenu && <TextFieldMenu menu={fieldMenu} onClose={closeFieldMenu} />}
      {children}
    </>
  );
}
