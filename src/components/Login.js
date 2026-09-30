import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import useAuth from "../hooks/useAuth";

export default function Login() {
  const [authMode, setAuthMode] = useState("magic"); // "magic" | "password"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const { login, refetchUser } = useAuth();
  const navigate = useNavigate();

  const handleMagicLink = async (e) => {
    e.preventDefault();
    if (!email || !email.includes("@")) {
      setError("Please enter a valid email address.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await api.auth.requestMagicLink(email.trim());
      setSent(true);
    } catch (err) {
      setError(err.message || "Failed to request sign-in link.");
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordLogin = async (e) => {
    e.preventDefault();
    if (!email || !email.includes("@")) {
      setError("Please enter a valid email address.");
      return;
    }
    if (!password) {
      setError("Please enter your account password.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/v1/auth/login-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error?.message || "Invalid credentials.");
      }
      if (refetchUser) await refetchUser();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.message || "Sign-in failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleMicrosoftLogin = () => {
    window.location.href = "/api/v1/auth/microsoft";
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-[#15171c] border border-[#262a33] p-6 sm:p-8 rounded-2xl shadow-2xl space-y-5">
        <div className="text-center space-y-1">
          <div className="text-3xl">🦎</div>
          <h1 className="text-2xl font-extrabold text-white">Welcome to Manga World</h1>
          <p className="text-xs text-[#8b93a3]">
            Sign in with your Email, Google, or Microsoft account to enter.
          </p>
        </div>

        {error && (
          <div className="p-3 bg-red-500/15 border border-red-500/30 rounded-xl text-xs text-red-400 font-medium">
            {error}
          </div>
        )}

        <div className="space-y-4">
          {/* OAuth Social Buttons (Google + Microsoft) */}
          <div className="space-y-2.5">
            <button
              type="button"
              onClick={() => login("google")}
              className="w-full py-2.5 px-4 rounded-xl bg-[#101216] hover:bg-[#1f2330] border border-[#262a33] hover:border-[#00AEF0] text-white font-semibold text-xs transition flex items-center justify-center gap-2.5 shadow-sm"
            >
              <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24">
                <path
                  fill="#EA4335"
                  d="M12 5c1.6 0 3 .6 4.1 1.7l3.1-3.1C17.3 1.8 14.8 1 12 1 7.5 1 3.7 3.6 1.9 7.3l3.7 2.9C6.5 7.4 9 5 12 5z"
                />
                <path
                  fill="#4285F4"
                  d="M23.5 12.3c0-.8-.1-1.7-.2-2.3H12v4.6h6.5c-.3 1.5-1.1 2.8-2.4 3.7l3.7 2.9c2.2-2 3.7-5 3.7-8.9z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.6 14.8c-.2-.7-.4-1.5-.4-2.3 0-.8.2-1.6.4-2.3L1.9 7.3C.7 9.7 0 12.3 0 15.1c0 2.8.7 5.4 1.9 7.8l3.7-2.9z"
                />
                <path
                  fill="#34A853"
                  d="M12 23.5c3.2 0 6-1.1 8-3l-3.7-2.9c-1.1.7-2.5 1.2-4.3 1.2-3 0-5.5-2.4-6.4-5.2L1.9 16.5C3.7 20.2 7.5 23.5 12 23.5z"
                />
              </svg>
              <span>Continue with Google</span>
            </button>

            <button
              type="button"
              onClick={handleMicrosoftLogin}
              className="w-full py-2.5 px-4 rounded-xl bg-[#101216] hover:bg-[#1f2330] border border-[#262a33] hover:border-[#00AEF0] text-white font-semibold text-xs transition flex items-center justify-center gap-2.5 shadow-sm"
            >
              <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 21 21">
                <rect x="1" y="1" width="9" height="9" fill="#F25022" />
                <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
                <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
                <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
              </svg>
              <span>Continue with Microsoft</span>
            </button>
          </div>

          <div className="relative flex py-1 items-center">
            <div className="flex-grow border-t border-[#262a33]"></div>
            <span className="flex-shrink mx-3 text-[10px] uppercase tracking-wider text-[#8b93a3] font-bold">
              Or with Email
            </span>
            <div className="flex-grow border-t border-[#262a33]"></div>
          </div>

          {/* Mode Switch Tabs */}
          <div className="flex rounded-xl bg-[#101216] p-1 border border-[#262a33] text-xs font-semibold">
            <button
              type="button"
              onClick={() => {
                setAuthMode("magic");
                setError("");
              }}
              className={`flex-1 py-1.5 rounded-lg transition text-center ${
                authMode === "magic"
                  ? "bg-[#00AEF0] text-white shadow"
                  : "text-gray-400 hover:text-white"
              }`}
            >
              <i className="fas fa-magic mr-1.5 text-[10px]"></i>
              <span>1-Click Magic Link</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setAuthMode("password");
                setError("");
              }}
              className={`flex-1 py-1.5 rounded-lg transition text-center ${
                authMode === "password"
                  ? "bg-[#00AEF0] text-white shadow"
                  : "text-gray-400 hover:text-white"
              }`}
            >
              <i className="fas fa-key mr-1.5 text-[10px]"></i>
              <span>Password</span>
            </button>
          </div>

          {authMode === "magic" ? (
            sent ? (
              <div className="p-4 bg-emerald-500/15 border border-emerald-500/30 rounded-xl text-center space-y-2">
                <i className="fas fa-paper-plane text-emerald-400 text-xl"></i>
                <h3 className="text-sm font-bold text-white">Sign-in Link Sent!</h3>
                <p className="text-xs text-gray-300 leading-relaxed">
                  We sent a verification link to <strong className="text-white">{email}</strong>. Open the link to enter the website.
                </p>
                <button
                  type="button"
                  onClick={() => setSent(false)}
                  className="text-xs text-[#00AEF0] hover:underline font-semibold mt-1"
                >
                  Use a different email address
                </button>
              </div>
            ) : (
              <form onSubmit={handleMagicLink} className="space-y-3.5">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-gray-300 block">Email Address</label>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full px-4 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0]"
                  />
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-sm shadow-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {loading ? <span>Sending link…</span> : <span>Send Sign-In Link</span>}
                </button>
              </form>
            )
          ) : (
            <form onSubmit={handlePasswordLogin} className="space-y-3.5">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-300 block">Email Address</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full px-4 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0]"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-300 block">Password</label>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-4 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0]"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-sm shadow-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? <span>Signing in…</span> : <span>Sign In with Password</span>}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
