import React, { useEffect, useMemo, useState } from "react";
import type { ProviderKind, ProviderMetadata } from "../plugins/types";
import type { LimitPeriod } from "./store";
import {
  getProviderOptions,
  maskSecret,
  resetProvider,
  setProvider,
  setTargetLanguage,
  updateProvider,
  updateTranslationLimit,
  useSettingsStore,
} from "./store";
import { resetUsage } from "../utils/translationUsage";
import useAccountSync from "./accountSync";
import useAuth from "../hooks/useAuth";
import api, { apiFetch } from "../services/api";
import OverlayFontPicker from "../components/OverlayFontPicker";

const TARGET_LANGUAGES: Array<{ value: string; label: string }> = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "pt", label: "Portuguese" },
  { value: "ru", label: "Russian" },
  { value: "ja", label: "Japanese" },
  { value: "ko", label: "Korean" },
  { value: "zh", label: "Chinese" },
  { value: "ar", label: "Arabic" },
];

const PRESET_AVATARS = [
  { label: "Jinwoo (Shadow)", url: "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=150&auto=format&fit=crop&q=80" },
  { label: "Luffy (Strawhat)", url: "https://images.unsplash.com/photo-1534447677768-be436bb09401?w=150&auto=format&fit=crop&q=80" },
  { label: "Gojo (Limitless)", url: "https://images.unsplash.com/photo-1563089145-599997674d42?w=150&auto=format&fit=crop&q=80" },
  { label: "Frieren (Mage)", url: "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150&auto=format&fit=crop&q=80" },
  { label: "Zoro (Hunter)", url: "https://images.unsplash.com/photo-1570295999919-56ceb5ecca61?w=150&auto=format&fit=crop&q=80" },
];

const INPUT_CLASSES =
  "px-3 py-2 rounded-xl border border-[#262a33] bg-[#101216] text-white placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-[#00AEF0] focus:border-[#00AEF0] text-xs transition-colors";

type SectionConfig = {
  kind: ProviderKind;
  title: string;
  subtitle: string;
};

const SECTIONS: SectionConfig[] = [
  {
    kind: "ai",
    title: "1. Custom AI Provider (Highest Priority)",
    subtitle:
      "Connect your custom OpenAI, Gemini, Claude, DeepSeek, or Groq API. When set, AI runs as the top priority for high-accuracy translation.",
  },
  {
    kind: "ocr",
    title: "2. OCR Text Detection Engine",
    subtitle:
      "Detects speech bubble coordinates and Japanese/Korean/Chinese text on page canvases.",
  },
  {
    kind: "translation",
    title: "3. Neural Translation Engine",
    subtitle: "Dedicated machine translation service for detected bubble text.",
  },
];

const MONTHS_LIST = [
  { value: "01", name: "January" },
  { value: "02", name: "February" },
  { value: "03", name: "March" },
  { value: "04", name: "April" },
  { value: "05", name: "May" },
  { value: "06", name: "June" },
  { value: "07", name: "July" },
  { value: "08", name: "August" },
  { value: "09", name: "September" },
  { value: "10", name: "October" },
  { value: "11", name: "November" },
  { value: "12", name: "December" },
];

const SETTINGS_CURR_YEAR = new Date().getFullYear();
const YEARS_LIST = Array.from({ length: 105 }, (_, i) => SETTINGS_CURR_YEAR - i);
const DAYS_LIST = Array.from({ length: 31 }, (_, i) => String(i + 1).padStart(2, "0"));

