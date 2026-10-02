import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import api, { apiFetch } from "../../services/api";

// Geolock (main admin only): choose countries that can't open the site.

const card = "bg-[#15171c] border border-[#262a33] rounded-2xl p-5 shadow-xl space-y-4 text-xs";
const input =
  "w-full rounded-lg bg-[#0b0d10] border border-[#262a33] px-3 py-2 text-xs text-white focus:outline-none focus:border-[#00AEF0]";
const btn = "px-3 py-2 rounded-xl text-xs font-bold transition disabled:opacity-40";
const primary = `${btn} bg-[#00AEF0] hover:bg-[#0F5065] text-white`;
const ghost = `${btn} border border-[#262a33] text-gray-300 hover:text-white`;

// Quick picks; every country can also be ticked one by one.
export const REGION_PICKS = {
  "North America": ["US", "CA", "MX"],
  "South America": ["AR", "BO", "BR", "CL", "CO", "EC", "GY", "PE", "PY", "SR", "UY", "VE"],
  "European Union": [
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE", "IT",
    "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
  ],
  "Oceania": ["AU", "NZ"],
};

let regionNames = null;
export function countryName(code) {
  try {
    regionNames = regionNames || new Intl.DisplayNames(["en"], { type: "region" });
    return regionNames.of(code) || code;
  } catch {
    return code;
  }
}

