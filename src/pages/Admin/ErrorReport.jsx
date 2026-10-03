import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import api from "../../services/api";

// Admin -> Error Report: every error the site hit (API server, background
// workers, readers' browsers), grouped so a repeat is one entry with a count,
// each with the likely cause and how to fix it in plain language.

const card = "bg-[#15171c] border border-[#262a33] rounded-2xl p-4 shadow-xl space-y-3 text-xs";
const btn = "px-3 py-1.5 rounded-xl text-xs font-bold transition disabled:opacity-40";
const primary = `${btn} bg-[#00AEF0] hover:bg-[#0F5065] text-white`;
const ghost = `${btn} border border-[#262a33] text-gray-300 hover:text-white`;

export const SOURCE_LABELS = {
  server: { label: "Server", icon: "fas fa-server", tone: "text-red-300 border-red-500/30 bg-red-500/10" },
  worker: { label: "Background job", icon: "fas fa-gears", tone: "text-amber-300 border-amber-500/30 bg-amber-500/10" },
  browser: { label: "Reader's browser", icon: "fas fa-globe", tone: "text-sky-300 border-sky-500/30 bg-sky-500/10" },
};

export const CATEGORY_LABELS = {
  database: "Database",
  redis: "Cache / queue",
  server: "Server",
  provider: "API provider",
  scraper: "Scraper",
  network: "Connection",
  email: "E-mail",
  config: "Missing setting",
  data: "Bad data",
  update: "Site update",
  harmless: "Harmless",
  extension: "Extension / ads",
  storage: "Browser storage",
  code: "Code bug",
  unknown: "Unrecognised",
};

