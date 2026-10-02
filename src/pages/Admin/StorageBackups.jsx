import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import api, { BASE_URL, apiFetch } from "../../services/api";

// Storage & Backups (main admin only): whole-site archives on this server,
// optionally copied to S3-compatible storage (R2, B2, MinIO...), weekly on a
// schedule, downloadable, and restorable here or on a new server.

const card = "bg-[#15171c] border border-[#262a33] rounded-2xl p-5 shadow-xl space-y-4 text-xs";
const input =
  "w-full rounded-lg bg-[#0b0d10] border border-[#262a33] px-3 py-2 text-xs text-white focus:outline-none focus:border-[#00AEF0]";
const btn = "px-3 py-2 rounded-xl text-xs font-bold transition disabled:opacity-40";
const primary = `${btn} bg-[#00AEF0] hover:bg-[#0F5065] text-white`;
const ghost = `${btn} border border-[#262a33] text-gray-300 hover:text-white`;
const danger = `${btn} border border-red-500/40 text-red-300 hover:bg-red-500/10`;
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const TRIGGER_LABEL = {
  manual: "Manual",
  scheduled: "Weekly",
  pre_restore: "Safety copy",
  uploaded: "Uploaded",
  fetched: "From storage",
};

export function formatBytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return `${v} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let x = v / 1024;
  let i = 0;
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024;
    i += 1;
  }
  return `${x.toFixed(x >= 100 ? 0 : 1)} ${units[i]}`;
}

function when(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function Badge({ children, tone = "gray" }) {
  const tones = {
    gray: "bg-[#262a33] text-[#8b93a3] border-[#262a33]",
    blue: "bg-[#00AEF0]/15 text-[#00AEF0] border-[#00AEF0]/40",
    green: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
    amber: "bg-amber-500/10 text-amber-300 border-amber-500/30",
    red: "bg-red-500/10 text-red-300 border-red-500/30",
  };
  return <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${tones[tone]}`}>{children}</span>;
}

function JobStatus({ status }) {
  if (!status || status.state === "idle") return null;
  const running = status.state === "running" || status.state === "queued";
  const tone = running ? "blue" : status.state === "failed" ? "red" : "green";
  const verb = { backup: "Backup", restore: "Restore", fetch: "Download from storage" }[status.action] || "Job";
  return (
    <div
      role="status"
      className={`p-3 rounded-xl border text-xs flex items-center gap-2 ${
        tone === "red"
          ? "border-red-500/40 bg-red-500/10 text-red-200"
          : tone === "green"
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
          : "border-[#00AEF0]/40 bg-[#00AEF0]/10 text-[#bfefff]"
      }`}
    >
      {running && <i className="fas fa-spinner fa-spin"></i>}
      <span className="font-bold">
        {verb}: {running ? "working" : status.state === "failed" ? "failed" : "finished"}
      </span>
      <span>{status.message}</span>
    </div>
  );
}

function RestoreDialog({ backup, onClose, onDone }) {
  const [confirm, setConfirm] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const go = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post(`/admin/backups/files/${encodeURIComponent(backup.name)}/restore`, {
        confirm,
        password: password || undefined,
      });
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="max-w-md w-full bg-[#101216] border border-red-500/40 rounded-2xl p-5 space-y-3 text-xs text-gray-200">
        <h3 className="text-sm font-bold text-white">Restore {backup.name}?</h3>
        <p>
          This replaces the site&apos;s whole database{backup.includes_images === false ? "" : " and the pictures in this backup"}{" "}
          with the backup&apos;s copy. Everything changed since it was made is lost. A safety copy of the current
          database is made first, so you can undo it from this list.
        </p>
        {backup.encrypted && (
          <label className="block space-y-1">
            <span className="font-bold text-gray-300">Backup password</span>
            <input
              type="password"
              className={input}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Leave empty to use this site's backup password"
              autoComplete="off"
            />
          </label>
        )}
        <label className="block space-y-1">
          <span className="font-bold text-gray-300">Type RESTORE to confirm</span>
          <input className={input} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoFocus />
        </label>
        {error && <p className="text-red-400">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className={ghost} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={`${btn} bg-red-600 hover:bg-red-700 text-white`} disabled={confirm !== "RESTORE" || busy} onClick={go}>
            {busy ? "Starting…" : "Restore"}
          </button>
        </div>
      </div>
    </div>
  );
}