export function flag(code) {
  if (!/^[A-Z]{2}$/.test(code)) return "";
  return String.fromCodePoint(...[...code].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}

export default function Geolock() {
  const [data, setData] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [source, setSource] = useState("geoip");
  const [blocked, setBlocked] = useState([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState("");

  const apply = useCallback((res) => {
    setData(res);
    setEnabled(res.enabled);
    setSource(res.source);
    setBlocked(res.blocked);
  }, []);

  useEffect(() => {
    api
      .get("/admin/geolock")
      .then(apply)
      .catch((e) => setError(e.message));
  }, [apply]);

  const countries = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    return data.countries
      .map((code) => ({ code, name: countryName(code) }))
      .filter((c) => !q || c.code.toLowerCase() === q || c.name.toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [data, query]);

  const toggle = (code) =>
    setBlocked((list) => (list.includes(code) ? list.filter((c) => c !== code) : [...list, code].sort()));

  const save = async (confirmSelf = false) => {
    setBusy(true);
    setNotice(null);
    try {
      apply(await api.put("/admin/geolock", { enabled, blocked, source, confirm_self_block: confirmSelf }));
      setNotice({ ok: true, text: enabled ? "Saved. Blocked countries see “not available” within a minute." : "Saved. Geolock is off." });
    } catch (e) {
      const reason = e.body?.error?.details?.reason;
      if (reason === "would_block_you" && !confirmSelf) {
        const ok = window.confirm(
          `${e.message}\n\nIf you go ahead, you can only switch it off again from the server:\n` +
            "docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap geolock-off\n\nBlock it anyway?"
        );
        setBusy(false);
        if (ok) await save(true);
        return;
      }
      setNotice({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const updateDb = async () => {
    setBusy(true);
    setNotice(null);
    try {
      apply(await api.post("/admin/geolock/database/update", {}));
      setNotice({ ok: true, text: "Country database installed." });
    } catch (e) {
      setNotice({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const uploadDb = async (file) => {
    if (!file) return;
    setBusy(true);
    setNotice(null);
    try {
      const res = await apiFetch("/admin/geolock/database/upload", {
        method: "POST",
        body: file,
        headers: { "Content-Type": "application/octet-stream" },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.error?.message || `Upload failed (${res.status})`);
      apply(body);
      setNotice({ ok: true, text: "Country database installed." });
    } catch (e) {
      setNotice({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  if (error) return <p className="p-6 text-xs text-red-400">{error}</p>;
  if (!data) return <p className="p-6 text-xs text-[#8b93a3]">Loading…</p>;

  const db = data.database;
  const you = data.your_country;

  return (
    <div className="max-w-5xl mx-auto p-4 sm:p-6 space-y-5 text-gray-200">
      <div>
        <Link to="/admin" className="text-[11px] text-[#8b93a3] hover:text-white">
          ← Admin
        </Link>
        <h1 className="text-xl font-bold text-white">Geolock</h1>
        <p className="text-xs text-[#8b93a3]">
          Visitors from the countries you tick see “This site isn&apos;t available in your country”.
          {you ? ` You are in ${flag(you)} ${countryName(you)}.` : " Your country can't be told from here (local network or no database)."}
        </p>
      </div>

      {notice && <p className={`text-xs ${notice.ok ? "text-emerald-400" : "text-red-400"}`}>{notice.text}</p>}

      <section className={card}>
        <label className="flex items-center gap-2 text-sm font-bold text-white">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Geolock on
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[
            ["geoip", "Country database on this server", "Works anywhere. Needs the free database below."],
            ["cloudflare", "Cloudflare's country header", "Only if every visitor comes through Cloudflare (otherwise it can be faked)."],
          ].map(([key, label, desc]) => (
            <button
              key={key}
              type="button"
              onClick={() => setSource(key)}
              className={`p-3 rounded-xl border text-left ${
                source === key ? "border-[#00AEF0] bg-[#00AEF0]/10" : "border-[#262a33] bg-[#101216] hover:border-[#00AEF0]/50"
              }`}
            >
              <span className="block font-bold text-white">{label}</span>
              <span className="block text-[10px] text-[#8b93a3]">{desc}</span>
            </button>
          ))}
        </div>
        {source === "geoip" && (
          <div className="p-3 rounded-xl bg-[#101216] border border-[#262a33] flex flex-wrap items-center gap-2">
            <span>
              {db.installed ? (
                <>
                  Database: <b>{db.type}</b>
                  {db.built_at ? `, built ${db.built_at}` : ""}
                </>
              ) : (
                <span className="text-amber-300">No country database yet.</span>
              )}
            </span>
            <span className="ml-auto flex gap-2">
              <button type="button" className={ghost} disabled={busy} onClick={updateDb}>
                {db.installed ? "Update (free DB-IP)" : "Download free database (DB-IP)"}
              </button>
              <label className={`${ghost} cursor-pointer`}>
                Upload .mmdb
                <input type="file" accept=".mmdb" className="hidden" disabled={busy} onChange={(e) => uploadDb(e.target.files?.[0])} />
              </label>
            </span>
          </div>
        )}
      </section>

      <section className={card}>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-bold text-white mr-auto">Blocked countries ({blocked.length})</h2>
          {Object.entries(REGION_PICKS).map(([label, codes]) => (
            <button
              key={label}
              type="button"
              className={ghost}
              onClick={() => setBlocked((list) => Array.from(new Set([...list, ...codes])).sort())}
            >
              + {label}
            </button>
          ))}
          {blocked.length > 0 && (
            <button type="button" className={ghost} onClick={() => setBlocked([])}>
              Clear
            </button>
          )}
        </div>
        {blocked.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {blocked.map((code) => (
              <button
                key={code}
                type="button"
                onClick={() => toggle(code)}
                className={`px-2 py-1 rounded-full border text-[11px] ${
                  code === you ? "border-red-500 bg-red-500/15 text-red-200" : "border-[#262a33] bg-[#101216] text-gray-200"
                }`}
                title="Remove"
              >
                {flag(code)} {countryName(code)} ✕
              </button>
            ))}
          </div>
        )}
        <input className={input} placeholder="Search countries (name or code)" value={query} onChange={(e) => setQuery(e.target.value)} />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1 max-h-80 overflow-y-auto pr-1">
          {countries.map((c) => (
            <label key={c.code} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-[#101216] cursor-pointer">
              <input type="checkbox" checked={blocked.includes(c.code)} onChange={() => toggle(c.code)} />
              <span>{flag(c.code)}</span>
              <span className="flex-1">{c.name}</span>
              <span className="font-mono text-[10px] text-[#8b93a3]">{c.code}</span>
            </label>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <button type="button" className={primary} disabled={busy} onClick={() => save(false)}>
            {busy ? "Saving…" : "Save"}
          </button>
          <span className="text-[10px] text-[#8b93a3]">
            VPN users can get around any country lock. Picture files are served straight by the web server and are not
            checked; without the site&apos;s pages they can&apos;t be browsed.
          </span>
        </div>
      </section>

      <p className="text-[10px] text-[#8b93a3]">
        <a href={data.attribution.url} target="_blank" rel="noopener noreferrer" className="underline">
          {data.attribution.text}
        </a>
      </p>
    </div>
  );
}
