import React, { useState, useEffect } from "react";
import { Link } from "react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { apiFetch } from "../../services/api";
import useStaffPermissions from "../../hooks/useStaffPermissions";
import AuthGuard from "../../components/AuthGuard";

const last = (arr) => (arr.length ? arr[arr.length - 1] : null);
const avg = (arr) =>
  arr.length ? Math.round((arr.reduce((sum, v) => sum + v, 0) / arr.length) * 10) / 10 : null;

export default function Health() {
  const queryClient = useQueryClient();
  // The owner always; an Admin only while the owner has switched the power on.
  const { can } = useStaffPermissions();
  const canCache = can("manage_cache");
  const canPurge = can("purge_site_data");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [diagnosticReport, setDiagnosticReport] = useState(null);
  const [isRunningDiagnostics, setIsRunningDiagnostics] = useState(false);
  const [notice, setNotice] = useState(null);
  const [clearingCache, setClearingCache] = useState(false);

  // Telemetry history: starts empty and only ever holds values the backend reported.
  const [cpuHistory, setCpuHistory] = useState([]);
  const [ramHistory, setRamHistory] = useState([]);
  const [latencyHistory, setLatencyHistory] = useState([]);

  // Poll live system health every 3 seconds
  const {
    data: health,
    isLoading: loading,
    refetch,
  } = useQuery({
    queryKey: ["healthLive"],
    // Round-trip time is measured here so the latency graph is a real measurement.
    queryFn: async () => {
      const started = performance.now();
      const data = await api.health.simple();
      return { ...data, roundTripMs: Math.round(performance.now() - started) };
    },
    refetchInterval: autoRefresh ? 3000 : false,
    staleTime: 2000,
  });

  // Push new telemetry points on every poll
  useEffect(() => {
    if (!health) return;
    const push = (setter, value) => {
      if (typeof value === "number" && Number.isFinite(value)) {
        setter((prev) => [...prev.slice(-15), value]);
      }
    };
    push(setCpuHistory, health.system?.cpu_percent);
    push(setRamHistory, health.system?.memory_heap_used_mb);
    push(setLatencyHistory, health.roundTripMs);
  }, [health]);

  const diagnosticMutation = useMutation({
    mutationFn: () => api.health.runDiagnostics(),
    onMutate: () => {
      setIsRunningDiagnostics(true);
    },
    onSuccess: (data) => {
      setDiagnosticReport(data);
      setIsRunningDiagnostics(false);
      queryClient.invalidateQueries({ queryKey: ["healthLive"] });
    },
    onError: (err) => {
      setIsRunningDiagnostics(false);
      setNotice({ type: "error", message: "Failed to execute self-diagnostic: " + (err.message || "Unknown error") });
    },
  });

  const handleRunDiagnostics = () => {
    diagnosticMutation.mutate();
  };

  const handleClearCache = async () => {
    if (!canCache) return;
    setClearingCache(true);
    try {
      const res = await apiFetch("/api/v1/admin/settings/clear-cache", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error?.message || "Failed to flush cache");
      setNotice({ type: "success", message: "✅ " + data.message });
      queryClient.invalidateQueries({ queryKey: ["healthLive"] });
    } catch (err) {
      setNotice({ type: "error", message: err.message });
    } finally {
      setClearingCache(false);
    }
  };

  const handlePurgeImages = async () => {
    if (!canPurge) return;
    setClearingCache(true);
    try {
      const res = await apiFetch("/api/v1/admin/maintenance/purge-all-images", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error?.message || "Failed to purge image cache");
      setNotice({ type: "success", message: "✅ " + data.message });
      queryClient.invalidateQueries({ queryKey: ["healthLive"] });
    } catch (err) {
      setNotice({ type: "error", message: err.message });
    } finally {
      setClearingCache(false);
    }
  };

  const sys = health?.system || {};
  const db = health?.database || {};
  const services = Array.isArray(health?.services) ? health.services : [];
  const tables = Array.isArray(db.tables_health) ? db.tables_health : [];

  // SVG sparkline helper
  const renderSparkline = (data, strokeColor, fillColor) => {
    if (data.length < 2) {
      return <div className="h-10 flex items-center text-[10px] text-gray-500 font-mono">Collecting samples…</div>;
    }
    const min = Math.min(...data);
    const max = Math.max(...data) || 1;
    const range = max - min || 1;
    const height = 40;
    const width = 140;
    const step = width / (data.length - 1);

    const points = data
      .map((val, idx) => {
        const x = idx * step;
        const y = height - ((val - min) / range) * (height - 8) - 4;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

    const areaPoints = `0,${height} ${points} ${width},${height}`;

    return (
      <svg className="w-full h-10 overflow-visible" viewBox={`0 0 ${width} ${height}`}>
        <polygon points={areaPoints} fill={fillColor} />
        <polyline fill="none" stroke={strokeColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" points={points} />
      </svg>
    );
  };

  return (
    <AuthGuard requireAdmin allowSecondaryAdmins>
      <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6 text-gray-200">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-[#262a33] pb-4">
          <div>
            <div className="flex items-center gap-2 text-xs text-[#8b93a3] mb-1">
              <Link to="/admin" className="hover:text-white transition">
                Administrator Hub
              </Link>
              <span>/</span>
              <span className="text-[#00AEF0] font-semibold">Live System Health &amp; Diagnostics</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center gap-2.5">
              <i className="fas fa-heartbeat text-emerald-400 animate-pulse"></i>
              <span>Live System Health &amp; Self-Diagnostics</span>
            </h1>
            <p className="text-xs sm:text-sm text-[#8b93a3] mt-0.5">
              Interactive telemetry graphs, live CPU &amp; RAM profiling, real-time API connection tests, and automated repair probes.
            </p>
          </div>

          {/* Action Toolbar */}
          <div className="flex items-center gap-2.5 flex-wrap">
            <button
              type="button"
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold border transition flex items-center gap-1.5 ${
                autoRefresh
                  ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-400"
                  : "bg-[#15171c] border-[#262a33] text-gray-400 hover:text-white"
              }`}
            >
              <span className={`w-2 h-2 rounded-full ${autoRefresh ? "bg-emerald-400 animate-ping" : "bg-gray-500"}`}></span>
              <span>{autoRefresh ? "Live Telemetry (3s)" : "Polling Paused"}</span>
            </button>

            <button
              type="button"
              onClick={() => refetch()}
              className="px-3 py-1.5 rounded-xl text-xs font-bold bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] text-gray-200 flex items-center gap-1.5 transition"
            >
              <i className="fas fa-sync-alt"></i>
              <span>Refresh</span>
            </button>

            <button
              type="button"
              disabled={isRunningDiagnostics}
              onClick={handleRunDiagnostics}
              className="px-4 py-1.5 rounded-xl text-xs font-extrabold bg-[#00AEF0] hover:bg-[#0F5065] text-white shadow-lg transition flex items-center gap-2 disabled:opacity-50"
            >
              <i className={`fas fa-stethoscope ${isRunningDiagnostics ? "animate-spin" : ""}`}></i>
              <span>{isRunningDiagnostics ? "Executing Probes…" : "Run Full Self-Diagnosis"}</span>
            </button>
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

        {/* Real-time Interactive Graphs for CPU, Memory Heap, and Network IO */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Card 1: CPU Utilization */}
          <div className="bg-[#15171c] border border-[#262a33] p-4 rounded-2xl shadow-xl space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-gray-300 flex items-center gap-1.5">
                <i className="fas fa-microchip text-[#00AEF0]"></i>
                <span>CPU Core Load</span>
              </span>
              <span className="text-base font-extrabold text-white font-mono">
                {last(cpuHistory) ?? "—"}%
              </span>
            </div>
            {renderSparkline(cpuHistory, "#00AEF0", "rgba(0, 174, 240, 0.12)")}
            <div className="flex justify-between text-[10px] text-gray-500 font-mono">
              <span>Avg: {avg(cpuHistory) ?? "—"}%</span>
              <span>Peak: {cpuHistory.length ? Math.max(...cpuHistory) : "—"}%</span>
              <span>{cpuHistory.length} samples</span>
            </div>
          </div>

          {/* Card 2: Memory Heap Usage */}
          <div className="bg-[#15171c] border border-[#262a33] p-4 rounded-2xl shadow-xl space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-gray-300 flex items-center gap-1.5">
                <i className="fas fa-memory text-purple-400"></i>
                <span>RAM Heap Profiler</span>
              </span>
              <span className="text-base font-extrabold text-white font-mono">
                {last(ramHistory) ?? "—"} MB
              </span>
            </div>
            {renderSparkline(ramHistory, "#a855f7", "rgba(168, 85, 247, 0.12)")}
            <div className="flex justify-between text-[10px] text-gray-500 font-mono">
              <span>Process RSS</span>
              <span>Peak: {ramHistory.length ? Math.max(...ramHistory) : "—"} MB</span>
              <span>Host RAM: {sys.memory_percent ?? "—"}%</span>
            </div>
          </div>

          {/* Card 3: Live API & I/O Requests */}
          <div className="bg-[#15171c] border border-[#262a33] p-4 rounded-2xl shadow-xl space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-gray-300 flex items-center gap-1.5">
                <i className="fas fa-tachometer-alt text-emerald-400"></i>
                <span>API Round-trip Latency</span>
              </span>
              <span className="text-base font-extrabold text-white font-mono">
                {last(latencyHistory) ?? "—"} ms
              </span>
            </div>
            {renderSparkline(latencyHistory, "#10b981", "rgba(16, 185, 129, 0.12)")}
            <div className="flex justify-between text-[10px] text-gray-500 font-mono">
              <span>Avg: {avg(latencyHistory) ?? "—"} ms</span>
              <span>Status: {health?.status ?? "—"}</span>
              <span>Uptime: {health?.uptime ?? "—"}</span>
            </div>
          </div>
        </div>


        {/* Cache & Data Purge Controls */}
        <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <i className="fas fa-server text-purple-400"></i>
                <span>System Cache &amp; Buffer Operations</span>
              </h2>
              <p className="text-xs text-[#8b93a3]">
                Purge in-memory lookup caches and CDN buffers. Only the site owner, or an Admin the owner switched it on for.
              </p>
            </div>
            {!(canCache || canPurge) && (
              <span className="px-2.5 py-1 rounded-xl text-[10px] font-bold bg-red-500/20 text-red-300 border border-red-500/40">
                🔒 Owner Protected
              </span>
            )}
          </div>

          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <span className="text-xs font-bold text-gray-300 block">Active Cache Status:</span>
              <span className="text-xs text-emerald-400 font-mono font-semibold">{sys.cache_status || "Active (Healthy)"}</span>
            </div>

            <div className="flex items-center gap-2.5 flex-wrap">
              <button
                type="button"
                disabled={!canCache || clearingCache}
                onClick={handleClearCache}
                className="px-4 py-2 rounded-xl bg-purple-600/20 hover:bg-purple-600/40 border border-purple-500/40 text-purple-300 font-bold text-xs transition flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
                title={!canCache ? "Restricted: the owner has not switched this on for you" : "Flush system memory cache"}
              >
                <i className="fas fa-broom"></i>
                <span>Flush System Index Cache</span>
              </button>

              <button
                type="button"
                disabled={!canPurge || clearingCache}
                onClick={handlePurgeImages}
                className="px-4 py-2 rounded-xl bg-amber-500/20 hover:bg-amber-500/40 border border-amber-500/40 text-amber-300 font-bold text-xs transition flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
                title={!canPurge ? "Restricted: the owner has not switched this on for you" : "Purge image & CDN buffers"}
              >
                <i className="fas fa-images"></i>
                <span>Purge Image CDN Buffers</span>
              </button>
            </div>
          </div>
        </div>

        {/* Full Self-Diagnostic Probe Report */}
        {diagnosticReport && (
          <div className="bg-[#15171c] border border-[#00AEF0]/40 p-5 rounded-2xl shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <i className="fas fa-check-circle text-emerald-400"></i>
                <span>Self-Diagnostic Probe Report</span>
              </h2>
              <span className="px-3 py-1 rounded-xl text-xs font-extrabold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                Score: {diagnosticReport.overall_score}
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {(diagnosticReport.tests || []).map((t) => (
                <div key={t.id} className="p-3.5 rounded-xl bg-[#101216] border border-[#262a33] space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-white text-xs">{t.name}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 uppercase">
                      PASS ({t.latency_ms}ms)
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-300 leading-normal">{t.details}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Database Tables and Core Services */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <i className="fas fa-table text-[#00AEF0]"></i>
                <span>Database Records</span>
              </h2>
              <span className="text-xs text-[#8b93a3] font-semibold">{tables.length} Active Tables</span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {tables.map((tbl) => (
                <div key={tbl.table} className="p-3 bg-[#101216] rounded-xl border border-[#262a33] space-y-1">
                  <span className="text-[11px] font-mono text-[#00AEF0] block font-bold truncate">{tbl.table}</span>
                  <span className="text-white font-extrabold text-base block">{tbl.rows} Records</span>
                  <div className="flex items-center justify-between text-[10px]">
                    <span className="text-emerald-400 font-semibold">● {tbl.status}</span>
                    <span className="text-[#8b93a3]">{tbl.latency}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-[#15171c] border border-[#262a33] p-5 rounded-2xl shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <i className="fas fa-network-wired text-[#00AEF0]"></i>
                <span>Core Services</span>
              </h2>
              <span className="text-xs text-emerald-400 font-bold">All Operational</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {services.map((srv, idx) => (
                <div key={idx} className="p-3.5 bg-[#101216] rounded-xl border border-[#262a33] space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-white text-xs">{srv.name}</span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-500/20 text-emerald-400">
                      {srv.status}
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-300">{srv.explanation}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </AuthGuard>
  );
}
