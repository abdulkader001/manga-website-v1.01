import React, { useEffect, useState } from "react";
import api from "../services/api";
import SupportLinks from "./SupportLinks";
import FunctionGate from "./FunctionGate";
import CONFIG from "../config";
import useAuth from "../hooks/useAuth";
import useBranding, { DEFAULT_LOGO, DEFAULT_TAGLINE } from "../hooks/useBranding";
import useStaffPermissions from "../hooks/useStaffPermissions";

// What visitors see until the owner saves the footer (Admin).
const defaultCopyright = (name) => `© ${new Date().getFullYear()} ${name}. All rights reserved.`;

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
  // The site's name, logo and tagline as the owner saved them (same for
  // everyone); only the branding power sees the pencil to change them.
  const { user } = useAuth();
  const branding = useBranding();
  const brandName = branding.name;
  const brandLogo = branding.logo;
  const brandTagline = branding.tagline;
  const { can } = useStaffPermissions();
  const canEditBranding = Boolean(user) && can("configure_branding");
  const [brandError, setBrandError] = useState("");
  const [brandSaving, setBrandSaving] = useState(false);

  const [footerData, setFooterData] = useState({
    copyright: "",
    disclaimer: "Disclaimer: All manga, manhwa, and manhua content are property of their respective creators and publishers.",
    // No links until the owner adds the site's own (they used to point at
    // another site's Discord, X, Telegram and Reddit).
    social_links: [],
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
            copyright: data.copyright || "",
            disclaimer: data.disclaimer || "Disclaimer: All manga content are property of their respective creators.",
            social_links: Array.isArray(data.social_links) ? data.social_links : [],
          });
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

    window.addEventListener("mgeko_footer_updated", handleFooterUpdated);

    return () => {
      window.removeEventListener("mgeko_footer_updated", handleFooterUpdated);
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
    setBrandError("");
    setEditBrandModalOpen(true);
  };

  const handleSaveBrand = async (e) => {
    e?.preventDefault();
    const finalName = tempBrandName.trim() || CONFIG.BRAND_NAME;
    const finalLogo = tempBrandLogo.trim() || DEFAULT_LOGO;
    const finalTagline = tempBrandTagline.trim() || DEFAULT_TAGLINE;
    // Saved on the server for every visitor, or not at all.
    setBrandSaving(true);
    setBrandError("");
    try {
      await branding.save({ name: finalName, logo_url: finalLogo, tagline: finalTagline });
      setEditBrandModalOpen(false);
    } catch (err) {
      setBrandError(
        err?.code === "REVERIFICATION_REQUIRED"
          ? "Enter your authenticator code in the admin area first, then save again."
          : err?.message || "The change could not be saved."
      );
    } finally {
      setBrandSaving(false);
    }
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
                  {canEditBranding && (
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
                  )}
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

          <FunctionGate name="support_links">
            <SupportLinks />
          </FunctionGate>

          {/* Disclaimer & Copyright */}
          <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-[#8b93a3] text-center md:text-left">
            <p className="max-w-xl text-[11px] leading-relaxed">
              {footerData.disclaimer}
            </p>
            <div className="text-xs font-semibold text-gray-300 whitespace-nowrap">
              {footerData.copyright || defaultCopyright(brandName)}
            </div>
          </div>
        </div>
      </footer>

      {/* Edit Brand & Tagline Modal */}
      {editBrandModalOpen && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
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
                  <span className="text-xl leading-none">{tempBrandLogo || DEFAULT_LOGO}</span>
                )}
                <div>
                  <div className="font-extrabold text-white text-xs uppercase">{tempBrandName || CONFIG.BRAND_NAME}</div>
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
                placeholder="e.g. MangaWorld, AnimeScans"
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
                    setTempBrandLogo(DEFAULT_LOGO);
                  }
                }}
                placeholder="https://example.com/logo.png"
                className="w-full bg-[#1f2330] border border-[#374151] rounded-lg p-2.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0] font-mono"
              />
            </div>

            {brandError && (
              <p role="alert" className="text-[11px] text-red-400">
                {brandError}
              </p>
            )}

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
                disabled={brandSaving}
                className="px-4 py-1.5 rounded-lg bg-[#00AEF0] text-white text-xs font-bold hover:bg-[#0F5065] transition shadow-md flex items-center gap-1.5 disabled:opacity-50"
              >
                <i className="fas fa-check text-xs"></i>
                <span>{brandSaving ? "Saving…" : "Save Changes"}</span>
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
