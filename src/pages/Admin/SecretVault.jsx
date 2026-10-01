import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import api from "../../services/api";
import { CodeForm } from "../../components/AdminSecondFactor";

// Secret vault: the main admin's GUI for integration settings that used to
// live only in .env (OAuth apps, SMTP, API keys). Main admin only, behind an
// enrolled authenticator, and every change needs a fresh vault unlock.

const SOURCE_BADGE = {
  vault: { label: "Vault", cls: "bg-[#00AEF0]/15 text-[#00AEF0] border-[#00AEF0]/40" },
  env: { label: ".env", cls: "bg-amber-500/10 text-amber-300 border-amber-500/30" },
  unset: { label: "Not set", cls: "bg-[#262a33] text-[#8b93a3] border-[#262a33]" },
};

const inputCls =
  "w-full rounded-lg bg-[#0b0d10] border border-[#262a33] px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-[#00AEF0]";

function Entry({ entry, unlocked, onChanged, onLocked }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [revealed, setRevealed] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const badge = SOURCE_BADGE[entry.source] || SOURCE_BADGE.unset;

  const run = async (fn) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      if (e.body?.error?.details?.reason === "vault_locked") onLocked();
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      const res = await api.put(`/admin/vault/${entry.key}`, { value });
      onChanged(res.entry);
      setEditing(false);
      setValue("");
      setRevealed(null);
    });

  const remove = () => {
    const fallback = entry.has_env_fallback ? "the .env value" : "nothing (the setting will be unset)";
    if (!window.confirm(`Remove ${entry.key} from the vault? The site will fall back to ${fallback}.`)) return;
    run(async () => {
      const res = await api.del(`/admin/vault/${entry.key}`);
      onChanged(res.entry);
      setRevealed(null);
    });
  };

  const reveal = () =>
    run(async () => {
      const res = await api.post(`/admin/vault/${entry.key}/reveal`, {});
      setRevealed(res.value ?? "");
      // Don't leave a plaintext secret on screen.
      setTimeout(() => setRevealed(null), 15000);
    });

  return (
    <div className="p-3.5 rounded-xl bg-[#101216] border border-[#262a33] space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-bold text-white flex items-center gap-2 flex-wrap">
            <span>{entry.label}</span>
            <span className={`px-1.5 py-0.5 rounded border text-[10px] font-semibold ${badge.cls}`}>
              {badge.label}
            </span>
            {entry.restart_required && (
              <span
                className="px-1.5 py-0.5 rounded border text-[10px] font-semibold bg-purple-500/10 text-purple-300 border-purple-500/30"
                title="Read once at startup: takes effect after the next restart."
              >
                Restart
              </span>
            )}
          </div>
          <div className="text-[10px] text-[#8b93a3] font-mono mt-0.5">{entry.key}</div>
          {entry.help && <div className="text-[11px] text-[#8b93a3] mt-1">{entry.help}</div>}
        </div>
        {unlocked && !editing && (
          <div className="flex items-center gap-1.5 shrink-0">
            {entry.source !== "unset" && entry.secret && (
              <button
                type="button"
                disabled={busy}
                onClick={reveal}
                className="px-2 py-1 rounded-lg text-[10px] font-bold border border-[#262a33] text-gray-300 hover:text-white hover:border-[#00AEF0] transition disabled:opacity-50"
              >
                Reveal
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(true)}
              className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#00AEF0]/20 border border-[#00AEF0]/40 text-[#00AEF0] hover:bg-[#00AEF0] hover:text-white transition disabled:opacity-50"
            >
              {entry.source === "vault" ? "Change" : "Set"}
            </button>
            {entry.source === "vault" && (
              <button
                type="button"
                disabled={busy}
                onClick={remove}
                className="px-2 py-1 rounded-lg text-[10px] font-bold border border-red-500/40 text-red-300 hover:bg-red-500/20 transition disabled:opacity-50"
              >
                Remove
              </button>
            )}
          </div>
        )}
      </div>

      <div className="text-[11px] font-mono text-gray-300 break-all">
        {revealed != null ? (
          <span className="text-amber-300">{revealed || "(empty)"}</span>
        ) : (
          entry.preview ?? <span className="text-[#8b93a3]">—</span>
        )}
      </div>

      {editing && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <input
            className={inputCls}
            type={entry.secret ? "password" : "text"}
            autoComplete="off"
            spellCheck={false}
            placeholder={entry.kind === "bool" ? "true / false" : entry.kind === "url" ? "https://…" : "New value"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoFocus
          />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={busy || !value.trim()}
              className="px-3 py-1.5 rounded-lg text-[11px] font-bold bg-[#00AEF0] text-white disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save to vault"}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setValue("");
                setError("");
              }}
              className="px-3 py-1.5 rounded-lg text-[11px] font-bold border border-[#262a33] text-gray-300"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && <p className="text-[11px] text-red-400">{error}</p>}
    </div>
  );
}

