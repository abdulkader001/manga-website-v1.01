import React, { useEffect, useState } from "react";
import api from "../services/api";

// Admin Settings -> Donations. Main admin only. The server checks every entry
// (known platforms over https, addresses matching their network) and saves
// all or nothing; every change is logged and shown in the admin's bell.

const field =
  "w-full bg-[#101216] border border-[#262a33] rounded-xl px-3 py-2 text-white text-xs placeholder-gray-600 focus:outline-none focus:border-[#00AEF0]";

const blankLink = () => ({ kind: "link", platform: "kofi", url: "", note: "", enabled: true });
const blankCrypto = () => ({ kind: "crypto", network: "btc", address: "", note: "", enabled: true });

export default function DonationEditor() {
  const [links, setLinks] = useState([]);
  const [options, setOptions] = useState({ platforms: [], networks: [] });
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    api.admin.support
      .get()
      .then((data) => {
        setLinks(data?.links || []);
        setOptions({ platforms: data?.platforms || [], networks: data?.networks || [] });
      })
      .catch((e) => setNotice({ type: "error", text: e.message }))
      .finally(() => setLoaded(true));
  }, []);

  const update = (index, patch) => setLinks((ls) => ls.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  const remove = (index) => setLinks((ls) => ls.filter((_, i) => i !== index));

  const save = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const data = await api.admin.support.update(links);
      setLinks(data?.links || []);
      setNotice({ type: "ok", text: "Saved. The change is in your notifications and the audit log." });
    } catch (e) {
      setNotice({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const hostsFor = (platform) => options.platforms.find((p) => p.id === platform)?.hosts?.join(", ") || "";

  return (
    <div className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 sm:p-6 shadow-xl space-y-4 text-xs">
      <div>
        <h2 className="text-base font-bold text-white flex items-center gap-2">
          <i className="fas fa-hand-holding-heart text-pink-400"></i>
          <span>Donations &amp; support links</span>
        </h2>
        <p className="text-[#8b93a3] mt-1">
          Shown in the footer as &quot;Support the site&quot;. Links must be https on the platform&apos;s own
          site; crypto addresses must match the network you pick. Double-check every address by
          sending a small amount first.
        </p>
      </div>

      {!loaded && <p className="text-[#8b93a3]">Loading…</p>}

      {links.map((l, i) => (
        <div key={l.id || i} className="rounded-xl border border-[#262a33] bg-[#101216]/60 p-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-bold text-white">{i + 1}.</span>
            {l.kind === "link" ? (
              <select
                className={`${field} w-auto`}
                value={l.platform}
                onChange={(e) => update(i, { platform: e.target.value })}
                aria-label="Platform"
              >
                {options.platforms.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            ) : (
              <select
                className={`${field} w-auto`}
                value={l.network}
                onChange={(e) => update(i, { network: e.target.value })}
                aria-label="Network"
              >
                {options.networks.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
              </select>
            )}
            <label className="flex items-center gap-1.5 text-[#8b93a3]">
              <input type="checkbox" checked={l.enabled !== false} onChange={(e) => update(i, { enabled: e.target.checked })} />
              Shown
            </label>
            <button type="button" onClick={() => remove(i)} className="ml-auto text-red-400 hover:text-red-300">
              Remove
            </button>
          </div>
          {l.kind === "link" ? (
            <input
              className={`${field} font-mono`}
              placeholder={`https://${(hostsFor(l.platform).split(", ")[0] || "ko-fi.com")}/yourname`}
              value={l.url || ""}
              onChange={(e) => update(i, { url: e.target.value })}
              aria-label="Link"
            />
          ) : (
            <input
              className={`${field} font-mono`}
              placeholder="Wallet address"
              value={l.address || ""}
              onChange={(e) => update(i, { address: e.target.value })}
              aria-label="Address"
              spellCheck={false}
            />
          )}
          <input
            className={field}
            placeholder="Short note (optional)"
            maxLength={120}
            value={l.note || ""}
            onChange={(e) => update(i, { note: e.target.value })}
            aria-label="Note"
          />
        </div>
      ))}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setLinks((ls) => [...ls, blankLink()])}
          className="px-3 py-2 rounded-xl border border-[#262a33] text-gray-200 hover:border-[#00AEF0]"
        >
          + Payment link
        </button>
        <button
          type="button"
          onClick={() => setLinks((ls) => [...ls, blankCrypto()])}
          className="px-3 py-2 rounded-xl border border-[#262a33] text-gray-200 hover:border-[#00AEF0]"
        >
          + Crypto address
        </button>
        <button
          type="button"
          onClick={save}
          disabled={busy || !loaded}
          className="ml-auto px-4 py-2 rounded-xl font-bold bg-[#00AEF0] text-white disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save donation links"}
        </button>
      </div>

      {notice && <p className={notice.type === "error" ? "text-red-400" : "text-emerald-400"}>{notice.text}</p>}
    </div>
  );
}
