import { AVATAR_PLACEHOLDER } from "../utils/placeholders";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useLocation } from "react-router";
import NotificationBell from "./NotificationBell";
import FunctionGate from "./FunctionGate";
import ThemeToggle from "./ThemeToggle";
import CONFIG from "../config";
import useAuth from "../hooks/useAuth";
import { updateFavicon } from "../utils/favicon";
import { maskEmail } from "../utils/maskEmail";
import useBranding, { DEFAULT_LOGO } from "../hooks/useBranding";
import useStaffPermissions from "../hooks/useStaffPermissions";

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

export default function Navbar() {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    user,
    username,
    name,
    isAdmin,
    isSecondaryAdmin,
    login,
    logout,
  } = useAuth();

  // The site's name and logo as the owner saved them (same for everyone).
  // Only someone holding the branding power sees the pencil to change them.
  const branding = useBranding();
  const brandName = branding.name;
  const brandLogo = branding.logo;
  const { can } = useStaffPermissions();
  const canEditBranding = Boolean(user) && can("configure_branding");
  const [brandError, setBrandError] = useState("");
  const [brandSaving, setBrandSaving] = useState(false);

  // Branding Modal Editor
  const [brandingModalOpen, setBrandingModalOpen] = useState(false);
  const [tempBrandName, setTempBrandName] = useState(brandName);
  const [tempBrandLogo, setTempBrandLogo] = useState(brandLogo);
  const [customLogoUrl, setCustomLogoUrl] = useState(() => {
    return (brandLogo.startsWith("http://") || brandLogo.startsWith("https://") || brandLogo.startsWith("data:") || brandLogo.startsWith("/"))
      ? brandLogo
      : "";
  });

  // Quick search and user menu states
  const [quickSearchOpen, setQuickSearchOpen] = useState(false);
  const [quickQuery, setQuickQuery] = useState("");
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef(null);

  const isUserAdmin = user?.is_admin === true || isAdmin || isSecondaryAdmin;

  // Sync favicon and document title on mount & update
  useEffect(() => {
    updateFavicon(brandLogo);
    document.title = `${brandName} - Manga Updates & Browse`;
  }, [brandLogo, brandName]);

  const at = (path) => location.pathname === path;

  // Close user dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event) {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleQuickSearchSubmit = (e) => {
    e.preventDefault();
    if (quickQuery.trim()) {
      navigate(`/browse?search=${encodeURIComponent(quickQuery.trim())}`);
      setQuickSearchOpen(false);
      setQuickQuery("");
    }
  };

  const handleOpenBrandingModal = () => {
    setTempBrandName(brandName);
    setTempBrandLogo(brandLogo);
    setCustomLogoUrl(
      (brandLogo.startsWith("http://") || brandLogo.startsWith("https://") || brandLogo.startsWith("data:") || brandLogo.startsWith("/"))
        ? brandLogo
        : ""
    );
    setBrandError("");
    setBrandingModalOpen(true);
  };

  const handleSaveBranding = async (e) => {
    e?.preventDefault();
    const finalName = tempBrandName.trim() || CONFIG.BRAND_NAME;
    const finalLogo = tempBrandLogo.trim() || DEFAULT_LOGO;
    // Saved on the server for every visitor, or not at all: nothing is kept
    // in this browser only.
    setBrandSaving(true);
    setBrandError("");
    try {
      await branding.save({ name: finalName, logo_url: finalLogo });
      setBrandingModalOpen(false);
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

  const isImageUrl = (val) => {
    if (!val || typeof val !== "string") return false;
    return val.startsWith("http://") || val.startsWith("https://") || val.startsWith("data:") || val.startsWith("/");
  };

  return (
    <>
      <header className="mgeko-header w-full sticky top-0 z-50">
        <div className="max-w-[1240px] mx-auto px-3 sm:px-4 py-2 sm:py-2.5">
          {/* Main Top Header Bar: Logo + Brand on left, User & Controls on right */}
          <div className="flex items-center justify-between gap-2">
            {/* Logo & Changeable Website Box */}
            <div className="flex items-center gap-1.5 group min-w-0">
              <Link to="/" className="flex items-center gap-1.5 text-white font-extrabold text-base sm:text-xl tracking-tight hover:opacity-90 truncate">
                {isImageUrl(brandLogo) ? (
                  <img
                    src={brandLogo}
                    alt={brandName}
                    className="w-6 h-6 sm:w-7 sm:h-7 object-contain rounded-md flex-none shadow-sm"
                    onError={(e) => {
                      e.target.style.display = "none";
                    }}
                  />
                ) : (
                  <span className="text-[#00AEF0] text-xl sm:text-2xl flex-none leading-none select-none">
                    {brandLogo}
                  </span>
                )}
                <span className="truncate max-w-[140px] sm:max-w-xs">{brandName}</span>
              </Link>

              {/* Change Website Name & Favicon/Logo: branding power only */}
              {canEditBranding && (
              <button
                type="button"
                onClick={handleOpenBrandingModal}
                title="Change website name & picture/favicon"
                className="opacity-60 group-hover:opacity-100 hover:text-[#00AEF0] text-gray-400 p-1 text-xs transition rounded hover:bg-[#15171c] flex-none"
              >
                <i className="fas fa-pencil-alt text-[10px]"></i>
              </button>
              )}
            </div>

            {/* Desktop Navigation Links (Visible on md+ screens) */}
            <nav className="hidden md:flex items-center gap-5 text-sm font-semibold">
              <Link
                to="/"
                className={`nav-link ${at("/") ? "active text-[#00AEF0]" : "text-gray-300"} hover:text-[#00AEF0] transition flex items-center gap-1.5`}
              >
                <i className="fas fa-home text-sm"></i>
                <span>Homepage</span>
              </Link>

              <Link
                to="/browse"
                className={`nav-link ${at("/browse") ? "active text-[#00AEF0]" : "text-gray-300"} hover:text-[#00AEF0] transition flex items-center gap-1.5`}
              >
                <i className="fab fa-safari text-sm"></i>
                <span>Browse</span>
              </Link>

              <Link
                to="/bookmarks"
                className={`nav-link ${at("/bookmarks") ? "active text-[#00AEF0]" : "text-gray-300"} hover:text-[#00AEF0] transition flex items-center gap-1.5`}
              >
                <i className="fas fa-bookmark text-sm"></i>
                <span>Bookmarks</span>
              </Link>
            </nav>

            {/* Right-hand side: Day/Night Toggle, Notification Bell, Quick Search, User Menu Dropdown */}
            <div className="flex items-center gap-1 sm:gap-2 flex-shrink-0">
              {/* Day / Night Mode Toggle */}
              <ThemeToggle />

              {/* Notification Bell */}
              {/* Guests have no notifications: polling would only collect 401s. */}
              {user && (
                <FunctionGate name="notifications">
                  <NotificationBell />
                </FunctionGate>
              )}

              {/* Quick Search Button */}
              <button
                type="button"
                onClick={() => setQuickSearchOpen(!quickSearchOpen)}
                className="p-1.5 text-gray-300 hover:text-[#00AEF0] hover:bg-[#15171c] rounded-lg transition flex items-center gap-1 text-xs"
                title="Quick search by title"
              >
                <i className="fas fa-search text-xs sm:text-sm"></i>
              </button>

              {/* User Account / Hello Username Dropdown */}
              {user ? (
                <div className="relative" ref={userMenuRef}>
                  <button
                    type="button"
                    onClick={() => setUserMenuOpen(!userMenuOpen)}
                    className="flex items-center gap-1.5 text-[11px] sm:text-xs text-gray-200 hover:text-[#00AEF0] bg-[#15171c] border border-[#262a33] hover:border-[#00AEF0] px-2 py-1 rounded-xl transition shadow-sm"
                  >
                    <img
                      src={user.profile_image || AVATAR_PLACEHOLDER}
                      alt={username || name || "User"}
                      className="w-4 h-4 sm:w-5 sm:h-5 rounded-full object-cover border border-[#00AEF0]"
                    />
                    <span className="truncate max-w-[70px] sm:max-w-none">
                      <span className="hidden sm:inline">Hello </span>
                      <strong className="text-white">{username || name || "User"}</strong>
                    </span>
                    <i className={`fas fa-chevron-down text-[9px] text-gray-400 transition-transform ${userMenuOpen ? "rotate-180" : ""}`}></i>
                  </button>

                  {userMenuOpen && (
                    <div className="absolute right-0 mt-2 w-56 bg-[#15171c] border border-[#262a33] rounded-2xl shadow-2xl py-2 z-50 text-xs divide-y divide-[#262a33]">
                      {/* User info banner */}
                      <div className="px-3.5 py-2 flex items-center gap-2.5">
                        <img
                          src={user.profile_image || AVATAR_PLACEHOLDER}
                          alt="Profile"
                          className="w-8 h-8 rounded-full object-cover border border-[#00AEF0]"
                        />
                        <div className="min-w-0">
                          <div className="font-bold text-white truncate">{username || name || "User"}</div>
                          <div className="text-[10px] text-[#8b93a3] truncate font-mono">{user.email ? maskEmail(user.email) : (isUserAdmin ? "Administrator" : "Reader")}</div>
                          {user.age != null && (
                            <span className={`text-[9px] font-bold px-1.5 py-0.2 rounded-full mt-0.5 inline-block ${user.is_under_18 ? "bg-amber-500/20 text-amber-300" : "bg-emerald-500/20 text-emerald-300"}`}>
                              Age: {user.age} {user.is_under_18 ? "(Under 18)" : "(18+)"}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Navigation inside user menu */}
                      <div className="py-1">
                        <Link
                          to="/settings"
                          onClick={() => setUserMenuOpen(false)}
                          className="flex items-center gap-2 px-3.5 py-1.5 text-gray-300 hover:bg-[#252a38] hover:text-[#00AEF0] transition"
                        >
                          <i className="fas fa-cog w-4 text-[#00AEF0]"></i>
                          <span>Settings</span>
                        </Link>

                        {isUserAdmin && (
                          <Link
                            to="/admin"
                            onClick={() => setUserMenuOpen(false)}
                            className="flex items-center gap-2 px-3.5 py-1.5 text-gray-300 hover:bg-[#252a38] hover:text-[#00AEF0] transition"
                          >
                            <i className="fas fa-shield-alt w-4 text-blue-400"></i>
                            <span>Admin Panel</span>
                          </Link>
                        )}
                      </div>

                      {/* Sign Out */}
                      <div className="py-1">
                        <button
                          type="button"
                          onClick={async () => {
                            setUserMenuOpen(false);
                            await logout();
                            if (location.pathname.startsWith("/admin")) navigate("/");
                          }}
                          className="w-full flex items-center gap-2 px-3.5 py-1.5 text-red-400 hover:bg-[#252a38] hover:text-red-300 transition text-left"
                        >
                          <i className="material-icons text-sm w-4">person_pin</i>
                          <span>Sign Out</span>
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <Link
                  to="/login"
                  className="px-2.5 py-1 bg-[#00AEF0] hover:bg-[#0F5065] text-white text-[11px] sm:text-xs font-bold rounded-lg transition flex items-center gap-1 shadow-sm"
                >
                  <i className="fas fa-sign-in-alt text-[10px]"></i>
                  <span>Sign In</span>
                </Link>
              )}
            </div>
          </div>

          {/* Mobile Secondary Sub-Nav Bar (Compact, slim 1-row tab bar visible only on < md screens) */}
          <nav className="flex md:hidden items-center justify-around gap-1 pt-1 mt-1 border-t border-[#262a33]/50 text-[10px] sm:text-[11px] font-bold">
            <Link
              to="/"
              className={`px-2.5 py-0.5 rounded-md transition flex items-center gap-1 ${
                at("/") ? "bg-[#00AEF0]/15 text-[#00AEF0] border border-[#00AEF0]/30" : "text-gray-300 hover:text-white"
              }`}
            >
              <i className="fas fa-home text-[10px]"></i>
              <span>Home</span>
            </Link>

            <Link
              to="/browse"
              className={`px-2.5 py-0.5 rounded-md transition flex items-center gap-1 ${
                at("/browse") ? "bg-[#00AEF0]/15 text-[#00AEF0] border border-[#00AEF0]/30" : "text-gray-300 hover:text-white"
              }`}
            >
              <i className="fab fa-safari text-[10px]"></i>
              <span>Browse</span>
            </Link>

            <Link
              to="/bookmarks"
              className={`px-2.5 py-0.5 rounded-md transition flex items-center gap-1 ${
                at("/bookmarks") ? "bg-[#00AEF0]/15 text-[#00AEF0] border border-[#00AEF0]/30" : "text-gray-300 hover:text-white"
              }`}
            >
              <i className="fas fa-bookmark text-[10px]"></i>
              <span>Bookmarks</span>
            </Link>
          </nav>
        </div>
      </header>

      {/* Quick Search Pop-up / Drawer */}
      {quickSearchOpen && (
        <div className="bg-[#15171c] border-b border-[#262a33] px-4 py-3 shadow-2xl sticky top-[49px] z-40">
          <form onSubmit={handleQuickSearchSubmit} className="max-w-2xl mx-auto flex items-center gap-2">
            <div className="relative flex-1">
              <input
                type="search"
                autoFocus
                value={quickQuery}
                onChange={(e) => setQuickQuery(e.target.value)}
                placeholder="Search By Manga Name or Title..."
                className="w-full bg-[#1f2330] border border-[#374151] rounded-lg px-3.5 py-1.5 text-xs text-white placeholder-gray-400 focus:outline-none focus:border-[#00AEF0]"
              />
            </div>
            <button
              type="submit"
              className="px-3.5 py-1.5 bg-[#00AEF0] text-white text-xs font-bold rounded-lg hover:bg-[#0F5065] transition"
            >
              Search
            </button>
            <button
              type="button"
              onClick={() => setQuickSearchOpen(false)}
              className="px-2.5 py-1.5 bg-[#252a38] text-gray-400 text-xs rounded-lg hover:text-white"
            >
              ✕
            </button>
          </form>
        </div>
      )}

      {/* Change Website Name & Favicon/Picture Modal */}
      {brandingModalOpen && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/80 backdrop-blur-sm p-4">
          <form
            onSubmit={handleSaveBranding}
            className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-md w-full p-5 shadow-2xl space-y-4"
          >
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <div className="flex items-center gap-2">
                <span className="text-xl">🎨</span>
                <h3 className="text-base font-bold text-white">Customize Website &amp; Favicon</h3>
              </div>
              <button
                type="button"
                onClick={() => setBrandingModalOpen(false)}
                className="text-gray-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            {/* Live Preview Bar */}
            <div className="bg-[#101216] border border-[#262a33] rounded-xl p-3 flex items-center justify-between">
              <div className="text-xs text-gray-400">Live Preview:</div>
              <div className="flex items-center gap-2 bg-[#15171c] px-3 py-1.5 rounded-lg border border-[#374151]">
                {isImageUrl(tempBrandLogo) ? (
                  <img
                    src={tempBrandLogo}
                    alt="Preview"
                    className="w-6 h-6 object-contain rounded"
                    onError={(e) => {
                      e.target.src = AVATAR_PLACEHOLDER;
                    }}
                  />
                ) : (
                  <span className="text-2xl leading-none">{tempBrandLogo || DEFAULT_LOGO}</span>
                )}
                <span className="font-extrabold text-white text-sm">{tempBrandName || CONFIG.BRAND_NAME}</span>
              </div>
            </div>

            {/* Website Name Field */}
            <div className="space-y-1 text-xs">
              <label className="font-bold text-gray-300 block">Website Name</label>
              <input
                type="text"
                value={tempBrandName}
                onChange={(e) => setTempBrandName(e.target.value)}
                placeholder="e.g. MangaWorld, AnimeScans"
                className="w-full bg-[#1f2330] border border-[#374151] rounded-lg p-2.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0]"
                required
              />
            </div>

            {/* Favicon / Picture Presets */}
            <div className="space-y-1.5 text-xs">
              <div className="flex items-center justify-between">
                <label className="font-bold text-gray-300">Choose Icon / Favicon</label>
                <span className="text-[10px] text-gray-400">Updates browser tab icon</span>
              </div>
              <div className="grid grid-cols-5 gap-2 max-h-36 overflow-y-auto p-1 bg-[#101216] rounded-xl border border-[#262a33]">
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
                    <span className="text-2xl">{item.icon}</span>
                    <span className="text-[9px] truncate w-full text-center mt-1 text-gray-400">{item.name.split("/")[0]}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Or Custom Picture URL */}
            <div className="space-y-1 text-xs">
              <label className="font-bold text-gray-300 block">Or Custom Image / Favicon URL</label>
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
                placeholder="https://example.com/logo.png (or any image URL)"
                className="w-full bg-[#1f2330] border border-[#374151] rounded-lg p-2.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-[#00AEF0]"
              />
            </div>

            {brandError && (
              <p role="alert" className="text-[11px] text-red-400">
                {brandError}
              </p>
            )}

            {/* Buttons */}
            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setBrandingModalOpen(false)}
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