export default function SecretVault() {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [unlockError, setUnlockError] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api.get("/admin/vault"));
      setLoadError(null);
    } catch (e) {
      setLoadError(e);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const groups = useMemo(() => {
    const out = new Map();
    for (const entry of data?.entries || []) {
      if (!out.has(entry.group)) out.set(entry.group, []);
      out.get(entry.group).push(entry);
    }
    return [...out.entries()];
  }, [data]);

  const unlock = async (code) => {
    setBusy(true);
    setUnlockError("");
    try {
      await api.post("/admin/vault/unlock", { code });
      await load();
    } catch (e) {
      setUnlockError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const lock = async () => {
    try {
      await api.post("/admin/vault/lock", {});
    } finally {
      load();
    }
  };

  const onChanged = (entry) =>
    setData((d) => ({ ...d, entries: d.entries.map((e) => (e.key === entry.key ? entry : e)) }));
  const onLocked = () => setData((d) => ({ ...d, unlocked: false }));

  const reason = loadError?.body?.error?.details?.reason;

  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto space-y-6 text-gray-200">
      <div className="border-b border-[#262a33] pb-4">
        <div className="flex items-center gap-2 text-xs text-[#8b93a3] mb-1">
          <Link to="/admin" className="hover:text-white transition">
            Administrator Hub
          </Link>
          <span>/</span>
          <span className="text-[#00AEF0] font-semibold">Secret Vault</span>
        </div>
        <h1 className="text-2xl font-extrabold text-white flex items-center gap-2.5">
          <i className="fas fa-key text-[#00AEF0]"></i>
          <span>Secret Vault</span>
        </h1>
        <p className="text-xs text-[#8b93a3] mt-1">
          Sign-in providers, email and API keys, encrypted in the database. A value set here
          overrides <span className="font-mono">.env</span>; removing it falls back to{" "}
          <span className="font-mono">.env</span>. Only the main admin can open this page; it cannot
          be granted to anyone else. Database, Redis, signing keys and the main-admin identity stay in{" "}
          <span className="font-mono">.env</span> on purpose.
        </p>
      </div>

      {!data && !loadError && <p className="text-xs text-[#8b93a3]">Loading…</p>}

      {loadError && reason === "enrolment_required" && (
        <div className="p-4 rounded-xl border border-amber-500/40 bg-amber-950/30 text-xs text-amber-200">
          The vault needs two-step sign-in.{" "}
          <Link to="/admin/security" className="underline font-semibold">
            Set up your authenticator app
          </Link>{" "}
          first.
        </div>
      )}
      {loadError && reason !== "enrolment_required" && (
        <p className="text-xs text-red-400">{loadError.message}</p>
      )}

      {data && (
        <>
          <div className="p-4 rounded-2xl bg-[#15171c] border border-[#262a33] flex items-center justify-between gap-4 flex-wrap">
            {data.unlocked ? (
              <>
                <span className="text-xs font-bold text-emerald-400 flex items-center gap-2">
                  <i className="fas fa-lock-open"></i>
                  Unlocked. Changes are allowed for up to {data.unlock_minutes} minutes.
                </span>
                <button
                  type="button"
                  onClick={lock}
                  className="px-3 py-1.5 rounded-lg text-xs font-bold border border-[#262a33] text-gray-300 hover:text-white"
                >
                  Lock now
                </button>
              </>
            ) : (
              <div className="w-full max-w-sm">
                <CodeForm
                  onSubmit={unlock}
                  label="Locked. Enter a code from your authenticator app to change or reveal values."
                  busy={busy}
                  error={unlockError}
                />
              </div>
            )}
          </div>

          {groups.map(([group, entries]) => (
            <section key={group} className="space-y-2">
              <h2 className="text-sm font-bold text-white">{group}</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {entries.map((entry) => (
                  <Entry
                    key={entry.key}
                    entry={entry}
                    unlocked={data.unlocked}
                    onChanged={onChanged}
                    onLocked={onLocked}
                  />
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  );
}