function StorageForm({ storage, onSaved }) {
  const [form, setForm] = useState({
    endpoint: storage.endpoint || "",
    region: storage.region || "auto",
    bucket: storage.bucket || "",
    prefix: storage.prefix ?? "mangaworld-backups",
    access_key_id: "",
    secret_access_key: "",
  });
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const run = async (action) => {
    setBusy(true);
    setNote(null);
    try {
      if (action === "test") {
        await api.post("/admin/backups/storage/test", form);
        setNote({ ok: true, text: "Works: the storage accepted a test file and it was deleted again." });
      } else {
        onSaved(await api.put("/admin/backups/storage", form));
        setNote({ ok: true, text: "Connected. New backups are copied there automatically." });
      }
    } catch (e) {
      setNote({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };
  const field = (key, label, props = {}) => (
    <label className="block space-y-1">
      <span className="font-bold text-gray-300">{label}</span>
      <input className={input} value={form[key]} onChange={set(key)} autoComplete="off" {...props} />
    </label>
  );
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {field("endpoint", "Endpoint", { placeholder: "https://<account>.r2.cloudflarestorage.com" })}
        {field("region", "Region", { placeholder: "auto (R2) or e.g. us-west-004 (B2)" })}
        {field("bucket", "Bucket")}
        {field("prefix", "Folder in the bucket")}
        {field("access_key_id", "Access key ID", { placeholder: storage.connected ? "Enter again to change" : "" })}
        {field("secret_access_key", "Secret access key", {
          type: "password",
          placeholder: storage.connected ? "Leave empty to keep the saved one" : "",
        })}
      </div>
      <p className="text-[10px] text-[#8b93a3]">
        Keys are saved in the Secret Vault. Use a key limited to this one bucket. The storage is tested (write, read,
        delete) before anything is saved.
      </p>
      {note && <p className={note.ok ? "text-emerald-400" : "text-red-400"}>{note.text}</p>}
      <div className="flex gap-2">
        <button type="button" className={ghost} disabled={busy} onClick={() => run("test")}>
          Test connection
        </button>
        <button type="button" className={primary} disabled={busy} onClick={() => run("save")}>
          {busy ? "Checking…" : storage.connected ? "Save changes" : "Connect"}
        </button>
      </div>
    </div>
  );
}

export default function StorageBackups() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(null);
  const [restoring, setRestoring] = useState(null);
  const [remote, setRemote] = useState(null);
  const [settings, setSettings] = useState(null);
  const [password, setPassword] = useState("");
  const [uploading, setUploading] = useState(false);
  const [withPictures, setWithPictures] = useState(true);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get("/admin/backups");
      setData(res);
      setSettings((s) => s || res.settings);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const busyJob = data && ["running", "queued"].includes(data.status?.state);
  useEffect(() => {
    if (!busyJob) return undefined;
    const t = setInterval(async () => {
      try {
        const res = await api.get("/admin/backups/status");
        setData((d) => ({ ...d, status: res.status, backups: res.backups }));
        if (!["running", "queued"].includes(res.status?.state)) load();
      } catch {
        // keep polling quietly
      }
    }, 3000);
    return () => clearInterval(t);
  }, [busyJob, load]);

  const act = async (fn, okText) => {
    setNotice(null);
    try {
      const res = await fn();
      if (res && res.settings) setData(res);
      if (okText) setNotice({ ok: true, text: okText });
      await load();
    } catch (e) {
      setNotice({ ok: false, text: e.message });
    }
  };

  const upload = async (file) => {
    if (!file) return;
    setUploading(true);
    setNotice(null);
    try {
      const res = await apiFetch(`/admin/backups/upload?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        body: file,
        headers: { "Content-Type": "application/octet-stream" },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.error?.message || `Upload failed (${res.status})`);
      setNotice({ ok: true, text: `Uploaded as ${body.backup.name}. Press Restore on it when you are ready.` });
      await load();
    } catch (e) {
      setNotice({ ok: false, text: e.message });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  if (error) return <p className="p-6 text-xs text-red-400">{error}</p>;
  if (!data || !settings) return <p className="p-6 text-xs text-[#8b93a3]">Loading…</p>;

  const { storage, disk, backups, status } = data;

  return (
    <div className="max-w-5xl mx-auto p-4 sm:p-6 space-y-5 text-gray-200">
      <div className="flex items-center justify-between gap-3">
        <div>
          <Link to="/admin" className="text-[11px] text-[#8b93a3] hover:text-white">
            ← Admin
          </Link>
          <h1 className="text-xl font-bold text-white">Storage &amp; Backups</h1>
          <p className="text-xs text-[#8b93a3]">
            Free disk {formatBytes(disk.free)} · backups use {formatBytes(disk.backups)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[11px] text-gray-300">
            <input type="checkbox" checked={withPictures} onChange={(e) => setWithPictures(e.target.checked)} />
            With pictures
          </label>
          <button
            type="button"
            className={primary}
            disabled={busyJob}
            onClick={() => act(() => api.post("/admin/backups/run", { include_images: withPictures }), "Backup started.")}
          >
            <i className="fas fa-box-archive mr-1.5"></i>Back up now
          </button>
        </div>
      </div>

      <JobStatus status={status} />
      {notice && <p className={`text-xs ${notice.ok ? "text-emerald-400" : "text-red-400"}`}>{notice.text}</p>}

      {/* Backups on this server */}
      <section className={card}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-white">Backups on this server</h2>
          <label className={`${ghost} cursor-pointer`}>
            <i className={uploading ? "fas fa-spinner fa-spin mr-1.5" : "fas fa-upload mr-1.5"}></i>
            {uploading ? "Uploading… keep this page open" : "Upload a backup"}
            <input
              ref={fileRef}
              type="file"
              accept=".zip,.enc"
              className="hidden"
              disabled={uploading}
              onChange={(e) => upload(e.target.files?.[0])}
            />
          </label>
        </div>
        {backups.length === 0 ? (
          <p className="text-[#8b93a3]">No backups yet. Press “Back up now”.</p>
        ) : (
          <ul className="divide-y divide-[#262a33]">
            {backups.map((b) => (
              <li key={b.name} className="py-3 flex flex-wrap items-center gap-3">
                <div className="flex-1 min-w-[220px]">
                  <div className="font-mono text-white break-all">{b.name}</div>
                  <div className="flex flex-wrap gap-1.5 mt-1 items-center text-[10px] text-[#8b93a3]">
                    <span>{when(b.created_at)}</span>·<span>{formatBytes(b.size)}</span>
                    <Badge>{TRIGGER_LABEL[b.trigger] || "Backup"}</Badge>
                    {b.includes_images === false ? <Badge>Database only</Badge> : b.includes_images ? <Badge>With pictures</Badge> : null}
                    {b.encrypted && <Badge tone="green">Encrypted</Badge>}
                    {b.remote?.uploaded && <Badge tone="blue">Copied to storage</Badge>}
                    {b.remote && !b.remote.uploaded && <Badge tone="amber">Storage copy failed</Badge>}
                  </div>
                </div>
                <a className={ghost} href={`${BASE_URL}/admin/backups/files/${encodeURIComponent(b.name)}`} download>
                  <i className="fas fa-download mr-1"></i>Download
                </a>
                <button type="button" className={danger} disabled={busyJob} onClick={() => setRestoring(b)}>
                  Restore
                </button>
                <button
                  type="button"
                  className={ghost}
                  disabled={busyJob}
                  aria-label={`Delete ${b.name}`}
                  onClick={() =>
                    window.confirm(`Delete ${b.name} from this server?`) &&
                    act(() => api.del(`/admin/backups/files/${encodeURIComponent(b.name)}`), "Deleted.")
                  }
                >
                  <i className="fas fa-trash"></i>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Schedule */}
      <section className={card}>
        <h2 className="text-sm font-bold text-white">Weekly backup</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 items-end">
          <label className="flex items-center gap-2 col-span-2 sm:col-span-4">
            <input
              type="checkbox"
              checked={settings.schedule_enabled}
              onChange={(e) => setSettings({ ...settings, schedule_enabled: e.target.checked })}
            />
            <span className="font-bold">Make a backup every week</span>
            {data.settings.next_run && <span className="text-[#8b93a3]">· next: {when(data.settings.next_run)}</span>}
          </label>
          <label className="space-y-1">
            <span className="font-bold text-gray-300">Day</span>
            <select className={input} value={settings.weekday} onChange={(e) => setSettings({ ...settings, weekday: Number(e.target.value) })}>
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="font-bold text-gray-300">Hour (UTC)</span>
            <select className={input} value={settings.hour_utc} onChange={(e) => setSettings({ ...settings, hour_utc: Number(e.target.value) })}>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {String(h).padStart(2, "0")}:00
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="font-bold text-gray-300">Keep the newest</span>
            <input
              type="number"
              min={1}
              max={30}
              className={input}
              value={settings.keep}
              onChange={(e) => setSettings({ ...settings, keep: Math.max(1, Math.min(30, Number(e.target.value) || 1)) })}
            />
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={settings.include_images}
              onChange={(e) => setSettings({ ...settings, include_images: e.target.checked })}
            />
            Include pictures
          </label>
        </div>
        <p className="text-[10px] text-[#8b93a3]">
          Older backups are deleted after a new one is made (here and in the storage). Safety copies and uploaded files
          are kept until you delete them. Pictures make backups as big as your picture folder; leave them out if the
          disk is small.
        </p>
        <button
          type="button"
          className={primary}
          onClick={() =>
            act(
              () =>
                api.put("/admin/backups/settings", {
                  schedule_enabled: settings.schedule_enabled,
                  weekday: settings.weekday,
                  hour_utc: settings.hour_utc,
                  keep: settings.keep,
                  include_images: settings.include_images,
                }),
              "Schedule saved."
            )
          }
        >
          Save schedule
        </button>
      </section>

      {/* Password */}
      <section className={card}>
        <h2 className="text-sm font-bold text-white flex items-center gap-2">
          Backup password {data.settings.encrypted ? <Badge tone="green">On</Badge> : <Badge tone="amber">Off</Badge>}
        </h2>
        <p className="text-[#8b93a3]">
          Encrypts every new backup. <b className="text-amber-300">Write it down somewhere off this server</b>: a backup
          can&apos;t be restored without it, on this server or a new one.
        </p>
        <div className="flex flex-wrap gap-2">
          <input
            type="password"
            className={`${input} max-w-xs`}
            placeholder="At least 10 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
          <button
            type="button"
            className={primary}
            disabled={password.length < 10}
            onClick={() =>
              act(() => api.put("/admin/backups/password", { password }), "Backup password saved.").then(() => setPassword(""))
            }
          >
            {data.settings.encrypted ? "Change" : "Set password"}
          </button>
          {data.settings.encrypted && (
            <button
              type="button"
              className={danger}
              onClick={() =>
                window.confirm("Stop encrypting new backups?") &&
                act(() => api.del("/admin/backups/password"), "New backups will not be encrypted.")
              }
            >
              Remove
            </button>
          )}
        </div>
      </section>

      {/* Storage */}
      <section className={card}>
        <h2 className="text-sm font-bold text-white flex items-center gap-2">
          Connected storage {storage.connected ? <Badge tone="blue">Connected</Badge> : <Badge>Not connected</Badge>}
        </h2>
        <p className="text-[#8b93a3]">
          Any S3-compatible storage: Cloudflare R2, Backblaze B2, Wasabi, or MinIO on another server. Every new backup is
          copied there. Like plugging in a USB drive: connect, and disconnect whenever you want (files already there
          stay).
        </p>
        {storage.connected && (
          <div className="flex flex-wrap items-center gap-2 p-3 rounded-xl bg-[#101216] border border-[#262a33]">
            <span className="font-mono">
              {storage.endpoint} / {storage.bucket}
              {storage.prefix ? `/${storage.prefix}` : ""}
            </span>
            <span className="ml-auto flex gap-2">
              <button
                type="button"
                className={ghost}
                onClick={() =>
                  act(async () => setRemote((await api.get("/admin/backups/remote")).backups))
                }
              >
                Show files in storage
              </button>
              <button
                type="button"
                className={danger}
                onClick={() =>
                  window.confirm("Disconnect this storage? Backups already there stay there.") &&
                  act(() => api.del("/admin/backups/storage"), "Storage disconnected.")
                }
              >
                Disconnect
              </button>
            </span>
          </div>
        )}
        {remote && (
          <ul className="divide-y divide-[#262a33]">
            {remote.length === 0 && <li className="py-2 text-[#8b93a3]">No backups in the storage yet.</li>}
            {remote.map((r) => (
              <li key={r.key} className="py-2 flex items-center gap-3">
                <span className="font-mono flex-1 break-all">{r.name}</span>
                <span className="text-[#8b93a3]">{formatBytes(r.size)}</span>
                <button
                  type="button"
                  className={ghost}
                  disabled={busyJob || backups.some((b) => b.name === r.name)}
                  onClick={() => act(() => api.post("/admin/backups/remote/fetch", { name: r.name }), "Downloading to this server…")}
                >
                  {backups.some((b) => b.name === r.name) ? "On this server" : "Bring to this server"}
                </button>
              </li>
            ))}
          </ul>
        )}
        <StorageForm storage={storage} onSaved={setData} />
      </section>

      {restoring && (
        <RestoreDialog
          backup={restoring}
          onClose={() => setRestoring(null)}
          onDone={() => {
            setRestoring(null);
            setNotice({ ok: true, text: "Restore started. Don't change anything on the site until it finishes." });
            load();
          }}
        />
      )}
    </div>
  );
}
