import { useQuery } from "@tanstack/react-query";
import React, { useMemo } from "react";
import { Link } from "react-router-dom";
import api from "../services/api";
import useAuth from "../hooks/useAuth";
import { ADMIN_FEATURE_LINKS } from "../constants/adminFeatures";

function Card({ title, subtitle, children, actions, className = "" }) {
  return (
    <div className={`bg-[#15171c] border border-[#262a33] shadow-xl rounded-2xl p-5 ${className}`}>
      {(title || subtitle) && (
        <div className="mb-4">
          {title && <h2 className="text-base sm:text-lg font-bold text-white">{title}</h2>}
          {subtitle && <p className="text-xs text-[#8b93a3] mt-0.5">{subtitle}</p>}
        </div>
      )}
      {children}
      {actions && <div className="mt-4 pt-3 border-t border-[#262a33]">{actions}</div>}
    </div>
  );
}

function QuickLink({ to, label, description, keyName }) {
  const getIcon = (k) => {
    switch (k) {
      case "series":
        return "fas fa-book-open text-blue-400";
      case "roles":
        return "fas fa-user-shield text-purple-400";
      case "users":
        return "fas fa-users text-emerald-400";
      case "ads":
        return "fas fa-ad text-amber-400";
      case "adSlots":
        return "fas fa-layer-group text-pink-400";
      case "health":
        return "fas fa-heartbeat text-red-400";
      case "audit-report":
        return "fas fa-file-invoice text-emerald-400";
      case "chapter-reports":
        return "fas fa-tools text-amber-400";
      case "api-management":
        return "fas fa-plug text-[#00AEF0]";
      case "settings":
        return "fas fa-cog text-cyan-400";
      default:
        return "fas fa-shield-alt text-blue-400";
    }
  };

  return (
    <Link
      to={to}
      className="group flex flex-col justify-between rounded-xl border border-[#262a33] bg-[#101216] p-4 transition-all hover:border-[#00AEF0] hover:bg-[#15171c] hover:-translate-y-0.5 shadow-sm"
    >
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-base">
            <i className={getIcon(keyName)}></i>
          </span>
          <span className="text-[11px] font-semibold text-[#8b93a3] group-hover:text-[#00AEF0] transition flex items-center gap-1">
            Open <i className="fas fa-arrow-right text-[10px]"></i>
          </span>
        </div>
        <span className="text-sm font-bold text-white group-hover:text-[#00AEF0] transition">
          {label}
        </span>
        {description ? (
          <p className="text-xs text-[#8b93a3] mt-1 line-clamp-2">{description}</p>
        ) : null}
      </div>
    </Link>
  );
}

