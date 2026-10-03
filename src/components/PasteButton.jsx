import React, { useState } from "react";
import { extractLinks, firstLink } from "../utils/links";

// A "Paste" button for address boxes: reads the clipboard and fills the box.
// With `multiple`, every address found is handed over (one per line);
// otherwise the first one. Browsers that don't allow reading the clipboard
// (or a refused permission) get a short hint to use Ctrl+V instead.
export default function PasteButton({ onPaste, multiple = false, label = "Paste", className = "" }) {
  const [hint, setHint] = useState("");

  const handleClick = async () => {
    try {
      if (!navigator.clipboard || !navigator.clipboard.readText) throw new Error("unsupported");
      const text = await navigator.clipboard.readText();
      if (!String(text || "").trim()) {
        setHint("The clipboard is empty.");
        return;
      }
      if (multiple) {
        const links = extractLinks(text);
        onPaste(links.length ? links.join("\n") : String(text).trim());
      } else {
        onPaste(firstLink(text));
      }
      setHint("");
    } catch {
      setHint("Press Ctrl+V (or long-press, then Paste) in the box.");
    }
  };

  return (
    <span className="inline-flex flex-col items-stretch">
      <button
        type="button"
        onClick={handleClick}
        title="Paste from clipboard"
        aria-label={label}
        className={
          className ||
          "px-3 py-2.5 rounded-xl bg-[#1d2027] hover:bg-[#262a33] border border-[#262a33] text-xs font-bold text-gray-200 flex items-center justify-center gap-1.5 whitespace-nowrap"
        }
      >
        <i className="fas fa-paste"></i>
        <span>{label}</span>
      </button>
      {hint && (
        <span role="status" className="text-[10px] text-amber-300 mt-1">
          {hint}
        </span>
      )}
    </span>
  );
}
