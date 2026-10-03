import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../../services/api";
import useStaffPermissions from "../../hooks/useStaffPermissions";
import TabAccessPanel from "./TabAccessPanel";
import { maskEmail } from "../../utils/maskEmail";
import { CodeForm } from "../../components/AdminSecondFactor";

// Four roles: the owner (everything, never touched by anyone), Admins (at most
// two; almost everything, switched by the owner), sub-admins (adjustable powers,
// managed by an Admin or the owner) and users (no admin powers). Only the owner
// makes Admins, shares the sub-admin seats, and sets the ceiling on what a
// sub-admin may hold; each Admin keeps a succession line of up to two sub-admins.

const label = (key) => String(key).replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const MAX_ADMINS = 2;
const personName = (p) => p.name || `#${p.user_id}`;

function Badge({ tone, children }) {
  const tones = {
    gold: "border-amber-500/40 bg-amber-500/10 text-amber-300",
    red: "border-red-500/40 bg-red-500/10 text-red-300",
    gray: "border-[#262a33] bg-[#101216] text-[#8b93a3]",
  };
  return <span className={`px-1.5 py-0.5 rounded-md border text-[9px] font-bold uppercase ${tones[tone]}`}>{children}</span>;
}

function CodeDialog({ title, text, onSubmit, onClose, busy, error }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="max-w-sm w-full bg-[#101216] border border-amber-500/40 rounded-2xl p-5 space-y-3 text-gray-200">
        <h3 className="text-sm font-bold text-white">{title}</h3>
        <p className="text-xs text-[#8b93a3]">{text}</p>
        <CodeForm onSubmit={onSubmit} label="Code from your authenticator app" busy={busy} error={error} />
        <button type="button" onClick={onClose} className="text-xs text-gray-400 hover:text-white">
          Cancel
        </button>
      </div>
    </div>
  );
}

function SuccessionPanel({ flash }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["succession"], queryFn: () => api.admin.permissions.succession() });
  const [enabled, setEnabled] = useState(false);
  const [days, setDays] = useState(60);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (data) {
      setEnabled(data.enabled);
      setDays(data.inactive_days);
    }
  }, [data]);
  const save = useMutation({
    mutationFn: (code) => api.admin.permissions.saveSuccession({ enabled, inactive_days: days, code }),
    onSuccess: (res) => {
      queryClient.setQueryData(["succession"], res);
      setAsking(false);
      setError("");
      flash(true, res.enabled ? "Automatic succession is on." : "Automatic succession is off.");
    },
    onError: (e) => setError(e.message),
  });
  if (!data) return null;
  return (
    <div className="bg-[#15171c] border border-amber-500/30 rounded-2xl p-5 space-y-4 text-xs">
      <div>
        <h2 className="text-base font-bold text-white">Automatic succession</h2>
        <p className="text-[11px] text-[#8b93a3]">
          Only you can switch this on. An Admin idle for longer than the days below becomes a user, and the first
          eligible sub-admin in their succession line (still a sub-admin, active, with an authenticator) takes the seat
          exactly as it was: your restrictions, their seats and the sub-admins they appointed. Switching it on never
          demotes anyone straight away: the idle clock starts then. Every change is logged and sent to you. You can also
          hand a seat over at any time, below.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex items-center gap-2 font-bold text-white">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          On
        </label>
        <label className="space-y-1">
          <span className="block text-gray-300 font-bold">Idle for more than (days)</span>
          <input
            type="number"
            min={30}
            max={365}
            value={days}
            onChange={(e) => setDays(Math.max(30, Math.min(365, Number(e.target.value) || 60)))}
            className="w-24 px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-white"
          />
        </label>
        <button type="button" onClick={() => setAsking(true)} className="px-4 py-2 rounded-xl bg-amber-500 text-black font-bold">
          Save
        </button>
      </div>
      {asking && (
        <CodeDialog
          title="Confirm with your code"
          text="Changing automatic succession needs the code from your authenticator app."
          onSubmit={(code) => save.mutate(code)}
          onClose={() => setAsking(false)}
          busy={save.isPending}
          error={error}
        />
      )}
    </div>
  );
}

