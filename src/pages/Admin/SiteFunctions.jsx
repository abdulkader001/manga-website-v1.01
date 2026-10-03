import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import api from "../../services/api";

// Admin -> Site Functions. Every main function of the website with an on/off
// switch. Owner only, and not delegable: there is no permission for this page,
// so nobody else can be given it (not even an Admin). The server enforces each
// switch; the rest of the site hides what is off.

function Switch({ on, busy, label, onClick }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={busy}
      onClick={onClick}
      className={`relative w-14 h-7 rounded-full transition flex-none disabled:opacity-50 ${
        on ? "bg-[#00AEF0]" : "bg-[#262a33]"
      }`}
    >
      <span
        className={`absolute top-1 w-5 h-5 rounded-full bg-white transition-all ${on ? "left-8" : "left-1"}`}
      />
    </button>
  );
}

export default function SiteFunctions() {
  const [data, setData] = useState(null);
  const [busyKey, setBusyKey] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api.admin.siteFunctions.list());
    } catch (err) {
      setError(err.message || "Could not load the site functions.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = async (fn) => {
    const next = !fn.enabled;
    // Turning a function with a warning off asks first; turning it back on never does.
    // A function that is on by default and has a warning is the risky one to switch off.
    if (!next && fn.warning && !window.confirm(`${fn.label}: ${fn.warning}\n\nSwitch it off?`)) return;
    setBusyKey(fn.key);
    setError("");
    try {
      setData(await api.admin.siteFunctions.set(fn.key, next));
    } catch (err) {
      setError(err.message || "Could not change that function.");
    } finally {
      setBusyKey("");
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-3xl mx-auto space-y-6 text-gray-200">
      <div>
        <Link to="/admin" className="text-xs text-[#8b93a3] hover:text-white transition">
          Admin
        </Link>
        <h1 className="text-lg font-bold text-white flex items-center gap-2">
          <i className="fas fa-toggle-on text-emerald-400"></i> Site Functions
        </h1>
        <p className="text-xs text-[#8b93a3] mt-1">
          Switch each main function of the website on or off. A function that is off answers nothing
          on the server and disappears from the pages. Only you can see this page; it can&apos;t be
          given to anyone else.
        </p>
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}
      {!data && !error && <p className="text-xs text-[#8b93a3]">Loading…</p>}

      {data &&
        data.groups.map((group) => {
          const items = data.functions.filter((f) => f.group === group);
          if (!items.length) return null;
          return (
            <section
              key={group}
              className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 shadow-xl space-y-4"
            >
              <h2 className="text-sm font-bold text-white">{group}</h2>
              <ul className="divide-y divide-[#262a33]">
                {items.map((fn) => (
                  <li key={fn.key} className="py-3 first:pt-0 last:pb-0 flex items-start gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-bold text-white">{fn.label}</p>
                      <p className="text-[11px] text-[#8b93a3] mt-0.5">{fn.description}</p>
                      {fn.warning && <p className="text-[11px] text-amber-300 mt-0.5">{fn.warning}</p>}
                    </div>
                    <Switch
                      on={fn.enabled}
                      busy={busyKey === fn.key}
                      label={fn.label}
                      onClick={() => toggle(fn)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          );
        })}

      <p className="text-[11px] text-[#8b93a3]">
        Locked out by a switch? On the server, run{" "}
        <span className="font-mono">cli_bootstrap functions-reset</span> to put every function back to
        its default.
      </p>
    </div>
  );
}