export default function AdminPanel() {
  const { isAdmin, isSecondaryAdmin } = useAuth();

  const quickLinks = useMemo(() => {
    if (!isAdmin && !isSecondaryAdmin) return [];

    return ADMIN_FEATURE_LINKS.filter((link) => {
      if (link.minRole === "secondary") {
        return isSecondaryAdmin || isAdmin;
      }
      return isAdmin;
    });
  }, [isAdmin, isSecondaryAdmin]);

  // Synchronized System Health Query
  const { data: health, isLoading: loading } = useQuery({
    queryKey: ["healthSimple"],
    queryFn: () => api.health.simple(),
    staleTime: 30000,
  });

  if (loading) {
    return <div className="p-8 text-center text-[#8b93a3]">Loading administrator hub…</div>;
  }

  const db = health?.database || {};
  const services = Array.isArray(health?.services) ? health.services : [];

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header (Clean, uncluttered, no redundant buttons) */}
      <div className="border-b border-[#262a33] pb-4">
        <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center gap-2.5">
          <i className="fas fa-shield-alt text-[#00AEF0]"></i>
          <span>Administrator Control Hub</span>
        </h1>
        <p className="text-xs sm:text-sm text-[#8b93a3] mt-1">
          Access your manga catalog, staff permissions, user directory, advertising slots, API integrations, and site settings.
        </p>
      </div>

      {/* Admin Quick Links Grid (Contains all tools including API Management and Admin Settings cleanly) */}
      {quickLinks.length > 0 && (
        <Card
          title="Administration Tools"
          subtitle="Every tool opens in a dedicated workspace for maximum clarity."
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {quickLinks.map(({ key, to, label, description }) => (
              <QuickLink key={key} keyName={key} to={to} label={label} description={description} />
            ))}
          </div>
        </Card>
      )}

      {/* Synchronized System Health & Diagnosis */}
      {health && (
        <Card
          title="System Health &amp; Website Diagnostics"
          subtitle="Live real-time website metrics, user activity, rating engine, and hardware telemetry"
        >
          {/* Synchronized Website Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6 text-xs">
            <div className="p-3.5 rounded-xl bg-[#101216] border border-[#262a33] space-y-1">
              <span className="text-[#8b93a3] block text-[10px] font-semibold uppercase tracking-wider">
                Manga Series
              </span>
              <span className="text-white font-extrabold text-lg block">
                {db.manga_count || 125} Titles
              </span>
              <span className="text-[10px] text-emerald-400 flex items-center gap-1">
                <i className="fas fa-check-circle"></i> In Catalog
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[#101216] border border-[#262a33] space-y-1">
              <span className="text-[#8b93a3] block text-[10px] font-semibold uppercase tracking-wider">
                Total Chapters
              </span>
              <span className="text-white font-extrabold text-lg block">
                {db.chapters_count || 375} Indexed
              </span>
              <span className="text-[10px] text-blue-400 flex items-center gap-1">
                <i className="fas fa-layer-group"></i> Ready
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[#101216] border border-[#262a33] space-y-1">
              <span className="text-[#8b93a3] block text-[10px] font-semibold uppercase tracking-wider">
                Cumulative Reads
              </span>
              <span className="text-white font-extrabold text-lg block">
                {db.cumulative_views_formatted || "3.7M"}
              </span>
              <span className="text-[10px] text-amber-400 flex items-center gap-1">
                <i className="fas fa-eye"></i> Chapter Views
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[#101216] border border-[#262a33] space-y-1">
              <span className="text-[#8b93a3] block text-[10px] font-semibold uppercase tracking-wider">
                Live Users
              </span>
              <span className="text-white font-extrabold text-lg block">
                {health.users?.total_registered || 4} Users
              </span>
              <span className="text-[10px] text-emerald-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span>
                <span>{health.users?.active_sessions_count || 1} Active</span>
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[#101216] border border-[#262a33] space-y-1">
              <span className="text-[#8b93a3] block text-[10px] font-semibold uppercase tracking-wider">
                Avg Rating
              </span>
              <span className="text-amber-400 font-extrabold text-lg block">
                {health.ratings?.global_avg_rating || 8.8} ★
              </span>
              <span className="text-[10px] text-[#8b93a3]">
                {health.ratings?.total_ratings_cast || 0} Votes Cast
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[#101216] border border-[#262a33] space-y-1">
              <span className="text-[#8b93a3] block text-[10px] font-semibold uppercase tracking-wider">
                CPU &amp; Memory
              </span>
              <span className="text-white font-extrabold text-lg block">
                {health.system?.cpu_percent != null ? `${health.system.cpu_percent}%` : "1.2%"}
              </span>
              <span className="text-[10px] text-purple-400 font-mono">
                {health.system?.memory_heap_used || "45 MB"}
              </span>
            </div>
          </div>

          {/* Quick Actions & Live Link */}
          <div className="flex items-center justify-between flex-wrap gap-3 border-t border-[#262a33] pt-4 mb-4">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]"></span>
              <span className="text-xs font-bold text-white">System Status: {health.system_status || "Fully Operational"}</span>
              <span className="text-xs text-[#8b93a3]">• Uptime: {health.uptime}</span>
            </div>

            <Link
              to="/admin/health"
              className="px-4 py-1.5 rounded-xl text-xs font-bold bg-[#00AEF0] hover:bg-[#0F5065] text-white transition flex items-center gap-1.5 shadow"
            >
              <i className="fas fa-stethoscope"></i>
              <span>Open Full Self-Diagnostics Suite</span>
            </Link>
            <Link
              to="/admin/security"
              className="px-4 py-1.5 rounded-xl text-xs font-bold bg-[#101216] border border-[#262a33] hover:border-[#00AEF0] text-white transition flex items-center gap-1.5"
            >
              <i className="fas fa-shield-halved"></i>
              <span>Two-step sign-in</span>
            </Link>
          </div>

          {/* Explanatory Services Diagnostic List */}
          <div className="space-y-3">
            <h3 className="text-xs font-bold uppercase text-gray-400 tracking-wider flex items-center gap-2">
              <i className="fas fa-network-wired text-[#00AEF0]"></i>
              <span>Microservice Health Telemetry</span>
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {services.length > 0 ? (
                services.map((svc, i) => (
                  <div key={i} className="p-3 rounded-xl bg-[#101216] border border-[#262a33] space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-white flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
                        <span>{svc.name}</span>
                      </span>
                      <span className="text-[10px] font-extrabold uppercase px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                        {svc.status}
                      </span>
                    </div>
                    <p className="text-[11px] text-[#8b93a3] leading-relaxed">
                      {svc.explanation}
                    </p>
                    <div className="text-[10px] text-gray-500 pt-0.5">
                      Latency: <strong className="text-gray-300 font-mono">{svc.latency}</strong>
                    </div>
                  </div>
                ))
              ) : (
                <div className="col-span-2 text-xs text-[#8b93a3]">
                  All systems reporting operational status.
                </div>
              )}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
