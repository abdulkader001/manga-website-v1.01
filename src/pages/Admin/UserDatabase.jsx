import React, { useState, useEffect } from "react";
import { Link } from "react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { apiFetch } from "../../services/api";
import useAuth from "../../hooks/useAuth";
import { maskEmail } from "../../utils/maskEmail";

export default function UserDatabase() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState(null);
  const [showRawEmails, setShowRawEmails] = useState(false);

  // Customizable account re-verification interval (in days)
  const [reverifyDays, setReverifyDays] = useState(15);
  const [savingInterval, setSavingInterval] = useState(false);

  const isMainAdmin = Boolean(
    currentUser?.is_main_admin ||
    currentUser?.role === "admin" ||
    currentUser?.email === "admin@mangareader.local"
  );

  // Fetch admin settings for reverifyDays
  useEffect(() => {
    apiFetch("/api/v1/admin/settings")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.settings?.session_timeout_days) {
          setReverifyDays(d.settings.session_timeout_days);
        }
      })
      .catch(() => {});
  }, []);

  const handleSaveInterval = async (e) => {
    e.preventDefault();
    setSavingInterval(true);
    try {
      await apiFetch("/api/v1/admin/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_timeout_days: Number(reverifyDays) }),
      });
      setNotice({
        type: "success",
        message: `✅ Account re-verification interval updated to ${reverifyDays} days! Users must re-login after this period.`,
      });
    } catch {
      setNotice({ type: "error", message: "Failed to update interval." });
    } finally {
      setSavingInterval(false);
    }
  };

  const { data: usersData, isLoading } = useQuery({
    queryKey: ["usersDirectory", search],
    queryFn: () => api.admin.users(),
    enabled: isMainAdmin,
  });

  const users = Array.isArray(usersData) ? usersData : (Array.isArray(usersData?.items) ? usersData.items : []);
  const filteredUsers = users.filter((u) =>
    (u.name || "").toLowerCase().includes(search.toLowerCase()) ||
    (u.email || "").toLowerCase().includes(search.toLowerCase()) ||
    (u.username || "").toLowerCase().includes(search.toLowerCase())
  );

  const handlePromote = async (id, name) => {
    try {
      await api.admin.promoteSecondary({ user_id: id });
      await queryClient.invalidateQueries({ queryKey: ["usersDirectory"] });
      await queryClient.invalidateQueries({ queryKey: ["adminUsersDirectory"] });
      setNotice({ type: "success", message: `✅ ${name || "User"} promoted to Sub-Admin.` });
    } catch (err) {
      setNotice({ type: "error", message: "Promotion failed: " + err.message });
    }
  };

  const handleDemote = async (id, name) => {
    try {
      await api.admin.demoteSecondary({ user_id: id });
      await queryClient.invalidateQueries({ queryKey: ["usersDirectory"] });
      await queryClient.invalidateQueries({ queryKey: ["adminUsersDirectory"] });
      setNotice({ type: "success", message: `✅ ${name || "User"} demoted to standard reader.` });
    } catch (err) {
      setNotice({ type: "error", message: "Demotion failed: " + err.message });
    }
  };

  if (!isMainAdmin) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6">
        <div className="bg-[#15171c] border border-red-500/40 p-8 rounded-2xl max-w-md text-center space-y-3">
          <div className="text-3xl">🔒</div>
          <h2 className="text-xl font-bold text-white">Main Admin Access Only</h2>
          <p className="text-xs text-gray-400">
            Only the primary owner (<strong className="text-white">admin@mangareader.local</strong>) can access the user database and credentials.
          </p>
          <Link to="/admin" className="inline-block mt-3 px-4 py-2 rounded-xl bg-[#00AEF0] text-white text-xs font-bold">
            ← Return to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-6">
      <div className="border-b border-[#262a33] pb-4 flex items-center justify-between flex-wrap gap-4">
        <div>
          <Link to="/admin" className="text-xs text-[#00AEF0] hover:underline mb-1 block">← Back to Admin</Link>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <span>👥 User Database &amp; Directory</span>
            <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/40">
              Main Admin Restricted
            </span>
          </h1>
          <p className="text-xs text-[#8b93a3] mt-1">
            Protected ledger of registered reader accounts, arbitrary email verification status, and re-login expiration intervals.
          </p>
        </div>
      </div>

      {notice && (
        <div className={`p-3.5 rounded-xl border text-xs flex items-center justify-between ${
          notice.type === "error" ? "bg-red-950/40 border-red-500/40 text-red-300" : "bg-emerald-950/40 border-emerald-500/40 text-emerald-300"
        }`}>
          <span>{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-gray-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Account Verification & Re-Login Interval Setting */}
      <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl shadow-xl space-y-3">
        <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-purple-500/20 border border-purple-500/40 flex items-center justify-center text-purple-300 text-sm">
              <i className="fas fa-hourglass-half"></i>
            </div>
            <div>
              <h2 className="text-sm font-bold text-white">Account Verification &amp; Session Re-Login Cycle</h2>
              <p className="text-[11px] text-[#8b93a3]">
                Configure how many days before a user session/verification automatically expires, requiring the reader to re-login.
              </p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSaveInterval} className="flex items-center gap-3 flex-wrap text-xs">
          <label className="font-semibold text-gray-300">Re-Verification Interval:</label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1}
              max={180}
              value={reverifyDays}
              onChange={(e) => setReverifyDays(Number(e.target.value))}
              className="w-24 px-3 py-1.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white font-mono focus:outline-none focus:border-[#00AEF0]"
            />
            <span className="text-gray-400 font-semibold">Days</span>
          </div>

          <button
            type="submit"
            disabled={savingInterval}
            className="px-4 py-1.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs shadow-md transition disabled:opacity-50"
          >
            {savingInterval ? "Saving..." : "Save Interval Setting"}
          </button>

          <span className="text-[11px] text-gray-400 ml-auto">
            Default: <strong>15 days</strong>. Any email (Gmail, Yahoo, custom mail) is supported.
          </span>
        </form>
      </div>

      <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search users by name, username, or arbitrary email domain…"
            className="w-full max-w-sm px-4 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0]"
          />
          <div className="flex items-center gap-2.5 flex-wrap">
            <button
              type="button"
              onClick={() => setShowRawEmails(!showRawEmails)}
              className="px-3 py-1.5 rounded-xl border border-purple-500/40 bg-purple-500/15 text-purple-300 hover:bg-purple-500/25 font-bold text-xs flex items-center gap-1.5 transition shadow"
              title="Toggle email privacy mask"
            >
              <i className={showRawEmails ? "fas fa-eye-slash" : "fas fa-shield-alt"}></i>
              <span>{showRawEmails ? "Mask Emails (Privacy Guard Active)" : "Unmask Emails (Main Admin Verify)"}</span>
            </button>
            <span className="text-xs text-[#8b93a3] font-semibold">{filteredUsers.length} Users Listed</span>
          </div>
        </div>

        {isLoading ? (
          <div className="p-8 text-center text-xs text-[#8b93a3]">Loading user database…</div>
        ) : (
          <div className="divide-y divide-[#262a33]">
            {filteredUsers.map((u, idx) => (
              <div key={u.id ? `user-${u.id}-${u.email || idx}` : u.email || `user-${idx}`} className="py-3 flex items-center justify-between gap-3 text-xs flex-wrap">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-[#00AEF0] to-purple-600 flex items-center justify-center font-bold text-xs text-white">
                    {(u.name || u.username || u.email || "U")[0].toUpperCase()}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white">{u.name || u.username}</span>
                      {u.username && (
                        <span className="text-[10px] text-[#00AEF0] font-mono">@{u.username}</span>
                      )}
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                        Verified
                      </span>
                    </div>
                    <span className="text-[11px] text-[#8b93a3] font-mono">
                      {showRawEmails ? u.email : maskEmail(u.email)}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <span className="text-[11px] text-gray-400 hidden sm:inline">
                    Expires in: <strong className="text-gray-200">{reverifyDays}d cycle</strong>
                  </span>

                  <span className={`px-2.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                    u.role === "admin" || u.is_main_admin
                      ? "bg-purple-500/20 text-purple-300 border border-purple-500/40"
                      : u.role === "secondary_admin" || u.is_secondary_admin
                      ? "bg-blue-500/20 text-blue-300 border border-blue-500/40"
                      : "bg-gray-800 text-gray-400"
                  }`}>
                    {u.role || "reader"}
                  </span>

                  {!(u.role === "admin" || u.is_main_admin) && (
                    u.role === "secondary_admin" ? (
                      <button
                        type="button"
                        onClick={() => handleDemote(u.id, u.name)}
                        className="px-2.5 py-1 rounded-lg bg-[#101216] border border-[#262a33] text-amber-400 hover:bg-[#15171c] transition"
                      >
                        Demote to User
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handlePromote(u.id, u.name)}
                        className="px-2.5 py-1 rounded-lg bg-[#00AEF0]/15 border border-[#00AEF0]/30 text-[#00AEF0] hover:bg-[#0F5065] text-white transition"
                      >
                        Make Sub-Admin
                      </button>
                    )
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
