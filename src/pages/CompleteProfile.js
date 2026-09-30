import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import useAuth from "../hooks/useAuth";
import { apiFetch } from "../services/api";

const MONTHS = [
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

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 105 }, (_, i) => CURRENT_YEAR - i);
const DAYS = Array.from({ length: 31 }, (_, i) => String(i + 1).padStart(2, "0"));

export default function CompleteProfile() {
  const { user, refetchUser, isLoading } = useAuth();
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [usernameStatus, setUsernameStatus] = useState(null); // { available: boolean, message: string } | null
  const [checkingUsername, setCheckingUsername] = useState(false);

  // Date, Month, Year structured inputs
  const [birthDay, setBirthDay] = useState("");
  const [birthMonth, setBirthMonth] = useState("");
  const [birthYear, setBirthYear] = useState("");

  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isLoading && !user) {
      navigate("/login", { replace: true });
    } else if (user) {
      if (user.name && user.name !== user.email?.split("@")[0]) {
        setName(user.name);
      }
      if (user.username && user.username !== user.email?.split("@")[0]) {
        setUsername(user.username);
      }
      if (user.birth_date) {
        const parts = user.birth_date.split("-");
        if (parts.length === 3) {
          setBirthYear(parts[0]);
          setBirthMonth(parts[1]);
          setBirthDay(parts[2]);
        }
      }
      if (user.profile_completed && user.birth_date && user.name && user.username) {
        navigate("/", { replace: true });
      }
    }
  }, [user, isLoading, navigate]);

  // Live Unique Username Check (solo identifier check)
  useEffect(() => {
    const clean = username.trim().toLowerCase().replace(/[^a-z0-9_]/g, "");
    if (!clean || clean.length < 3) {
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
  }, [username]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Please enter your display name.");
      return;
    }
    if (!username.trim()) {
      setError("Please enter your unique username.");
      return;
    }
    if (usernameStatus && !usernameStatus.available) {
      setError("This username is already in use. Unique names must be solo across the entire website.");
      return;
    }
    if (!birthDay || !birthMonth || !birthYear) {
      setError("Please select your complete date, month, and year of birth.");
      return;
    }

    const formattedBirthDate = `${birthYear}-${birthMonth}-${birthDay}`;

    setLoading(true);
    setError("");

    try {
      const res = await apiFetch("/api/v1/auth/complete-profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          username: username.trim(),
          birth_date: formattedBirthDate,
          password: password.trim() || undefined,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error?.message || "Failed to complete profile.");
      }

      if (refetchUser) {
        await refetchUser();
      }
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.message || "An error occurred.");
    } finally {
      setLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-[70vh] flex items-center justify-center text-[#8b93a3] text-sm">
        Loading account details…
      </div>
    );
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-[#15171c] border border-[#262a33] p-6 sm:p-8 rounded-2xl shadow-2xl space-y-5">
        <div className="text-center space-y-1">
          <div className="text-3xl">🎉</div>
          <h1 className="text-2xl font-extrabold text-white">Complete Your Profile</h1>
          <p className="text-xs text-[#8b93a3]">
            Your email is verified. Please set your display name, solo unique username, and birth date.
          </p>
        </div>

        {/* Verified Email Badge */}
        {user?.email && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-emerald-950/30 border border-emerald-500/40 text-emerald-300 text-xs">
            <i className="fas fa-check-circle text-emerald-400"></i>
            <span>Verified Email: <strong className="text-white">{user.email}</strong></span>
          </div>
        )}

        {error && (
          <div className="p-3 bg-red-500/15 border border-red-500/30 rounded-xl text-xs text-red-400 font-medium">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* 1. Display Name */}
          <div className="space-y-1">
            <label className="text-xs font-semibold text-gray-300 block">
              Display Name <span className="text-[#00AEF0]">*</span>
            </label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Sung Jinwoo"
              className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0]"
            />
          </div>

          {/* 2. Unique Username (Solo Identifier) */}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-gray-300 block">
                Unique Username (Solo Identifier) <span className="text-[#00AEF0]">*</span>
              </label>
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
              className={`w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border text-sm text-white placeholder:text-gray-500 focus:outline-none font-mono ${
                usernameStatus
                  ? usernameStatus.available
                    ? "border-emerald-500/60 focus:border-emerald-500"
                    : "border-red-500/60 focus:border-red-500"
                  : "border-[#262a33] focus:border-[#00AEF0]"
              }`}
            />
            {usernameStatus && (
              <p
                className={`text-[11px] font-medium mt-1 flex items-center gap-1.5 ${
                  usernameStatus.available ? "text-emerald-400" : "text-red-400"
                }`}
              >
                <i className={usernameStatus.available ? "fas fa-check-circle" : "fas fa-times-circle"}></i>
                <span>{usernameStatus.message}</span>
              </p>
            )}
          </div>

          {/* 3. Birthday: Date (Day), Month, Year */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-gray-300 block">
              Birth Date (Date / Month / Year) <span className="text-[#00AEF0]">*</span>
            </label>
            <div className="grid grid-cols-3 gap-2">
              {/* Date / Day */}
              <div>
                <label className="text-[10px] text-gray-400 block mb-0.5 font-medium">Date (Day)</label>
                <select
                  required
                  value={birthDay}
                  onChange={(e) => setBirthDay(e.target.value)}
                  className="w-full px-2.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                >
                  <option value="">Day</option>
                  {DAYS.map((d) => (
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
                  value={birthMonth}
                  onChange={(e) => setBirthMonth(e.target.value)}
                  className="w-full px-2.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                >
                  <option value="">Month</option>
                  {MONTHS.map((m) => (
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
                  value={birthYear}
                  onChange={(e) => setBirthYear(e.target.value)}
                  className="w-full px-2.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                >
                  <option value="">Year</option>
                  {YEARS.map((y) => (
                    <option key={y} value={String(y)}>
                      {y}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* 4. Optional Password */}
          <div className="space-y-1">
            <label className="text-xs font-semibold text-gray-300 block">
              Account Password <span className="text-gray-500 font-normal">(Optional for direct password login)</span>
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Create a password or leave blank for magic-link only"
              className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0]"
            />
          </div>

          <button
            type="submit"
            disabled={loading || (usernameStatus && !usernameStatus.available)}
            className="w-full py-2.5 mt-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-sm shadow-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {loading ? <span>Saving profile…</span> : <span>Enter Manga World</span>}
          </button>
        </form>
      </div>
    </div>
  );
}