export function timeAgo(iso, now = Date.now()) {
  if (!iso) return "—";
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function Stat({ label, value, tone = "text-white" }) {
  return (
    <div className="p-3 rounded-xl bg-[#101216] border border-[#262a33]">
      <span className="block text-[10px] font-semibold uppercase tracking-wider text-[#8b93a3]">{label}</span>
      <span className={`block text-lg font-extrabold ${tone}`}>{value ?? "—"}</span>
    </div>
  );
}

function Entry({ item, busy, onResolve, onReopen }) {
  const [open, setOpen] = useState(false);
  const src = SOURCE_LABELS[item.source] || SOURCE_LABELS.server;
  return (
    <article className={card} data-testid="error-entry">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`px-2 py-0.5 rounded border text-[10px] font-bold ${src.tone}`}>
              <i className={`${src.icon} mr-1`}></i>
              {src.label}
            </span>
            <span className="px-2 py-0.5 rounded border border-[#262a33] text-[10px] font-bold text-gray-300">
              {CATEGORY_LABELS[item.category] || item.category}
            </span>
            {item.resolved && (
              <span className="px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-[10px] font-bold text-emerald-300">
                Fixed
              </span>
            )}
          </div>
          <h2 className="text-sm font-bold text-white break-words">{item.kind}</h2>
          {item.message && <p className="text-gray-300 break-words">{item.message}</p>}
          {item.location && (
            <p className="text-[11px] text-[#8b93a3]">
              Where: <code className="text-gray-300">{item.location}</code>
            </p>
          )}
        </div>
        <div className="text-right text-[11px] text-[#8b93a3] shrink-0">
          <div className="text-base font-extrabold text-white">{item.count.toLocaleString()}×</div>
          <div>last {timeAgo(item.last_seen)}</div>
          <div>first {timeAgo(item.first_seen)}</div>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="p-3 rounded-xl bg-[#101216] border border-[#262a33]">
          <span className="block text-[10px] font-bold uppercase tracking-wider text-amber-300 mb-1">
            <i className="fas fa-magnifying-glass mr-1"></i>Likely cause
          </span>
          <p className="text-gray-200 leading-relaxed">{item.cause}</p>
        </div>
        <div className="p-3 rounded-xl bg-[#101216] border border-[#262a33]">
          <span className="block text-[10px] font-bold uppercase tracking-wider text-emerald-300 mb-1">
            <i className="fas fa-wrench mr-1"></i>How to fix
          </span>
          <p className="text-gray-200 leading-relaxed">{item.fix}</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" className="text-[11px] text-[#8b93a3] hover:text-white" onClick={() => setOpen((v) => !v)}>
          <i className={`fas fa-chevron-${open ? "up" : "down"} mr-1`}></i>
          Technical details
        </button>
        {item.resolved ? (
          <button type="button" className={ghost} disabled={busy} onClick={() => onReopen(item.id)}>
            Reopen
          </button>
        ) : (
          <button type="button" className={primary} disabled={busy} onClick={() => onResolve(item.id)}>
            Mark fixed
          </button>
        )}
      </div>
      {open && (
        <pre className="max-h-72 overflow-auto rounded-xl bg-[#0b0d10] border border-[#262a33] p-3 text-[10px] text-gray-300 whitespace-pre-wrap break-words">
          {item.stack || "No stack trace was recorded for this error."}
        </pre>
      )}
    </article>
  );
}

export default function ErrorReport() {
  const [status, setStatus] = useState("open");
  const [source, setSource] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError("");
    return api.admin.errorReports
      .list({ status, source: source || undefined })
      .then(setData)
      .catch((err) => setError(err.message || "Could not load the error report."));
  }, [status, source]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (fn) => {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err.message || "That didn't work.");
    } finally {
      setBusy(false);
    }
  };

  const summary = data?.summary || {};
  const items = data?.items || [];

  return (
    <div className="max-w-5xl mx-auto p-4 sm:p-6 space-y-5 text-gray-200">
      <div>
        <Link to="/admin" className="text-[11px] text-[#8b93a3] hover:text-white">
          ← Admin
        </Link>
        <h1 className="text-xl font-bold text-white">Error Report</h1>
        <p className="text-xs text-[#8b93a3]">
          Errors the site hit, from the server, the background jobs and readers&apos; browsers. The same error is one
          entry with a count. Mark an entry fixed once you have dealt with it; it comes back if it happens again.
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
        <Stat label="Open" value={summary.open} tone={summary.open ? "text-red-300" : "text-emerald-300"} />
        <Stat label="Seen in 24 h" value={summary.last_24h} />
        <Stat label="Server" value={summary.by_source?.server} />
        <Stat label="Background jobs" value={summary.by_source?.worker} />
        <Stat label="Browsers" value={summary.by_source?.browser} />
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        {[
          ["open", "Open"],
          ["resolved", "Fixed"],
          ["all", "All"],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setStatus(key)}
            className={`${btn} border ${status === key ? "border-[#00AEF0] bg-[#00AEF0]/10 text-white" : "border-[#262a33] text-gray-300"}`}
          >
            {label}
          </button>
        ))}
        <select
          aria-label="Where the error happened"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="rounded-lg bg-[#0b0d10] border border-[#262a33] px-2 py-1.5 text-xs text-white"
        >
          <option value="">Everywhere</option>
          {Object.entries(SOURCE_LABELS).map(([key, { label }]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <button type="button" className={ghost} disabled={busy} onClick={() => act(load)}>
          <i className="fas fa-rotate mr-1"></i>Refresh
        </button>
        {summary.resolved > 0 && (
          <button
            type="button"
            className={`${ghost} ml-auto`}
            disabled={busy}
            onClick={() => {
              if (window.confirm("Delete every entry marked fixed?")) act(() => api.admin.errorReports.clearResolved());
            }}
          >
            Clear fixed ({summary.resolved})
          </button>
        )}
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}
      {!data && !error && <p className="text-xs text-[#8b93a3]">Loading…</p>}
      {data && items.length === 0 && (
        <p className={`${card} text-center text-[#8b93a3]`}>
          {status === "open" ? "No open errors. Everything recorded so far is fixed." : "Nothing here."}
        </p>
      )}
      <div className="space-y-3">
        {items.map((item) => (
          <Entry
            key={item.id}
            item={item}
            busy={busy}
            onResolve={(id) => act(() => api.admin.errorReports.resolve(id))}
            onReopen={(id) => act(() => api.admin.errorReports.reopen(id))}
          />
        ))}
      </div>
    </div>
  );
}
