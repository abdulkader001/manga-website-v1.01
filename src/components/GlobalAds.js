import FunctionGate from "./FunctionGate";
import React, { createContext, useContext, useState, useEffect } from "react";
import { apiFetch } from "../services/api";

const AdsContext = createContext({});

export function AdsProvider({ children }) {
  const [adsEnabled, setAdsEnabled] = useState(true);
  return (
    <AdsContext.Provider value={{ adsEnabled, setAdsEnabled }}>
      {children}
    </AdsContext.Provider>
  );
}

function AdSectionInner({ sectionKey, className = "", fallback = null }) {
  const { adsEnabled } = useContext(AdsContext);
  const [ad, setAd] = useState(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let isMounted = true;
    apiFetch("/api/v1/ad-slots")
      .then((res) => (res.ok ? res.json() : []))
      .then((slots) => {
        if (!isMounted || !Array.isArray(slots)) return;
        const matching = slots.find(
          (s) => (s.placement === sectionKey || s.slot_key === sectionKey) && s.enabled !== false
        );
        if (matching) {
          setAd(matching);
        }
      })
      .catch(() => {});

    return () => {
      isMounted = false;
    };
  }, [sectionKey]);

  if (!adsEnabled || dismissed || !ad) return fallback;

  return (
    <div
      className={`relative my-2.5 mx-auto w-full max-w-[1240px] rounded-xl overflow-hidden border border-[#262a33] bg-[#101216] shadow-sm group ${className}`}
    >
      <div className="absolute top-1.5 left-2 z-10 pointer-events-none">
        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-black/75 text-[#8b93a3] border border-[#262a33]">
          Ad
        </span>
      </div>

      {/* Cross / Close Button — Sized comfortably (22px) in corner */}
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="absolute top-1.5 right-1.5 z-20 w-6 h-6 rounded-full bg-black/80 hover:bg-red-600 text-gray-300 hover:text-white border border-[#262a33] hover:border-red-500 flex items-center justify-center text-xs font-bold transition shadow-md active:scale-90"
        title="Close advertisement"
        aria-label="Close advertisement"
      >
        ✕
      </button>

      <a
        href={ad.link_url || "#"}
        target="_blank"
        rel="noopener noreferrer"
        className="block w-full overflow-hidden"
      >
        {ad.image_url ? (
          <img
            src={ad.image_url}
            alt={ad.alt_text || "Ad"}
            className="w-full h-auto max-h-[140px] object-cover hover:opacity-95 transition"
            loading="lazy"
          />
        ) : (ad.html_code || ad.code) ? (
          <div
            className="p-3 text-center text-xs"
            dangerouslySetInnerHTML={{ __html: ad.html_code || ad.code }}
          />
        ) : null}
      </a>
    </div>
  );
}

// The owner can switch ads off for the whole site (Admin -> Site Functions).
export default function AdSection(props) {
  return (
    <FunctionGate name="ads" fallback={props.fallback ?? null}>
      <AdSectionInner {...props} />
    </FunctionGate>
  );
}