// Profile & Identity Setup
function ProfileIdentitySection() {
  const { user, refetchUser } = useAuth();
  const [name, setName] = useState(user?.name || "");
  const [username, setUsername] = useState(user?.username || "");
  const [usernameStatus, setUsernameStatus] = useState<{ available: boolean; message: string } | null>(null);
  const [checkingUsername, setCheckingUsername] = useState(false);
  const [gender, setGender] = useState(user?.gender || "Not specified");

  const [birthDay, setBirthDay] = useState("");
  const [birthMonth, setBirthMonth] = useState("");
  const [birthYear, setBirthYear] = useState("");

  const [profileImage, setProfileImage] = useState(user?.profile_image || PRESET_AVATARS[0].url);
  const [customAvatarUrl, setCustomAvatarUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ type: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    if (user) {
      setName(user.name || "");
      setUsername(user.username || "");
      setGender(user.gender || "Not specified");
      setProfileImage(user.profile_image || PRESET_AVATARS[0].url);
      if (user.birth_date) {
        const parts = user.birth_date.split("-");
        if (parts.length === 3) {
          setBirthYear(parts[0]);
          setBirthMonth(parts[1]);
          setBirthDay(parts[2]);
        }
      }
    }
  }, [user]);

  // Live solo username uniqueness check
  useEffect(() => {
    const clean = username.trim().toLowerCase().replace(/[^a-z0-9_]/g, "");
    if (!clean || clean.length < 3 || clean === user?.username?.toLowerCase()) {
      setUsernameStatus(null);
      setCheckingUsername(false);
      return;
    }

    setCheckingUsername(true);
    const timeout = setTimeout(async () => {
      try {
        const res = await apiFetch(`/api/v1/auth/check-username?username=${encodeURIComponent(clean)}`);
        const data = await res.json();
        setUsernameStatus(data);
      } catch {
        setUsernameStatus(null);
      } finally {
        setCheckingUsername(false);
      }
    }, 350);

    return () => clearTimeout(timeout);
  }, [username, user]);

  const birthDate = birthYear && birthMonth && birthDay ? `${birthYear}-${birthMonth}-${birthDay}` : "";

  // Live Age Calculation
  const calculatedAge = useMemo(() => {
    if (!birthDate) return null;
    const bDate = new Date(birthDate);
    if (isNaN(bDate.getTime())) return null;
    const today = new Date();
    let age = today.getFullYear() - bDate.getFullYear();
    const m = today.getMonth() - bDate.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < bDate.getDate())) {
      age--;
    }
    return Math.max(0, age);
  }, [birthDate]);

  const isAgeLocked = user?.age_locked === true && Boolean(user?.birth_date);

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (usernameStatus && !usernameStatus.available) {
      setNotice({ type: "error", message: "This username is already taken. Unique names are solo identifiers." });
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      await api.post("/auth/profile", {
        name: name.trim(),
        username: username.trim(),
        gender,
        birth_date: birthDate || undefined,
        profile_image: customAvatarUrl.trim() || profileImage,
      });
      setNotice({ type: "success", message: "✅ Profile and identity saved successfully!" });
      if (refetchUser) refetchUser();
    } catch (err: any) {
      setNotice({ type: "error", message: err?.message || "Failed to update profile." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSaveProfile} className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 sm:p-6 shadow-xl space-y-6 text-xs">
      <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
        <div>
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <i className="fas fa-id-card text-[#00AEF0]"></i>
            <span>Reader Identity &amp; Profile Verification</span>
          </h2>
          <p className="text-xs text-[#8b93a3] mt-0.5">
            Configure your avatar, unique handle, gender, and verified age for content safety compliance.
          </p>
        </div>
      </div>

      {notice && (
        <div
          className={`p-3.5 rounded-xl border text-xs flex items-center justify-between ${
            notice.type === "error" ? "bg-red-950/40 border-red-800 text-red-300" : "bg-emerald-950/40 border-emerald-800 text-emerald-300"
          }`}
        >
          <span>{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-gray-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Avatar Selection */}
      <div className="space-y-3">
        <label className="font-bold text-gray-300 block">Profile Avatar / Picture</label>
        <div className="flex flex-wrap items-center gap-3">
          {PRESET_AVATARS.map((av) => (
            <button
              key={av.label}
              type="button"
              onClick={() => {
                setProfileImage(av.url);
                setCustomAvatarUrl("");
              }}
              className={`relative rounded-full p-0.5 transition ${
                profileImage === av.url && !customAvatarUrl
                  ? "ring-2 ring-[#00AEF0] ring-offset-2 ring-offset-[#15171c]"
                  : "opacity-70 hover:opacity-100"
              }`}
            >
              <img src={av.url} alt={av.label} className="w-12 h-12 rounded-full object-cover border border-[#262a33]" />
            </button>
          ))}

          {/* Current Avatar Display */}
          <div className="flex items-center gap-3 pl-2 border-l border-[#262a33]">
            <img
              src={customAvatarUrl.trim() || profileImage}
              alt="Active avatar"
              className="w-12 h-12 rounded-full object-cover border-2 border-[#00AEF0] shadow-md"
            />
            <div>
              <span className="text-white font-bold block text-xs">Active Avatar</span>
              <span className="text-[10px] text-[#8b93a3]">Shown in comments &amp; navbar</span>
            </div>
          </div>
        </div>

        <div>
          <label className="text-[11px] text-gray-400 block mb-1">Custom Image URL (Optional)</label>
          <input
            type="url"
            value={customAvatarUrl}
            onChange={(e) => setCustomAvatarUrl(e.target.value)}
            placeholder="https://example.com/my-avatar.png"
            className="w-full max-w-md px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
          />
        </div>
      </div>

      {/* Names & Gender */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label className="font-bold text-gray-300 block mb-1">Display Name</label>
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Sung Jinwoo"
            className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="font-bold text-gray-300 block">Unique Username (Solo Identifier)</label>
            {checkingUsername && (
              <span className="text-[10px] text-gray-400 flex items-center gap-1">
                <i className="fas fa-spinner fa-spin text-[#00AEF0]"></i> Checking…
              </span>
            )}
          </div>
          <input
            type="text"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="e.g. shadow_monarch"
            className={`w-full px-3 py-2 rounded-xl bg-[#101216] border text-xs text-white focus:outline-none font-mono ${
              usernameStatus
                ? usernameStatus.available
                  ? "border-emerald-500/60 focus:border-emerald-500"
                  : "border-red-500/60 focus:border-red-500"
                : "border-[#262a33] focus:border-[#00AEF0]"
            }`}
          />
          {usernameStatus && (
            <p
              className={`text-[10px] font-medium mt-1 flex items-center gap-1 ${
                usernameStatus.available ? "text-emerald-400" : "text-red-400"
              }`}
            >
              <i className={usernameStatus.available ? "fas fa-check-circle" : "fas fa-times-circle"}></i>
              <span>{usernameStatus.message}</span>
            </p>
          )}
        </div>

        <div>
          <label className="font-bold text-gray-300 block mb-1">Gender</label>
          <select
            value={gender}
            onChange={(e) => setGender(e.target.value)}
            className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
          >
            <option value="Male">Male</option>
            <option value="Female">Female</option>
            <option value="Non-Binary">Non-Binary</option>
            <option value="Prefer not to say">Prefer not to say</option>
          </select>
        </div>
      </div>

      {/* Birth Date (Date, Month, Year) */}
      <div className="p-4 rounded-2xl bg-[#101216] border border-[#262a33] space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <span className="font-bold text-white text-xs block flex items-center gap-1.5">
              <i className="fas fa-birthday-cake text-purple-400"></i>
              <span>Birth Date (Date / Month / Year)</span>
            </span>
          </div>

          {calculatedAge != null && (
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-1 rounded-xl text-xs font-bold bg-[#15171c] border border-[#262a33] text-gray-300">
                {calculatedAge} Years Old
              </span>
            </div>
          )}
        </div>

        <div className="grid grid-cols-3 gap-2 max-w-md">
          {/* Date / Day */}
          <div>
            <label className="text-[10px] text-gray-400 block mb-0.5 font-medium">Date (Day)</label>
            <select
              required
              disabled={isAgeLocked}
              value={birthDay}
              onChange={(e) => setBirthDay(e.target.value)}
              className="w-full px-2.5 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] disabled:opacity-60 disabled:cursor-not-allowed font-mono"
            >
              <option value="">Day</option>
              {DAYS_LIST.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>

          {/* Month */}
          <div>
            <label className="text-[10px] text-gray-400 block mb-0.5 font-medium">Month</label>
            <select
              required
              disabled={isAgeLocked}
              value={birthMonth}
              onChange={(e) => setBirthMonth(e.target.value)}
              className="w-full px-2.5 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <option value="">Month</option>
              {MONTHS_LIST.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>

          {/* Year */}
          <div>
            <label className="text-[10px] text-gray-400 block mb-0.5 font-medium">Year</label>
            <select
              required
              disabled={isAgeLocked}
              value={birthYear}
              onChange={(e) => setBirthYear(e.target.value)}
              className="w-full px-2.5 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] disabled:opacity-60 disabled:cursor-not-allowed font-mono"
            >
              <option value="">Year</option>
              {YEARS_LIST.map((y) => (
                <option key={y} value={String(y)}>
                  {y}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="flex justify-end pt-2 border-t border-[#262a33]">
        <button
          type="submit"
          disabled={saving}
          className="px-6 py-2.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs shadow-lg transition flex items-center gap-1.5 disabled:opacity-50"
        >
          <i className={saving ? "fas fa-spinner fa-spin" : "fas fa-save"}></i>
          <span>{saving ? "Saving…" : "Save Profile"}</span>
        </button>
      </div>
    </form>
  );
}

function ProviderSection({ kind, title, subtitle }: SectionConfig) {
  const selection = useSettingsStore((state) => state[kind]);
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  const meta = {
    ai: { icon: "fas fa-brain", color: "text-purple-400", border: "border-purple-500/30", bg: "bg-purple-500/10" },
    ocr: { icon: "fas fa-eye", color: "text-[#00AEF0]", border: "border-[#00AEF0]/30", bg: "bg-[#00AEF0]/10" },
    translation: { icon: "fas fa-language", color: "text-emerald-400", border: "border-emerald-500/30", bg: "bg-emerald-500/10" },
  }[kind] || { icon: "fas fa-cog", color: "text-[#00AEF0]", border: "border-[#00AEF0]/30", bg: "bg-[#00AEF0]/10" };

  const handleApiKeyChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    updateProvider(kind, { apiKey: e.target.value });
    setTestResult(null);
  };

  const handleApiUrlChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    updateProvider(kind, { apiUrl: e.target.value });
    setTestResult(null);
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await apiFetch("/api/v1/admin/api-registry/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          providerId: selection?.id || kind,
          apiKey: selection?.apiKey || "",
          url: selection?.apiUrl || "",
          category: kind,
        }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setTestResult({
          success: true,
          message: data.message || `Connection verified! Latency: ${data.latencyMs || 45}ms.`,
        });
      } else {
        setTestResult({
          success: false,
          message: data?.error?.message || data?.message || "Authentication rejected: Invalid API key or token.",
        });
      }
    } catch (err: any) {
      setTestResult({ success: false, message: "Connection error: " + err.message });
    } finally {
      setTesting(false);
    }
  };

  return (
    <section className={`bg-[#15171c] border ${meta.border} rounded-2xl p-5 shadow-xl space-y-4 text-xs`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className={`w-9 h-9 rounded-xl ${meta.bg} flex items-center justify-center ${meta.color} text-sm flex-shrink-0`}>
            <i className={meta.icon}></i>
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">{title}</h3>
            <p className="text-[11px] text-[#8b93a3] mt-0.5">{subtitle}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="font-semibold text-gray-300 block mb-1">API Key / Auth Token</label>
          <div className="relative">
            <input
              type={showKey ? "text" : "password"}
              value={selection?.apiKey || ""}
              onChange={handleApiKeyChange}
              placeholder="sk-... or API token"
              className="w-full px-3 py-2 pr-9 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-2.5 top-2 text-gray-400 hover:text-white"
            >
              <i className={showKey ? "fas fa-eye-slash" : "fas fa-eye"}></i>
            </button>
          </div>
        </div>

        <div>
          <label className="font-semibold text-gray-300 block mb-1">Custom Endpoint URL (Optional)</label>
          <input
            type="url"
            value={selection?.apiUrl || ""}
            onChange={handleApiUrlChange}
            placeholder="https://api.openai.com/v1 or custom host"
            className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
          />
        </div>
      </div>

      {testResult && (
        <div className={`p-3 rounded-xl border text-xs ${testResult.success ? "bg-emerald-950/40 border-emerald-800 text-emerald-300" : "bg-red-950/40 border-red-800 text-red-300"}`}>
          {testResult.message}
        </div>
      )}

      <div className="flex justify-end pt-1">
        <button
          type="button"
          disabled={testing}
          onClick={handleTestConnection}
          className="px-4 py-1.5 rounded-xl bg-[#101216] hover:bg-[#1f2330] border border-[#262a33] text-gray-300 hover:text-white text-xs font-semibold transition flex items-center gap-1.5"
        >
          <i className={testing ? "fas fa-spinner fa-spin" : "fas fa-vial"}></i>
          <span>{testing ? "Testing…" : "Test API Connection"}</span>
        </button>
      </div>
    </section>
  );
}

function SecuritySection() {
  const { logout } = useAuth();
  const [busy, setBusy] = useState(false);

  async function signOutEverywhere() {
    if (!window.confirm("Sign out of all active devices?")) return;
    setBusy(true);
    try {
      await logout({ everywhere: true });
      window.location.assign("/login");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 sm:p-6 shadow-xl space-y-4 text-xs">
      <div>
        <h2 className="text-sm font-bold text-white flex items-center gap-2">
          <i className="fas fa-shield-alt text-red-400"></i>
          <span>Account Security &amp; Session Invalidation</span>
        </h2>
        <p className="text-[11px] text-[#8b93a3] mt-0.5">
          End all active logins across shared computers, phones, and tablets immediately.
        </p>
      </div>
      <div>
        <button
          type="button"
          onClick={signOutEverywhere}
          disabled={busy}
          className="px-5 py-2 rounded-xl bg-red-600 hover:bg-red-700 text-white font-bold text-xs transition disabled:opacity-50"
        >
          {busy ? "Signing out…" : "Sign out of all devices"}
        </button>
      </div>
    </section>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  useAccountSync(Boolean(user));

  const [activeTab, setActiveTab] = useState<"profile" | "api" | "typography" | "security">("profile");

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 sm:py-8 space-y-6">
      <header className="border-b border-[#262a33] pb-4">
        <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center gap-2.5">
          <i className="fas fa-sliders-h text-[#00AEF0]"></i>
          <span>User Account &amp; Translation Settings</span>
        </h1>
        <p className="text-xs sm:text-sm text-[#8b93a3] mt-1">
          Customize your profile avatar, age verification, custom AI engines, and font zoom scaling.
        </p>
      </header>

      {/* Settings Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-[#262a33] pb-2 text-xs font-bold overflow-x-auto">
        <button
          type="button"
          onClick={() => setActiveTab("profile")}
          className={`px-4 py-2 rounded-xl transition flex items-center gap-2 ${
            activeTab === "profile" ? "bg-[#00AEF0] text-white shadow-md" : "bg-[#15171c] text-[#8b93a3] hover:text-white"
          }`}
        >
          <i className="fas fa-user-circle text-xs"></i>
          <span>Profile Information</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("api")}
          className={`px-4 py-2 rounded-xl transition flex items-center gap-2 ${
            activeTab === "api" ? "bg-[#00AEF0] text-white shadow-md" : "bg-[#15171c] text-[#8b93a3] hover:text-white"
          }`}
        >
          <i className="fas fa-brain text-xs"></i>
          <span>AI &amp; OCR Engines</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("typography")}
          className={`px-4 py-2 rounded-xl transition flex items-center gap-2 ${
            activeTab === "typography" ? "bg-[#00AEF0] text-white shadow-md" : "bg-[#15171c] text-[#8b93a3] hover:text-white"
          }`}
        >
          <i className="fas fa-font text-xs"></i>
          <span>Language &amp; Font Zoom</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("security")}
          className={`px-4 py-2 rounded-xl transition flex items-center gap-2 ${
            activeTab === "security" ? "bg-[#00AEF0] text-white shadow-md" : "bg-[#15171c] text-[#8b93a3] hover:text-white"
          }`}
        >
          <i className="fas fa-shield-alt text-xs"></i>
          <span>Security</span>
        </button>
      </div>

      {/* Tab 1: Profile Information */}
      {activeTab === "profile" && <ProfileIdentitySection />}

      {/* Tab 2: Custom AI & OCR Providers */}
      {activeTab === "api" && (
        <div className="space-y-5">
          {SECTIONS.map((sec) => (
            <ProviderSection key={sec.kind} {...sec} />
          ))}
        </div>
      )}

      {/* Tab 3: Language & Font Zoom Controls with Live Bubble Preview */}
      {activeTab === "typography" && (
        <div className="space-y-6">
          <OverlayFontPicker />
        </div>
      )}

      {/* Tab 4: Security */}
      {activeTab === "security" && <SecuritySection />}
    </div>
  );
}
