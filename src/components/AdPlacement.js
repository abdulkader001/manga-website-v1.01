import React, { useState, useEffect } from "react";
import { auditUrlSecurity } from "../utils/urlValidator";
import { apiFetch } from "../services/api";

export default function AdPlacement({ placement, className = "" }) {
  const [ad, setAd] = useState(null);
  const [dismissed, setDismissed] = useState(() => {
    try {
      return sessionStorage.getItem(`ad_dismissed_${placement}`) === "true";
    } catch {
      return false;
    }
  });

  const handleDismiss = () => {
    setDismissed(true);
    try {
      sessionStorage.setItem(`ad_dismissed_${placement}`, "true");
    } catch {}
  };

  useEffect(() => {
    let isMounted = true;
    apiFetch("/api/v1/ad-slots")
      .then((res) => (res.ok ? res.json() : []))
      .then((slots) => {
        if (!isMounted || !Array.isArray(slots)) return;
        const matching = slots.find(
          (s) => (s.placement === placement || s.slot_key === placement) && s.enabled !== false
        );
        if (matching) {
          setAd(matching);
        } else {
          // If deleted or not configured, strictly do not render any ad
          setAd(null);
        }
      })
      .catch(() => {
        if (isMounted) setAd(null);
      });

    return () => {
      isMounted = false;
    };
  }, [placement]);

  if (dismissed || !ad) return null;

  // Real-time Antivirus & URL Threat Intelligence verification
  const linkAudit = ad.link_url ? auditUrlSecurity(ad.link_url) : { isSafe: true };
  const safeLink = linkAudit.isSafe ? ad.link_url : "#";

  return (
    <div
      className={`relative my-3 mx-auto w-full max-w-[1240px] rounded-xl overflow-hidden border border-[#262a33] bg-[#101216] shadow-md group ${className}`}
    >
      {/* Sponsor / Ad label badge */}
      <div className="absolute top-1.5 left-2 z-10 pointer-events-none">
        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-black/75 text-[#8b93a3] border border-[#262a33]">
          Ad
        </span>
      </div>

      {/* Dismiss / Close (✕) Button — Sized comfortably (22px) without covering the ad creative */}
      <button
        type="button"
        onClick={handleDismiss}
        className="absolute top-1.5 right-1.5 z-20 w-6 h-6 rounded-full bg-black/80 hover:bg-red-600 text-gray-300 hover:text-white border border-[#262a33] hover:border-red-500 flex items-center justify-center text-xs font-bold transition shadow-md active:scale-90"
        title="Close advertisement"
        aria-label="Close advertisement"
      >
        ✕
      </button>

      {/* Ad Graphic & Link */}
      <a
        href={safeLink || "#"}
        target="_blank"
        rel="noopener noreferrer"
        className="block w-full overflow-hidden"
      >
        {ad.image_url ? (
          <img
            src={ad.image_url}
            alt={ad.alt_text || ad.name || "Advertisement"}
            className="w-full h-auto max-h-[140px] sm:max-h-[180px] object-cover transition duration-300 hover:opacity-95"
            loading="lazy"
          />
        ) : (ad.html_code || ad.code) ? (
          <div
            className="p-4 text-center text-xs text-gray-400"
            dangerouslySetInnerHTML={{ __html: ad.html_code || ad.code }}
          />
        ) : (
          <div className="py-4 text-center text-xs text-[#8b93a3]">
            <span>{ad.name || "Sponsored Partner"}</span>
          </div>
        )}
      </a>
    </div>
  );
}
