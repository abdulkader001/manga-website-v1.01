import React, { useEffect, useState } from "react";
import api from "../services/api";
import { updateFavicon } from "../utils/favicon";

const PRESET_LOGOS = [
  { icon: "🦎", name: "Gecko / Lizard" },
  { icon: "📖", name: "Manga Book" },
  { icon: "⚡", name: "Thunder / Lightning" },
  { icon: "🦊", name: "Kitsune / Fox" },
  { icon: "⚔️", name: "Crossed Blades" },
  { icon: "👑", name: "Crown" },
  { icon: "⛩️", name: "Torii Shrine" },
  { icon: "🐱", name: "Neko / Cat" },
  { icon: "🌸", name: "Cherry Blossom" },
  { icon: "🔥", name: "Inferno Flame" },
  { icon: "🚀", name: "Rocket" },
  { icon: "🛡️", name: "Hero Shield" },
  { icon: "🐉", name: "Mythic Dragon" },
  { icon: "💀", name: "Necromancer" },
  { icon: "💎", name: "Crystal Gem" },
];

export default function Footer() {
  const [brandName, setBrandName] = useState(() => {
    return localStorage.getItem("mgeko_custom_brand") || "MGEKO.CC";
  });
  const [brandLogo, setBrandLogo] = useState(() => {
    return localStorage.getItem("mgeko_custom_logo") || "🦎";
  });
  const [brandTagline, setBrandTagline] = useState(() => {
    return localStorage.getItem("mgeko_custom_tagline") || "Fan Comics & Fast Manga Reader Engine";
  });

  const [footerData, setFooterData] = useState({
    copyright: "© 2026 mgeko.cc. All rights reserved.",
    disclaimer: "Disclaimer: All manga, manhwa, and manhua content are property of their respective creators and publishers.",
    social_links: [
      { id: 1, platform: "discord", title: "Discord Community", url: "https://discord.gg/mgeko", icon: "fab fa-discord", enabled: true },
      { id: 2, platform: "twitter", title: "Twitter / X Updates", url: "https://x.com/mgekocc", icon: "fab fa-x-twitter", enabled: true },
      { id: 3, platform: "telegram", title: "Telegram Channel", url: "https://t.me/mgeko_updates", icon: "fab fa-telegram", enabled: true },
      { id: 4, platform: "reddit", title: "Reddit Community", url: "https://reddit.com/r/mgeko", icon: "fab fa-reddit", enabled: true },
      { id: 5, platform: "email", title: "Contact & Support", url: "mailto:contact@mgeko.cc", icon: "fas fa-envelope", enabled: true },
    ],
  });

  // Modal Editor for Footer Brand & Info
  const [editBrandModalOpen, setEditBrandModalOpen] = useState(false);
  const [tempBrandName, setTempBrandName] = useState(brandName);
  const [tempBrandLogo, setTempBrandLogo] = useState(brandLogo);
  const [tempBrandTagline, setTempBrandTagline] = useState(brandTagline);
  const [customLogoUrl, setCustomLogoUrl] = useState(() => {
    return (brandLogo.startsWith("http://") || brandLogo.startsWith("https://") || brandLogo.startsWith("data:") || brandLogo.startsWith("/"))
      ? brandLogo
      : "";
  });

  const fetchFooter = () => {
    api.footer
      .get()
      .then((data) => {
        if (data) {
          setFooterData({
            copyright: data.copyright || "© 2026 mgeko.cc. All rights reserved.",
            disclaimer: data.disclaimer || "Disclaimer: All manga content are property of their respective creators.",
            social_links: Array.isArray(data.social_links) && data.social_links.length > 0 ? data.social_links : footerData.social_links,
          });
          if (data.site_name && !localStorage.getItem("mgeko_custom_brand")) {
            setBrandName(data.site_name);
          }
          if (data.tagline && !localStorage.getItem("mgeko_custom_tagline")) {
            setBrandTagline(data.tagline);
          }
          if (data.logo_url && !localStorage.getItem("mgeko_custom_logo")) {
            setBrandLogo(data.logo_url);
          }
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    fetchFooter();

    const handleFooterUpdated = (e) => {
      if (e?.detail?.social_links) {
        setFooterData((prev) => ({ ...prev, social_links: e.detail.social_links }));
      } else {
        fetchFooter();
      }
    };

    const handleBrandingUpdated = (e) => {
      if (e?.detail) {
        if (e.detail.name) setBrandName(e.detail.name);
        if (e.detail.logo) setBrandLogo(e.detail.logo);
        if (e.detail.tagline) setBrandTagline(e.detail.tagline);
      }
    };

    window.addEventListener("mgeko_footer_updated", handleFooterUpdated);
    window.addEventListener("mgeko_branding_updated", handleBrandingUpdated);

    return () => {
      window.removeEventListener("mgeko_footer_updated", handleFooterUpdated);
      window.removeEventListener("mgeko_branding_updated", handleBrandingUpdated);
    };
  }, []);

  const isImageUrl = (val) => {
    if (!val || typeof val !== "string") return false;
    return val.startsWith("http://") || val.startsWith("https://") || val.startsWith("data:") || val.startsWith("/");
  };

  const handleOpenBrandModal = () => {
    setTempBrandName(brandName);
    setTempBrandLogo(brandLogo);
    setTempBrandTagline(brandTagline);
    setCustomLogoUrl(isImageUrl(brandLogo) ? brandLogo : "");
    setEditBrandModalOpen(true);
  };

  const handleSaveBrand = async (e) => {
    e?.preventDefault();
    const finalName = tempBrandName.trim() || "MGEKO.CC";
    const finalLogo = tempBrandLogo.trim() || "🦎";
    const finalTagline = tempBrandTagline.trim() || "Fan Comics & Fast Manga Reader Engine";

    setBrandName(finalName);
    setBrandLogo(finalLogo);
    setBrandTagline(finalTagline);

    localStorage.setItem("mgeko_custom_brand", finalName);
    localStorage.setItem("mgeko_custom_logo", finalLogo);
    localStorage.setItem("mgeko_custom_tagline", finalTagline);

    updateFavicon(finalLogo);
    document.title = `${finalName} - Manga Updates & Browse`;

    try {
      window.dispatchEvent(
        new CustomEvent("mgeko_branding_updated", {
          detail: { name: finalName, logo: finalLogo, tagline: finalTagline },
        })
      );
    } catch {}

    setEditBrandModalOpen(false);

    try {
      await fetch("/api/v1/branding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: finalName, logo_url: finalLogo, tagline: finalTagline }),
      });
    } catch {}
  };

  const activeSocials = (footerData.social_links || []).filter((l) => l.enabled !== false);

  return (
    <>
      <footer className="mt-16 bg-[#101216] border-t border-[#262a33] text-gray-400 py-10 px-4">
        <div className="max-w-6xl mx-auto space-y-6">
          <div className="flex flex-col md:flex-row items-center justify-between gap-6 pb-6 border-b border-[#262a33]/60">
            {/* Brand Logo & Info (Editable) */}
            <div className="flex items-center gap-3 group relative cursor-pointer" onClick={handleOpenBrandModal} title="Click to edit website brand, logo, and tagline">
              {isImageUrl(brandLogo) ? (
                <img
                  src={brandLogo}
                  alt={brandName}
                  className="w-9 h-9 object-contain rounded-lg flex-none shadow"
                  onError={(e) => {
                    e.target.style.display = "none";
                  }}
                />
              ) : (
                <span className="text-3xl select-none leading-none">{brandLogo}</span>
              )}
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-white font-extrabold text-base tracking-wide uppercase">{brandName}</span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleOpenBrandModal();
                    }}
                    className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-[#00AEF0] transition p-1 text-xs rounded hover:bg-[#1f2330]"
                    title="Edit brand name, logo, and tagline"
                  >
                    <i className="fas fa-pencil-alt text-[10px]"></i>
                  </button>
                </div>
                <p className="text-xs text-[#8b93a3]">{brandTagline}</p>
              </div>
            </div>

            {/* Dynamic Social Media Channels & Community Handles */}
            {activeSocials.length > 0 && (
              <div className="flex flex-wrap items-center justify-center gap-3 text-xs font-semibold">
                {activeSocials.map((social) => (
                  <a
                    key={social.id}
                    href={social.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 rounded-xl bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] hover:border-[#00AEF0] text-gray-300 hover:text-white transition flex items-center gap-2 shadow-sm"
                    title={social.title}
                  >
                    {social.custom_icon_url ? (
                      <img src={social.custom_icon_url} alt={social.title} className="w-3.5 h-3.5 object-contain rounded" />
                    ) : (
                      <i className={`${social.icon || "fas fa-link"} text-[#00AEF0] text-xs`}></i>
                    )}
                    <span>{social.title}</span>
                  </a>
                ))}
              </div>
            )}
          </div>

          {/* Disclaimer & Copyright */}
          <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-[#8b93a3] text-center md:text-left">
            <p className="max-w-xl text-[11px] leading-relaxed">
              {footerData.disclaimer}
            </p>
            <div className="text-xs font-semibold text-gray-300 whitespace-nowrap">
              {footerData.copyright}
            </div>
          </div>
        </div>
      </footer>

      {/* Edit Brand & Tagline Modal */}
      {editBrandModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <form
            onSubmit={handleSaveBrand}
            className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-md w-full p-5 shadow-2xl space-y-4 text-xs"
          >
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <div className="flex items-center gap-2">
                <span className="text-lg">🎨</span>
                <h3 className="text-sm font-bold text-white">Edit Footer Brand, Logo &amp; Tagline</h3>
              </div>
              <button
                type="button"
                onClick={() => setEditBrandModalOpen(false)}
                className="text-gray-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            {/* Live Preview */}
            <div className="bg-[#101216] border border-[#262a33] rounded-xl p-3 flex items-center justify-between">
              <div className="text-[11px] text-gray-400">Preview:</div>
              <div className="flex items-center gap-2 bg-[#15171c] px-3 py-1.5 rounded-lg border border-[#374151]">
                {isImageUrl(tempBrandLogo) ? (
                  <img src={tempBrandLogo} alt="Preview" className="w-6 h-6 object-contain rounded" />
                ) : (
                  <span className="text-xl leading-none">{tempBrandLogo || "🦎"}</span>
                )}
                <div>
                  <div className="font-extrabold text-white text-xs uppercase">{tempBrandName || "MGEKO.CC"}</div>
                  <div className="text-[10px] text-[#8b93a3]">{tempBrandTagline || "Fan Comics & Fast Manga Reader"}</div>
                </div>
              </div>
            </div>

            {/* Brand Name Input */}
            <div className="space-y-1">
              <label className="font-bold text-gray-300 block">Website / Brand Name</label>
              <input
                type="text"
                required
                value={tempBrandName}
                onChange={(e) => setTempBrandName(e.target.value)}
                placeholder="e.g. MGEKO.CC, MangaWorld, AnimeScans"
                className="w-full bg-[#1f2330] border border-[#374151] rounded-lg p-2.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0]"
              />
            </div>

            {/* Brand Tagline Input */}
            <div className="space-y-1">
              <label className="font-bold text-gray-300 block">Tagline / Subtitle Description</label>
              <input
                type="text"
                required
                value={tempBrandTagline}
                onChange={(e) => setTempBrandTagline(e.target.value)}
                placeholder="e.g. Fan Comics & Fast Manga Reader Engine"
                className="w-full bg-[#1f2330] border border-[#374151] rounded-lg p-2.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0]"
              />
            </div>

            {/* Logo Presets */}
            <div className="space-y-1.5">
              <label className="font-bold text-gray-300 block">Choose Icon / Emoji</label>
              <div className="grid grid-cols-5 gap-2 max-h-32 overflow-y-auto p-1.5 bg-[#101216] rounded-xl border border-[#262a33]">
                {PRESET_LOGOS.map((item) => (
                  <button
                    key={item.icon}
                    type="button"
                    onClick={() => {
                      setTempBrandLogo(item.icon);
                      setCustomLogoUrl("");
                    }}
                    title={item.name}
                    className={`flex flex-col items-center justify-center p-2 rounded-lg transition border ${
                      tempBrandLogo === item.icon
                        ? "bg-[#00AEF0]/20 border-[#00AEF0] text-white scale-105"
                        : "bg-[#15171c] border-[#262a33] text-gray-300 hover:border-gray-500"
                    }`}
                  >
                    <span className="text-xl">{item.icon}</span>
                    <span className="text-[9px] truncate w-full text-center mt-1 text-gray-400">{item.name.split("/")[0]}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Custom Logo Image URL */}
            <div className="space-y-1">
              <label className="font-bold text-gray-300 block">Or Custom Image URL</label>
              <input
                type="url"
                value={customLogoUrl}
                onChange={(e) => {
                  setCustomLogoUrl(e.target.value);
                  if (e.target.value.trim()) {
                    setTempBrandLogo(e.target.value.trim());
                  } else {
                    setTempBrandLogo("🦎");
                  }
                }}
                placeholder="https://example.com/logo.png"
                className="w-full bg-[#1f2330] border border-[#374151] rounded-lg p-2.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0] font-mono"
              />
            </div>

            {/* Modal Actions */}
            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setEditBrandModalOpen(false)}
                className="px-3.5 py-1.5 rounded-lg bg-gray-800 text-gray-300 text-xs font-semibold hover:bg-gray-700 transition"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 rounded-lg bg-[#00AEF0] text-white text-xs font-bold hover:bg-[#0F5065] transition shadow-md flex items-center gap-1.5"
              >
                <i className="fas fa-check text-xs"></i>
                <span>Save Changes</span>
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