// An Admin's seat: the owner sees both Admins and runs them; an Admin sees only
// their own seat and keeps their own succession line.
function AdminsPanel({ isOwner, flash }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["roleAdmins"], queryFn: () => api.admin.roles.admins() });
  const [asking, setAsking] = useState(null); // { title, text, run }
  const [error, setError] = useState("");
  const [pick, setPick] = useState("");
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["roleAdmins"] });
    queryClient.invalidateQueries({ queryKey: ["managedPeople"] });
    queryClient.invalidateQueries({ queryKey: ["adminUsersDirectory"] });
    queryClient.invalidateQueries({ queryKey: ["succession"] });
  };
  const done = (message) => () => {
    setAsking(null);
    setError("");
    refresh();
    flash(true, message);
  };
  const fail = (e) => (asking ? setError(e.message) : flash(false, e.message));

  const make = useMutation({
    mutationFn: ({ id, code }) => api.admin.roles.makeAdmin(id, code),
    onSuccess: done("Admin appointed. They start with the Admin defaults; adjust them below."),
    onError: fail,
  });
  const handOver = useMutation({
    mutationFn: ({ id, successorId, code }) => api.admin.roles.handOver(id, successorId, code),
    onSuccess: done("Seat handed over."),
    onError: fail,
  });
  const removeAdmin = useMutation({
    mutationFn: ({ id, to }) => api.admin.roles.removeAdmin(id, to),
    onSuccess: done("Admin seat taken away."),
    onError: (e) => flash(false, e.message),
  });
  const quota = useMutation({
    mutationFn: ({ id, value }) => api.admin.roles.setQuota(id, value),
    onSuccess: done("Seats saved."),
    onError: (e) => flash(false, e.message),
  });
  const line = useMutation({
    mutationFn: ({ id, ids }) => api.admin.roles.setSuccessors(id, ids),
    onSuccess: done("Succession line saved."),
    onError: (e) => flash(false, e.message),
  });

  if (!data) return null;
  const subs = data.sub_admins || [];
  const free = subs.filter((p) => !data.admins.some((a) => a.user_id === p.user_id));
  const setSlot = (admin, index, value) => {
    const ids = admin.line.map((p) => p.user_id);
    if (value) ids[index] = Number(value);
    else ids.splice(index, 1);
    line.mutate({ id: admin.user_id, ids: [...new Set(ids.filter(Boolean))].slice(0, 2) });
  };

  return (
    <div className="bg-[#15171c] border border-purple-500/30 rounded-2xl p-5 space-y-4 text-xs">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-base font-bold text-white">
            {isOwner ? `Admins (${data.admins.length}/${data.max_admins})` : "Your Admin seat"}
          </h2>
          <p className="text-[11px] text-[#8b93a3]">
            {isOwner
              ? `Admins hold almost everything except Admin Settings, the cache and "delete all manga" until you switch them on. ` +
                `They change sub-admins and users only. The Admins share ${data.pool} sub-admin seats (${data.pool_used} given out).`
              : "Name up to two sub-admins, in order, to take your seat if you are idle too long. They inherit it as it is."}
          </p>
        </div>
      </div>

      {data.admins.length === 0 && <p className="text-[#8b93a3]">There are no Admins yet.</p>}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {data.admins.map((a) => (
          <div key={a.user_id} className="p-3 rounded-xl bg-[#101216] border border-[#262a33] space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-white font-bold">{personName(a)}</span>
              {!a.authenticator && <Badge tone="red">No authenticator</Badge>}
            </div>
            <div className="text-[10px] text-[#8b93a3]">
              Last active {a.last_active || "never"}
              {a.idle_days != null && ` · idle ${a.idle_days} days`}
              {a.days_left != null && ` · ${Math.max(0, a.days_left)} days before replacement`}
              {" · "}
              Seats {a.used}/{a.quota} used
            </div>

            <div className="space-y-1">
              <div className="font-bold text-gray-300">Succession line</div>
              {[0, 1].map((i) => {
                const current = a.line[i];
                return (
                  <label key={i} className="flex items-center gap-2">
                    <span className="w-4 text-gray-400">{i + 1}.</span>
                    <select
                      aria-label={`Successor ${i + 1} of ${personName(a)}`}
                      disabled={line.isPending || (i > 0 && !a.line[i - 1])}
                      value={current?.user_id || ""}
                      onChange={(e) => setSlot(a, i, e.target.value)}
                      className="flex-1 px-2 py-1.5 rounded-lg bg-[#15171c] border border-[#262a33] text-white"
                    >
                      <option value="">— nobody —</option>
                      {subs
                        .filter((p) => p.user_id === current?.user_id || !a.line.some((l) => l.user_id === p.user_id))
                        .map((p) => (
                          <option key={p.user_id} value={p.user_id}>
                            {personName(p)}
                            {p.blocked_by.length ? ` (${p.blocked_by.join(", ")})` : ""}
                          </option>
                        ))}
                    </select>
                    {current && current.blocked_by.length > 0 && <Badge tone="gray">can't serve yet</Badge>}
                  </label>
                );
              })}
            </div>

            {isOwner && (
              <div className="flex flex-wrap items-end gap-2 pt-1">
                <label className="space-y-1">
                  <span className="block text-gray-300 font-bold">Seats for sub-admins</span>
                  <input
                    type="number"
                    min={0}
                    max={data.pool}
                    defaultValue={a.quota}
                    key={`${a.user_id}-${a.quota}`}
                    onBlur={(e) => {
                      const value = Number(e.target.value);
                      if (value !== a.quota) quota.mutate({ id: a.user_id, value });
                    }}
                    className="w-20 px-2 py-1.5 rounded-lg bg-[#15171c] border border-[#262a33] text-white"
                  />
                </label>
                <button
                  type="button"
                  onClick={() =>
                    setAsking({
                      title: `Hand over ${personName(a)}'s seat`,
                      text: "The first eligible person in their line takes the seat now; the Admin becomes a user. With nobody eligible in the line, appoint a new Admin instead.",
                      run: (code) => handOver.mutate({ id: a.user_id, code }),
                    })
                  }
                  className="px-3 py-1.5 rounded-lg border border-amber-500/40 text-amber-300 hover:bg-amber-500/10 font-bold"
                >
                  Hand seat over now
                </button>
                {["sub_admin", "user"].map((to) => (
                  <button
                    key={to}
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Take ${personName(a)}'s Admin seat and make them a ${to === "user" ? "user" : "sub-admin"}?`))
                        removeAdmin.mutate({ id: a.user_id, to });
                    }}
                    className="px-3 py-1.5 rounded-lg border border-red-500/40 text-red-300 hover:bg-red-500/10 font-bold"
                  >
                    {to === "user" ? "Demote to user" : "Demote to sub-admin"}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {isOwner && data.admins.length < data.max_admins && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="space-y-1">
            <span className="block text-gray-300 font-bold">Make a sub-admin an Admin</span>
            <select
              aria-label="Sub-admin to make an Admin"
              value={pick}
              onChange={(e) => setPick(e.target.value)}
              className="px-2 py-1.5 rounded-lg bg-[#101216] border border-[#262a33] text-white"
            >
              <option value="">Choose a sub-admin…</option>
              {free.map((p) => (
                <option key={p.user_id} value={p.user_id} disabled={!p.blocked_by.every((r) => r !== "no authenticator")}>
                  {personName(p)}
                  {p.blocked_by.includes("no authenticator") ? " (no authenticator)" : ""}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!pick}
            onClick={() =>
              setAsking({
                title: "Make an Admin",
                text: "Giving the Admin seat needs the code from your authenticator app.",
                run: (code) => make.mutate({ id: Number(pick), code }),
              })
            }
            className="px-4 py-1.5 rounded-lg bg-purple-600 text-white font-bold disabled:opacity-40"
          >
            Make Admin
          </button>
        </div>
      )}

      {asking && (
        <CodeDialog
          title={asking.title}
          text={asking.text}
          onSubmit={asking.run}
          onClose={() => {
            setAsking(null);
            setError("");
          }}
          busy={make.isPending || handOver.isPending}
          error={error}
        />
      )}
    </div>
  );
}

// The owner's ceiling: powers no sub-admin can hold, whatever an Admin tries.
function LimitsPanel({ flash, catalogue }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["subAdminLimits"], queryFn: () => api.admin.roles.limits() });
  const [blocked, setBlocked] = useState([]);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (data) setBlocked(data.blocked);
  }, [data]);
  const save = useMutation({
    mutationFn: (code) => api.admin.roles.saveLimits(blocked, code),
    onSuccess: (res) => {
      queryClient.setQueryData(["subAdminLimits"], res);
      queryClient.invalidateQueries({ queryKey: ["userPermissions"] });
      setAsking(false);
      setError("");
      flash(true, "Ceiling saved.");
    },
    onError: (e) => setError(e.message),
  });
  if (!data) return null;
  const everyday = (catalogue?.permissions || []).filter((p) => !p.owner_power);
  const flip = (key) => setBlocked((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]));
  return (
    <div className="bg-[#15171c] border border-amber-500/30 rounded-2xl p-5 space-y-3 text-xs">
      <div>
        <h2 className="text-base font-bold text-white">What sub-admins may hold</h2>
        <p className="text-[11px] text-[#8b93a3]">
          Tick a power to take it out of every sub-admin's reach: an Admin can't give it, and any sub-admin who has it
          loses it until you untick it. Site-owner powers are always out of reach.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
        {everyday.map((p) => (
          <label key={p.key} className="flex items-center gap-2 p-2 rounded-lg bg-[#101216] border border-[#262a33]" title={p.description}>
            <input type="checkbox" checked={blocked.includes(p.key)} onChange={() => flip(p.key)} />
            <span className="text-white">{label(p.key)}</span>
          </label>
        ))}
      </div>
      <button type="button" onClick={() => setAsking(true)} className="px-4 py-2 rounded-xl bg-amber-500 text-black font-bold">
        Save ceiling
      </button>
      {asking && (
        <CodeDialog
          title="Confirm with your code"
          text="Changing what sub-admins may hold needs the code from your authenticator app."
          onSubmit={(code) => save.mutate(code)}
          onClose={() => setAsking(false)}
          busy={save.isPending}
          error={error}
        />
      )}
    </div>
  );
}

export default function RoleManagement() {
  const { isMainAdmin, isAdminTier, can, isLoading: loadingMine } = useStaffPermissions();
  const allowed = isMainAdmin || can("manage_roles");
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState(null);
  const [email, setEmail] = useState("");
  const [showEmails, setShowEmails] = useState(false);
  const [notice, setNotice] = useState(null);
  const [pendingGrant, setPendingGrant] = useState(null);
  const [codeError, setCodeError] = useState("");

  const flash = (ok, message) => {
    setNotice({ ok, message });
    if (ok) setTimeout(() => setNotice(null), 3000);
  };

  const { data: usersData } = useQuery({
    queryKey: ["adminUsersDirectory"],
    queryFn: () => api.admin.users(),
    enabled: allowed,
  });
  const { data: managedData } = useQuery({
    queryKey: ["managedPeople"],
    queryFn: () => api.admin.permissions.managed(),
    enabled: allowed,
  });
  const { data: mine } = useQuery({
    queryKey: ["staffPermissions"],
    queryFn: () => api.admin.permissions.mine(),
    enabled: allowed && !isMainAdmin,
  });
  const managed = useMemo(
    () => new Map((managedData?.people || []).map((p) => [p.user_id, p])),
    [managedData]
  );
  // The owner manages Admins and sub-admins; an Admin manages sub-admins only.
  const subAdmins = useMemo(() => {
    const list = Array.isArray(usersData) ? usersData : usersData?.items || [];
    return list.filter((u) => {
      if (u.role === "co_admin") return isMainAdmin;
      return u.role === "secondary_admin" || (u.is_secondary_admin && u.role !== "permanent_admin" && u.role !== "admin");
    });
  }, [usersData, isMainAdmin]);

  const selectedIsAdmin = subAdmins.find((u) => u.id === selectedId)?.role === "co_admin";

  useEffect(() => {
    if (subAdmins.length && !subAdmins.some((u) => u.id === selectedId)) setSelectedId(subAdmins[0].id);
    if (!subAdmins.length) setSelectedId(null);
  }, [subAdmins, selectedId]);

  const { data: catalogueData } = useQuery({
    queryKey: ["permissionsCatalogue"],
    queryFn: () => api.admin.permissions.catalogue(),
    enabled: allowed,
  });
  const { data: presetsData } = useQuery({
    queryKey: ["permissionPresets"],
    queryFn: () => api.admin.permissions.presets(),
    enabled: allowed,
  });
  const { data: effectiveData, isLoading: loadingEffective } = useQuery({
    queryKey: ["userPermissions", selectedId],
    queryFn: () => api.admin.permissions.effective(selectedId),
    enabled: allowed && Boolean(selectedId),
  });

  const groups = useMemo(() => {
    const byKey = new Map((effectiveData?.permissions || []).map((p) => [p.key, p]));
    const map = new Map();
    for (const entry of catalogueData?.permissions || []) {
      const group = entry.owner_power ? "Site owner powers" : entry.group || "General";
      if (!map.has(group)) map.set(group, []);
      map.get(group).push({ ...entry, ...(byKey.get(entry.key) || {}) });
    }
    // Site-owner powers last, set apart.
    return [...map.entries()].sort(([a], [b]) => (a === "Site owner powers") - (b === "Site owner powers"));
  }, [catalogueData, effectiveData]);

  const refreshPerms = () => {
    queryClient.invalidateQueries({ queryKey: ["userPermissions", selectedId] });
    queryClient.invalidateQueries({ queryKey: ["managedPeople"] });
    queryClient.invalidateQueries({ queryKey: ["succession"] });
  };
  const refreshUsers = () => {
    queryClient.invalidateQueries({ queryKey: ["adminUsersDirectory"] });
    queryClient.invalidateQueries({ queryKey: ["managedPeople"] });
  };

  const toggle = useMutation({
    mutationFn: ({ key, next, ownerPower, code }) =>
      api.admin.permissions.setOverrides(
        selectedId,
        // An Admin's toggles are real on/off switches; a sub-admin never holds a site-owner power.
        [{ permission: key, state: next ? "granted" : ownerPower && !selectedIsAdmin ? "inherited" : "revoked" }],
        code
      ),
    onSuccess: () => {
      refreshPerms();
      setPendingGrant(null);
      setCodeError("");
    },
    onError: (e, vars) => {
      if (vars.code) setCodeError(e.message);
      else flash(false, e.message);
    },
  });
  const applyPreset = useMutation({
    mutationFn: (preset) => api.admin.permissions.applyPreset(selectedId, preset.key),
    onSuccess: (_d, preset) => {
      refreshPerms();
      flash(true, `Applied "${preset.label}". Site-owner powers were left as they were.`);
    },
    onError: (e) => flash(false, e.message),
  });
  const reset = useMutation({
    mutationFn: () => api.admin.permissions.reset(selectedId),
    onSuccess: () => {
      refreshPerms();
      flash(true, "Back to the sub-admin defaults.");
    },
    onError: (e) => flash(false, e.message),
  });
  const appoint = useMutation({
    mutationFn: (value) => api.admin.promoteSecondaryByEmail(value),
    onSuccess: (res) => {
      setEmail("");
      refreshUsers();
      if (res?.user?.id) setSelectedId(res.user.id);
      flash(true, "Sub-admin appointed.");
    },
    onError: (e) => flash(false, e.message),
  });
  const remove = useMutation({
    mutationFn: (userId) => api.admin.demoteSecondary({ user_id: userId }),
    onSuccess: () => {
      refreshUsers();
      flash(true, "Sub-admin removed; they are a regular user again.");
    },
    onError: (e) => flash(false, e.message),
  });

  if (loadingMine) {
    return <div className="min-h-[50vh] flex items-center justify-center text-xs text-[#8b93a3]">Loading…</div>;
  }
  if (!allowed) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6">
        <div className="bg-[#15171c] border border-red-500/40 p-8 rounded-2xl max-w-md text-center space-y-3">
          <div className="text-3xl">🔒</div>
          <h2 className="text-xl font-bold text-white">Not available</h2>
          <p className="text-xs text-gray-400">Role Management is for the site owner, or an Admin the owner allows.</p>
          <Link to="/admin" className="inline-block mt-3 px-4 py-2 rounded-xl bg-[#00AEF0] text-white text-xs font-bold">
            ← Back to the admin hub
          </Link>
        </div>
      </div>
    );
  }

  const myId = mine?.user_id;
  const selected = subAdmins.find((u) => u.id === selectedId);
  const selectedInfo = selected ? managed.get(selected.id) : null;
  // Nobody changes their own powers, and only the owner changes an Admin's (the server refuses too).
  const lockedForMe = !isMainAdmin && selected && selected.id === myId;
  const shownEmail = (u) => (showEmails ? u.email : maskEmail(u.email));
  const presets = presetsData?.presets || [];

  const onToggle = (perm) => {
    const next = !perm.effective;
    if (perm.owner_power && next) {
      setCodeError("");
      setPendingGrant(perm);
      return;
    }
    toggle.mutate({ key: perm.key, next, ownerPower: perm.owner_power });
  };

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-6 text-gray-200">
      <div className="border-b border-[#262a33] pb-4">
        <Link to="/admin" className="text-xs text-[#00AEF0] hover:underline font-semibold">
          ← Admin hub
        </Link>
        <h1 className="text-2xl font-extrabold text-white mt-1">Roles &amp; powers</h1>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-4 gap-2 text-[11px]">
          <div className="p-3 rounded-xl bg-[#101216] border border-amber-500/30">
            <b className="text-amber-300">Owner</b> — everything. Never changed or touched by anyone.
          </div>
          <div className="p-3 rounded-xl bg-[#101216] border border-blue-500/30">
            <b className="text-blue-300">Admin</b> — up to {MAX_ADMINS}. Almost everything; the owner switches powers.
            Changes sub-admins and users only.
          </div>
          <div className="p-3 rounded-xl bg-[#101216] border border-purple-500/30">
            <b className="text-purple-300">Sub-admin</b> — staff, as many as the seats allow. Changes users only.
          </div>
          <div className="p-3 rounded-xl bg-[#101216] border border-[#262a33]">
            <b className="text-white">User</b> — readers. No admin powers.
          </div>
        </div>
      </div>

      {notice && (
        <div
          className={`p-3 rounded-xl border text-xs flex items-center justify-between ${
            notice.ok ? "bg-emerald-950/40 border-emerald-500/40 text-emerald-300" : "bg-red-950/40 border-red-500/40 text-red-300"
          }`}
        >
          <span>{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-gray-400 hover:text-white" aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {(isMainAdmin || can("promote_secondary")) && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (email.trim()) appoint.mutate(email.trim());
            }}
            className="bg-[#15171c] border border-[#262a33] p-4 rounded-2xl space-y-2"
          >
            <div className="text-white font-bold text-xs">Appoint a sub-admin</div>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="their account email"
              className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
            />
            <button
              type="submit"
              disabled={appoint.isPending}
              className="w-full py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs disabled:opacity-50"
            >
              {appoint.isPending ? "Appointing…" : "Make sub-admin"}
            </button>
            <p className="text-[10px] text-[#8b93a3]">The person must already have an account.</p>
          </form>
        )}

        <div className="bg-[#15171c] border border-[#262a33] p-4 rounded-2xl space-y-2 md:col-span-2">
          <div className="flex items-center justify-between">
            <span className="text-white font-bold text-xs">{isMainAdmin ? "Admins & sub-admins" : "Sub-admins"} ({subAdmins.length})</span>
            <button
              type="button"
              onClick={() => setShowEmails(!showEmails)}
              className="text-[10px] font-bold text-purple-300 hover:text-white"
            >
              {showEmails ? "Hide emails" : "Show emails"}
            </button>
          </div>
          {subAdmins.length === 0 ? (
            <p className="text-[11px] text-[#8b93a3]">No sub-admins yet.</p>
          ) : (
            <div className="space-y-1.5">
              {subAdmins.map((u) => {
                const info = managed.get(u.id);
                const isAdminRow = u.role === "co_admin";
                const protectedRow = isAdminRow || u.id === myId;
                return (
                  <div
                    key={u.id}
                    className={`flex items-center justify-between gap-2 p-2 rounded-xl border cursor-pointer ${
                      u.id === selectedId ? "border-purple-500 bg-purple-600/15" : "border-[#262a33] bg-[#101216] hover:border-purple-500/50"
                    }`}
                    onClick={() => setSelectedId(u.id)}
                  >
                    <span className="text-xs text-white font-semibold truncate flex items-center gap-1.5">
                      {u.username || u.name || `#${u.id}`}
                      {isAdminRow && <Badge tone="gold">Admin</Badge>}
                      {info && !info.authenticator && <Badge tone="gray">No authenticator</Badge>}
                      <span className="text-[10px] text-gray-400 font-mono">{shownEmail(u)}</span>
                    </span>
                    {(isMainAdmin || can("demote_secondary")) && !protectedRow && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (window.confirm(`Remove ${u.username || u.name || "this person"} as sub-admin?`)) remove.mutate(u.id);
                        }}
                        className="px-2 py-1 rounded-lg border border-red-500/40 text-red-300 hover:bg-red-500/10 text-[10px] font-bold"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {selected && (
        <div className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 space-y-5">
          <div className="flex items-center justify-between flex-wrap gap-2 border-b border-[#262a33] pb-3">
            <div>
              <h2 className="text-base font-bold text-white">Powers of {selected.username || selected.name || `#${selected.id}`}</h2>
              <p className="text-[11px] text-[#8b93a3]">
                {lockedForMe
                  ? "Nobody changes their own powers."
                  : "Changes save immediately and apply on their next request."}
              </p>
            </div>
            {!lockedForMe && (
              <button
                type="button"
                disabled={reset.isPending}
                onClick={() => reset.mutate()}
                className="px-3 py-1.5 rounded-xl border border-[#262a33] text-xs text-gray-300 hover:text-white disabled:opacity-50"
              >
                Reset to defaults
              </button>
            )}
          </div>

          {presets.length > 0 && !lockedForMe && (
            <div className="space-y-2">
              <span className="text-xs font-bold text-gray-300">Quick presets</span>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {presets.map((p) => (
                  <button
                    key={p.key}
                    type="button"
                    disabled={applyPreset.isPending}
                    onClick={() => applyPreset.mutate(p)}
                    className="p-3 rounded-xl border border-[#262a33] bg-[#101216] text-left hover:border-[#00AEF0] transition disabled:opacity-50"
                  >
                    <span className="block text-xs font-bold text-white">{p.label}</span>
                    <span className="block text-[10px] text-[#8b93a3]">{p.description}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {loadingEffective ? (
            <p className="text-xs text-[#8b93a3]">Loading…</p>
          ) : (
            groups.map(([group, perms]) => (
              <div key={group} className={`space-y-2 ${group === "Site owner powers" ? "p-3 rounded-2xl border border-amber-500/30" : ""}`}>
                <h3 className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">
                  {group === "Site owner powers" ? "🔒 Site owner powers" : group}
                </h3>
                {group === "Site owner powers" && (
                  <p className="text-[10px] text-[#8b93a3]">
                    Only you switch these for an Admin; switching one on needs your authenticator code. An Admin needs an
                    authenticator and enters a code to use them. A sub-admin can never hold one.
                  </p>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {perms.map((perm) => {
                    const paused =
                      selectedIsAdmin && perm.owner_power && !perm.effective && perm.state !== "revoked" && (perm.state === "granted" || perm.role_default);
                    const on = Boolean(perm.effective) || paused;
                    const blockedByOwner = perm.state === "blocked";
                    const disabled =
                      toggle.isPending ||
                      lockedForMe ||
                      blockedByOwner ||
                      (selectedIsAdmin && !isMainAdmin) ||
                      (perm.owner_power && (!isMainAdmin || !selectedIsAdmin));
                    return (
                      <div
                        key={perm.key}
                        className="flex items-center justify-between gap-3 p-3 rounded-xl bg-[#101216] border border-[#262a33]"
                        title={perm.description}
                      >
                        <span className="text-xs text-white">
                          {label(perm.key)}
                          {blockedByOwner && <span className="ml-2 text-[9px] font-bold text-red-300 uppercase">blocked by owner</span>}
                          {perm.state && perm.state !== "inherited" && perm.state !== "blocked" && !(perm.owner_power && !selectedIsAdmin) && (
                            <span className="ml-2 text-[9px] font-bold text-amber-300 uppercase">changed</span>
                          )}
                          {paused && <span className="ml-2 text-[9px] font-bold text-red-300 uppercase">paused: no authenticator</span>}
                        </span>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={on}
                          aria-label={label(perm.key)}
                          disabled={disabled}
                          onClick={() => onToggle({ ...perm, effective: on })}
                          className={`shrink-0 w-10 h-6 rounded-full p-0.5 transition disabled:opacity-40 ${
                            on ? (perm.owner_power ? "bg-amber-500" : "bg-[#00AEF0]") : "bg-[#262a33]"
                          }`}
                        >
                          <span className={`block w-5 h-5 rounded-full bg-white shadow transition-transform ${on ? "translate-x-4" : ""}`}></span>
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {(isMainAdmin || isAdminTier) && <AdminsPanel isOwner={isMainAdmin} flash={flash} />}
      {isMainAdmin && <LimitsPanel flash={flash} catalogue={catalogueData} />}
      {isMainAdmin && <TabAccessPanel flash={flash} />}
      {isMainAdmin && <SuccessionPanel flash={flash} />}

      {pendingGrant && (
        <CodeDialog
          title={`Give "${label(pendingGrant.key)}"`}
          text={`${pendingGrant.description} This is a site-owner power: confirm with the code from your authenticator app.`}
          onSubmit={(code) => toggle.mutate({ key: pendingGrant.key, next: true, ownerPower: true, code })}
          onClose={() => setPendingGrant(null)}
          busy={toggle.isPending}
          error={codeError}
        />
      )}
    </div>
  );
}
