import { formatUtcTime } from "../../utils/gstTime";
import React, { useState } from "react";
import { Link } from "react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import useAuth from "../../hooks/useAuth";
import { apiFetch } from "../../services/api";

export default function ChapterReports() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [filterStatus, setFilterStatus] = useState("all");
  const [actionNotice, setActionNotice] = useState(null);
  const [rescrapingId, setRescrapingId] = useState(null);

  // Fetch chapter reports
  const { data: reportsData, isLoading, refetch } = useQuery({
    queryKey: ["chapterReportsAdmin", filterStatus],
    queryFn: async () => {
      const res = await apiFetch(`/api/v1/reports/chapters?status=${filterStatus}`);
      if (!res.ok) throw new Error("Failed to load chapter reports");
      return res.json();
    },
    refetchInterval: 10000,
  });

  // Re-scrape Single Chapter Mutation
  const rescrapeSingleMutation = useMutation({
    mutationFn: async (reportId) => {
      setRescrapingId(reportId);
      const res = await apiFetch(`/api/v1/admin/reports/${reportId}/rescrape-single`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error("Failed to re-scrape single chapter");
      return res.json();
    },
    onSuccess: (data) => {
      setActionNotice({
        type: "success",
        message: data.message || "Chapter singly re-scraped, verified, and restored successfully!",
      });
      queryClient.invalidateQueries({ queryKey: ["chapterReportsAdmin"] });
    },
    onError: (err) => {
      setActionNotice({
        type: "error",
        message: "Failed to re-scrape single chapter: " + (err.message || "Unknown error"),
      });
    },
    onSettled: () => {
      setRescrapingId(null);
      setTimeout(() => setActionNotice(null), 5000);
    },
  });

  // Resolve Report Mutation
  const resolveMutation = useMutation({
    mutationFn: async (reportId) => {
      const res = await apiFetch(`/api/v1/reports/${reportId}/resolve`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Failed to resolve report");
      return res.json();
    },
    onSuccess: () => {
      setActionNotice({ type: "success", message: "Report marked as resolved." });
      queryClient.invalidateQueries({ queryKey: ["chapterReportsAdmin"] });
    },
    onSettled: () => {
      setTimeout(() => setActionNotice(null), 4000);
    },
  });

  // Delete Report Mutation
  const deleteMutation = useMutation({
    mutationFn: async (reportId) => {
      const res = await apiFetch(`/api/v1/reports/${reportId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete report");
      return res.json();
    },
    onSuccess: () => {
      setActionNotice({ type: "success", message: "Report record deleted." });
      queryClient.invalidateQueries({ queryKey: ["chapterReportsAdmin"] });
    },
    onSettled: () => {
      setTimeout(() => setActionNotice(null), 4000);
    },
  });

  const reports = reportsData?.items || [];
  const pendingCount = reportsData?.pending_count || reports.filter((r) => r.status !== "resolved").length;

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#262a33] pb-4">
        <div>
          <Link to="/admin" className="text-xs text-[#00AEF0] hover:underline mb-1 block font-semibold">
            ← Back to Admin Console
          </Link>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center gap-2.5">
            <i className="fas fa-tools text-amber-400"></i>
            <span>Chapter Issue Reports &amp; Single Re-scrape</span>
          </h1>
          <p className="text-xs sm:text-sm text-[#8b93a3] mt-0.5">
            Dedicated triage queue for Sub-Admins and Admins. Re-scrape reported chapters individually without disturbing the rest of the series.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => refetch()}
            className="px-3.5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs transition flex items-center gap-1.5 shadow"
          >
            <i className="fas fa-sync-alt"></i>
            <span>Refresh Queue</span>
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-[#15171c] border border-amber-500/30 p-4 rounded-2xl shadow">
          <div className="flex items-center justify-between text-gray-400 text-xs font-semibold">
            <span>Pending Issue Reports</span>
            <i className="fas fa-exclamation-triangle text-amber-400"></i>
          </div>
          <div className="text-2xl font-black text-amber-400 mt-1">{pendingCount}</div>
          <p className="text-[11px] text-gray-400 mt-0.5">Awaiting single chapter re-scrape</p>
        </div>

        <div className="bg-[#15171c] border border-emerald-500/30 p-4 rounded-2xl shadow">
          <div className="flex items-center justify-between text-gray-400 text-xs font-semibold">
            <span>Resolved Chapters</span>
            <i className="fas fa-check-circle text-emerald-400"></i>
          </div>
          <div className="text-2xl font-black text-emerald-400 mt-1">
            {reports.filter((r) => r.status === "resolved").length}
          </div>
          <p className="text-[11px] text-gray-400 mt-0.5">Singly re-scraped &amp; verified</p>
        </div>

        <div className="bg-[#15171c] border border-[#262a33] p-4 rounded-2xl shadow">
          <div className="flex items-center justify-between text-gray-400 text-xs font-semibold">
            <span>Total Logged Reports</span>
            <i className="fas fa-list text-gray-400"></i>
          </div>
          <div className="text-2xl font-black text-white mt-1">{reports.length}</div>
          <p className="text-[11px] text-gray-400 mt-0.5">History across all series</p>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 border-b border-[#262a33] pb-3">
        {[
          { id: "all", label: "All Reports" },
          { id: "investigating", label: "Pending Investigation" },
          { id: "resolved", label: "Resolved" },
        ].map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setFilterStatus(t.id)}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition ${
              filterStatus === t.id
                ? "bg-[#00AEF0] text-white shadow"
                : "text-gray-400 hover:text-white bg-[#101216] border border-[#262a33]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Action Notification */}
      {actionNotice && (
        <div
          className={`p-3.5 rounded-xl border text-xs flex items-center justify-between animate-in fade-in ${
            actionNotice.type === "error"
              ? "bg-red-950/40 border-red-500/40 text-red-300"
              : "bg-emerald-950/40 border-emerald-500/40 text-emerald-300"
          }`}
        >
          <span>{actionNotice.message}</span>
          <button type="button" onClick={() => setActionNotice(null)} className="text-gray-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Reports List */}
      <div className="space-y-3">
        {isLoading ? (
          <div className="p-8 text-center text-xs text-[#8b93a3]">Loading chapter reports queue…</div>
        ) : reports.length === 0 ? (
          <div className="p-8 text-center bg-[#15171c] border border-[#262a33] rounded-2xl space-y-2">
            <div className="text-2xl">🎉</div>
            <h3 className="text-sm font-bold text-white">No active chapter error reports!</h3>
            <p className="text-xs text-gray-400">All manga reading chapters are verified and running cleanly.</p>
          </div>
        ) : (
          reports.map((report) => {
            const isResolved = report.status === "resolved";
            const isBusy = rescrapingId === report.id;

            return (
              <div
                key={report.id}
                className={`p-4 sm:p-5 rounded-2xl border transition space-y-3 ${
                  isResolved
                    ? "bg-[#101216] border-[#262a33] opacity-75"
                    : "bg-[#15171c] border-amber-500/40 shadow-lg"
                }`}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[#262a33] pb-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider border ${
                          isResolved
                            ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                            : "bg-amber-500/15 text-amber-300 border-amber-500/40 animate-pulse"
                        }`}
                      >
                        {isResolved ? "✓ Resolved" : "🚨 Pending Fix"}
                      </span>
                      <span className="text-xs text-rose-400 font-bold bg-rose-500/10 px-2 py-0.5 rounded-lg border border-rose-500/20">
                        {report.report_type || "Broken Chapter"}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 pt-1 flex-wrap">
                      <Link
                        to={`/manga/${report.manga_id}`}
                        target="_blank"
                        className="font-bold text-white hover:text-[#00AEF0] transition text-sm flex items-center gap-1"
                      >
                        <span>{report.manga_title}</span>
                        <i className="fas fa-external-link-alt text-[10px] text-gray-500"></i>
                      </Link>
                      <span className="text-gray-500">•</span>
                      <Link
                        to={`/reader/${report.manga_id}/${report.chapter_id}`}
                        target="_blank"
                        className="font-mono text-xs font-bold text-[#00AEF0] hover:underline"
                      >
                        {report.chapter_title || `Chapter #${report.chapter_number || report.chapter_id}`}
                      </Link>
                    </div>
                  </div>

                  {/* Actions for Sub-Admin / Admin */}
                  <div className="flex items-center gap-2 flex-wrap">
                    {/* Primary Button: Re-scrape Single Chapter */}
                    <button
                      type="button"
                      onClick={() => rescrapeSingleMutation.mutate(report.id)}
                      disabled={isBusy || rescrapeSingleMutation.isPending}
                      className="px-3.5 py-2 rounded-xl bg-amber-500 hover:bg-amber-600 text-black font-extrabold text-xs transition flex items-center gap-1.5 shadow-md disabled:opacity-50 active:scale-95"
                      title="Re-scrape and rebuild pages strictly for this single chapter"
                    >
                      <i className={isBusy ? "fas fa-spinner fa-spin" : "fas fa-sync-alt"}></i>
                      <span>{isBusy ? "Re-scraping Chapter…" : "⚡ Re-scrape This Single Chapter"}</span>
                    </button>

                    {!isResolved && (
                      <button
                        type="button"
                        onClick={() => resolveMutation.mutate(report.id)}
                        disabled={resolveMutation.isPending}
                        className="px-3 py-2 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-300 font-bold text-xs transition flex items-center gap-1"
                        title="Mark issue resolved"
                      >
                        <i className="fas fa-check"></i>
                        <span>Mark Resolved</span>
                      </button>
                    )}

                    <button
                      type="button"
                      onClick={() => deleteMutation.mutate(report.id)}
                      disabled={deleteMutation.isPending}
                      className="px-2.5 py-2 rounded-xl bg-[#101216] hover:bg-red-500/20 border border-[#262a33] hover:border-red-500/40 text-gray-400 hover:text-red-400 text-xs transition"
                      title="Delete report"
                    >
                      <i className="fas fa-trash-alt"></i>
                    </button>
                  </div>
                </div>

                {/* Details submitted by reader */}
                <div className="bg-[#101216] p-3 rounded-xl border border-[#262a33] text-xs text-gray-300 space-y-1">
                  <div className="text-[11px] text-[#8b93a3] flex items-center justify-between">
                    <span>
                      Reported by: <strong className="text-gray-200">{report.user_name || "Reader"}</strong>
                    </span>
                    <span className="font-mono text-[10px]">
                      {formatUtcTime(report.created_at)}
                    </span>
                  </div>
                  {report.details ? (
                    <p className="text-gray-300 leading-relaxed italic">"{report.details}"</p>
                  ) : (
                    <p className="text-gray-500 text-[11px]">No additional commentary provided.</p>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
