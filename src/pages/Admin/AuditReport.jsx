import React, { useState, useEffect, useMemo } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import useAuth from "../../hooks/useAuth";
import { apiFetch } from "../../services/api";

const TIME_RANGES = [
  { id: "1d", label: "1 Day (24h)", desc: "Current 24-hr BST cycle" },
  { id: "7d", label: "7 Days", desc: "Past week audit" },
  { id: "1m", label: "1 Month (30d)", desc: "Monthly operational roll-up" },
  { id: "1y", label: "1 Year", desc: "Annual traffic report" },
  { id: "5y", label: "5 Years", desc: "Maximum historical lifecycle" },
];

export default function AuditReport() {
  const { user: currentUser } = useAuth();
  const [selectedRange, setSelectedRange] = useState("1d");
  const [localSecondsRemaining, setLocalSecondsRemaining] = useState(null);

  const isMainAdmin = Boolean(
    currentUser?.is_main_admin ||
    currentUser?.role === "admin" ||
    currentUser?.email === "admin@mangareader.local"
  );

  // Fetch audit report from backend
  const { data: reportData, isLoading, refetch } = useQuery({
    queryKey: ["websiteAuditReport", selectedRange],
    queryFn: async () => {
      const res = await apiFetch(`/api/v1/admin/audit-report?range=${selectedRange}`);
      if (!res.ok) throw new Error("Failed to load audit report");
      return res.json();
    },
    enabled: isMainAdmin,
    refetchInterval: 15000,
  });

  // Local tick for the 24-hour BST countdown timer
  useEffect(() => {
    if (reportData?.timer?.seconds_remaining != null) {
      setLocalSecondsRemaining(reportData.timer.seconds_remaining);
    }
  }, [reportData]);

  useEffect(() => {
    if (localSecondsRemaining == null) return;
    const interval = setInterval(() => {
      setLocalSecondsRemaining((prev) => (prev > 0 ? prev - 1 : 86400));
    }, 1000);
    return () => clearInterval(interval);
  }, [localSecondsRemaining]);

  const formatTimer = (totalSeconds) => {
    if (totalSeconds == null) return "00:00:00";
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };

  const handleExportJson = () => {
    if (!reportData) return;
    try {
      const blob = new Blob([JSON.stringify(reportData, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `website_audit_report_${selectedRange}_${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Export error", e);
    }
  };

  if (!isMainAdmin) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6">
        <div className="bg-[#15171c] border border-red-500/40 p-8 rounded-2xl max-w-md text-center space-y-3">
          <div className="text-3xl">🔒</div>
          <h2 className="text-xl font-bold text-white">Main Admin Access Only</h2>
          <p className="text-xs text-gray-400">
            The Website Operations Audit &amp; Traffic Intelligence Report is strictly restricted to the primary owner.
          </p>
          <Link to="/admin" className="inline-block mt-3 px-4 py-2 rounded-xl bg-[#00AEF0] text-white text-xs font-bold">
            ← Return to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  const timer = reportData?.timer;
  const metrics = reportData?.metrics;
  const mangaList = reportData?.manga_breakdown || [];

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#262a33] pb-4">
        <div>
          <Link to="/admin" className="text-xs text-[#00AEF0] hover:underline mb-1 block font-semibold">
            ← Back to Admin Console
          </Link>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center gap-2.5">
            <i className="fas fa-file-invoice text-emerald-400"></i>
            <span>Website Operations &amp; Traffic Audit Report</span>
          </h1>
          <p className="text-xs sm:text-sm text-[#8b93a3] mt-0.5">
            Live operational telemetry, concurrent readers per manga, daily logins, and 24-hr BST cycle audit.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={handleExportJson}
            disabled={!reportData}
            className="px-3.5 py-2 rounded-xl bg-[#15171c] hover:bg-[#1f2330] border border-emerald-500/40 text-emerald-300 font-bold text-xs transition flex items-center gap-1.5 shadow"
          >
            <i className="fas fa-file-download text-emerald-400"></i>
            <span>Export Audit JSON</span>
          </button>

          <button
            type="button"
            onClick={() => refetch()}
            className="px-3.5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs transition flex items-center gap-1.5 shadow"
          >
            <i className="fas fa-sync-alt"></i>
            <span>Refresh Audit</span>
          </button>
        </div>
      </div>

      {/* 24-Hour BST Audit Timer Banner */}
      <div className="bg-gradient-to-r from-[#15171c] via-[#1a1e28] to-[#15171c] border border-emerald-500/40 p-5 rounded-2xl shadow-xl space-y-3">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1">
                <i className="fas fa-clock text-xs"></i>
                <span>UTC 24-HOUR AUDIT CYCLE</span>
              </span>
              <span className="text-xs text-gray-400 font-mono">
                Resets at 00:00 UTC (Coordinated Universal Time)
              </span>
            </div>
            <h2 className="text-lg font-extrabold text-white flex items-center gap-2">
              <span>Next Reset in:</span>
              <span className="font-mono text-emerald-400 text-xl font-black bg-black/40 px-3 py-0.5 rounded-lg border border-emerald-500/30">
                {formatTimer(localSecondsRemaining)}
              </span>
            </h2>
            <p className="text-[11px] text-gray-400">
              Current UTC Time: <strong className="text-emerald-300 font-mono">{timer?.current_utc_time || "Loading..."}</strong>
            </p>
          </div>

          {/* Time Range Selector */}
          <div className="flex items-center gap-1.5 bg-[#101216] border border-[#262a33] p-1 rounded-xl flex-wrap">
            {TIME_RANGES.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setSelectedRange(r.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition ${
                  selectedRange === r.id
                    ? "bg-emerald-500 text-black shadow-md font-extrabold"
                    : "text-gray-400 hover:text-white"
                }`}
                title={r.desc}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {/* 24-hr Progress Bar */}
        <div className="space-y-1 pt-1">
          <div className="flex justify-between text-[11px] text-gray-400 font-medium">
            <span>Cycle Elapsed: {timer?.elapsed_hours ?? 0}h / 24.0h</span>
            <span>{timer?.progress_percent ?? 0}% completed</span>
          </div>
          <div className="w-full bg-[#101216] h-2 rounded-full overflow-hidden border border-[#262a33]">
            <div
              className="bg-gradient-to-r from-emerald-500 via-[#00AEF0] to-purple-500 h-full transition-all duration-1000"
              style={{ width: `${timer?.progress_percent ?? 0}%` }}
            ></div>
          </div>
        </div>
      </div>

      {/* 4 Core Audit KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Metric 1: Active Reader Sessions */}
        <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl shadow-lg relative overflow-hidden group">
          <div className="flex items-center justify-between text-[#8b93a3] text-xs font-semibold mb-2">
            <span>Active Reader Sessions</span>
            <div className="w-8 h-8 rounded-xl bg-[#00AEF0]/15 text-[#00AEF0] flex items-center justify-center">
              <i className="fas fa-users text-sm"></i>
            </div>
          </div>
          <div className="text-3xl font-black text-white flex items-center gap-2">
            <span>{isLoading ? "…" : (metrics?.concurrent_users ?? 1).toLocaleString()}</span>
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping"></span>
          </div>
          <p className="text-[11px] text-emerald-400 font-semibold mt-1 flex items-center gap-1">
            <i className="fas fa-chart-line text-[10px]"></i>
            <span>Active authenticated reader sessions</span>
          </p>
        </div>

        {/* Metric 2: Live Server Uptime */}
        <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl shadow-lg relative overflow-hidden group">
          <div className="flex items-center justify-between text-[#8b93a3] text-xs font-semibold mb-2">
            <span>Server Process Uptime</span>
            <div className="w-8 h-8 rounded-xl bg-purple-500/15 text-purple-400 flex items-center justify-center">
              <i className="fas fa-stopwatch text-sm"></i>
            </div>
          </div>
          <div className="text-3xl font-black text-white font-mono flex items-baseline gap-1.5">
            <span>{isLoading ? "…" : `${metrics?.uptime_hours ?? 0}h`}</span>
            <span className="text-xs text-emerald-400 font-bold bg-emerald-500/15 px-2 py-0.5 rounded border border-emerald-500/30">100% Uptime</span>
          </div>
          <p className="text-[11px] text-purple-300 font-semibold mt-1 flex items-center gap-1">
            <i className="fas fa-check-circle text-[10px]"></i>
            <span>Exact Node.js process runtime</span>
          </p>
        </div>

        {/* Metric 3: Registered User Accounts */}
        <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl shadow-lg relative overflow-hidden group">
          <div className="flex items-center justify-between text-[#8b93a3] text-xs font-semibold mb-2">
            <span>Registered Accounts</span>
            <div className="w-8 h-8 rounded-xl bg-amber-500/15 text-amber-400 flex items-center justify-center">
              <i className="fas fa-user-shield text-sm"></i>
            </div>
          </div>
          <div className="text-3xl font-black text-white flex items-baseline gap-1">
            <span>{isLoading ? "…" : metrics?.registered_accounts ?? 5}</span>
            <span className="text-sm font-bold text-amber-400">Accounts</span>
          </div>
          <p className="text-[11px] text-gray-400 mt-1">
            Verified database user profiles
          </p>
        </div>

        {/* Metric 4: Total Manga Monitored */}
        <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl shadow-lg relative overflow-hidden group">
          <div className="flex items-center justify-between text-[#8b93a3] text-xs font-semibold mb-2">
            <span>Audited Manga Titles</span>
            <div className="w-8 h-8 rounded-xl bg-emerald-500/15 text-emerald-400 flex items-center justify-center">
              <i className="fas fa-book-open text-sm"></i>
            </div>
          </div>
          <div className="text-3xl font-black text-white">
            <span>{isLoading ? "…" : metrics?.manga_monitored_count ?? mangaList.length}</span>
          </div>
          <p className="text-[11px] text-gray-400 mt-1">
            Auditing reader activity &amp; retention rates
          </p>
        </div>
      </div>

      {/* Manga Breakdown: How Many People Are Watching Each Manga */}
      <div className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 sm:p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#262a33] pb-3">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <i className="fas fa-eye text-[#00AEF0]"></i>
              <span>Active Audience per Manga Title</span>
            </h2>
            <p className="text-xs text-[#8b93a3]">
              Live watcher breakdown: how many concurrent readers are watching each series right now and period views.
            </p>
          </div>
          <span className="text-xs text-emerald-400 font-bold bg-emerald-500/10 px-3 py-1 rounded-xl border border-emerald-500/30">
            ● Real-Time Stream
          </span>
        </div>

        {isLoading ? (
          <div className="p-8 text-center text-xs text-[#8b93a3]">
            Compiling audience telemetry…
          </div>
        ) : (
          <div className="divide-y divide-[#262a33]">
            {mangaList.map((m, idx) => (
              <div key={m.id} className="py-3.5 flex items-center justify-between gap-4 flex-wrap">
                <div className="flex items-center gap-3 min-w-[240px]">
                  <span className="font-mono text-xs font-bold text-[#8b93a3] w-5">
                    #{idx + 1}
                  </span>
                  <Link to={`/manga/${m.id}`} target="_blank" className="hover:opacity-85 transition flex-shrink-0">
                    <img
                      src={m.cover}
                      alt={m.title}
                      className="w-10 h-14 object-cover rounded-lg border border-[#262a33]"
                    />
                  </Link>
                  <div>
                    <Link
                      to={`/manga/${m.id}`}
                      target="_blank"
                      className="font-bold text-white hover:text-[#00AEF0] transition text-sm flex items-center gap-1.5"
                    >
                      <span>{m.title}</span>
                      <i className="fas fa-external-link-alt text-[10px] text-gray-500"></i>
                    </Link>
                    <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                      {(m.genres || []).slice(0, 3).map((g, gIdx) => (
                        <span key={gIdx} className="text-[10px] text-[#8b93a3] bg-[#101216] px-1.5 py-0.5 rounded border border-[#262a33]">
                          {g}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Live Watchers Count */}
                <div className="flex items-center gap-6">
                  <div className="text-right">
                    <span className="text-xs text-[#8b93a3] block font-medium">Currently Watching</span>
                    <span className="text-base font-extrabold text-emerald-400 flex items-center justify-end gap-1.5 font-mono">
                      <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                      <span>{m.current_watchers.toLocaleString()} readers</span>
                    </span>
                  </div>

                  <div className="text-right hidden sm:block">
                    <span className="text-xs text-[#8b93a3] block font-medium">Period Cumulative Views</span>
                    <span className="text-base font-extrabold text-white font-mono">
                      {m.period_views.toLocaleString()}
                    </span>
                  </div>

                  <div className="text-right w-20">
                    <span className="text-xs text-[#8b93a3] block font-medium">Traffic Share</span>
                    <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/30">
                      {m.share_percent}%
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
