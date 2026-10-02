import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../../services/api";
import useStaffPermissions from "../../hooks/useStaffPermissions";
import { maskEmail } from "../../utils/maskEmail";
import { CodeForm } from "../../components/AdminSecondFactor";

// Three roles: the owner (everything), sub-admins (adjustable powers,
// managed here), and users (no admin powers). The owner can also hand
// site-owner powers to at most two sub-admins ("deputies"); only the owner
// gives or takes those, with their authenticator code.

const label = (key) => String(key).replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const MAX_DEPUTIES = 2;

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
  const rules = data.rules;
  return (
    <div className="bg-[#15171c] border border-amber-500/30 rounded-2xl p-5 space-y-4 text-xs">
      <div>
        <h2 className="text-base font-bold text-white">Automatic succession</h2>
        <p className="text-[11px] text-[#8b93a3]">
          Only you can switch this on. A deputy idle for longer than the days below becomes a user, and the most active
          eligible sub-admin receives exactly their site-owner powers. To be eligible a sub-admin must have been an
          admin for {rules.min_tenure_days}+ days, been active on {rules.min_active_days} of the last {rules.window_days}{" "}
          days, done admin work on {rules.min_work_days} of them, and have an authenticator. Switching it on never
          demotes anyone straight away: the idle clock starts then. Every change is logged and sent to you.
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
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <div className="font-bold text-gray-300">
            Deputies ({data.deputies.length}/{rules.max_deputies})
          </div>
          {data.deputies.length === 0 && <p className="text-[#8b93a3]">Nobody holds site-owner powers.</p>}
          {data.deputies.map((d) => (
            <div key={d.user_id} className="p-2 rounded-xl bg-[#101216] border border-[#262a33]">
              <div className="text-white font-semibold">{d.name || `#${d.user_id}`}</div>
              <div className="text-[10px] text-[#8b93a3]">
                Last active {d.last_active || "never"}
                {d.idle_days != null && ` · idle ${d.idle_days} days`}
                {d.days_left != null && ` · ${Math.max(0, d.days_left)} days before replacement`}
              </div>
            </div>
          ))}
        </div>
        <div className="space-y-1.5">
          <div className="font-bold text-gray-300">Next in line</div>
          {data.candidates.length === 0 && <p className="text-[#8b93a3]">No other sub-admins.</p>}
          {data.candidates.map((c, i) => (
            <div key={c.user_id} className="p-2 rounded-xl bg-[#101216] border border-[#262a33]">
              <div className="text-white font-semibold">
                {i + 1}. {c.name || `#${c.user_id}`}{" "}
                {c.blocked_by.length === 0 ? <Badge tone="gold">eligible</Badge> : <Badge tone="gray">not yet</Badge>}
              </div>
              <div className="text-[10px] text-[#8b93a3]">
                Active {c.active_days}/{rules.window_days} days · worked {c.work_days} days · admin for {c.admin_for_days} days
                {c.blocked_by.length > 0 && ` · ${c.blocked_by.join(", ")}`}
              </div>
            </div>
          ))}
        </div>
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

export default function RoleManagement() {
  const { isMainAdmin, can, isLoading: loadingMine } = useStaffPermissions();
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
  const subAdmins = useMemo(() => {
    const list = Array.isArray(usersData) ? usersData : usersData?.items || [];
    return list.filter((u) => u.role === "secondary_admin" || u.is_secondary_admin);
  }, [usersData]);
  const deputyCount = subAdmins.filter((u) => managed.get(u.id)?.deputy).length;

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
        [{ permission: key, state: next ? "granted" : ownerPower ? "inherited" : "revoked" }],
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
      flash(true, "Sub-admin removed; they are a regular user again (and lost any site-owner powers).");
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
          <p className="text-xs text-gray-400">Role Management is for the site owner, or a deputy they gave it to.</p>
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
  // A deputy can't change themselves or another deputy (the server refuses too).
  const lockedForMe = !isMainAdmin && selected && (selectedInfo?.deputy || selected.id === myId);
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
        <h1 className="text-2xl font-extrabold text-white mt-1">Roles &amp; sub-admin powers</h1>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px]">
          <div className="p-3 rounded-xl bg-[#101216] border border-amber-500/30">
            <b className="text-amber-300">Owner</b> — every power. Only the owner gives or takes site-owner powers.
          </div>
          <div className="p-3 rounded-xl bg-[#101216] border border-purple-500/30">
            <b className="text-purple-300">Sub-admin</b> — staff. Up to {MAX_DEPUTIES} can be deputies with site-owner
            powers ({deputyCount}/{MAX_DEPUTIES} now).
          </div>
          <div className="p-3 rounded-xl bg-[#101216] border border-[#262a33]">
            <b className="text-white">User</b> — readers. No admin powers; cannot be given any.
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
            <span className="text-white font-bold text-xs">Sub-admins ({subAdmins.length})</span>
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
                const protectedRow = !isMainAdmin && (info?.deputy || u.id === myId);
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
                      {info?.deputy && <Badge tone="gold">Deputy</Badge>}
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
                  ? "Only the site owner can change a deputy's powers (or your own)."
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
                    Only you give or take these, with your authenticator code. Up to {MAX_DEPUTIES} sub-admins can hold
                    them, they need an authenticator, and they enter a code to use them. A deputy can never pass them on.
                  </p>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {perms.map((perm) => {
                    const paused = perm.owner_power && perm.state === "granted" && !perm.effective;
                    const on = Boolean(perm.effective) || paused;
                    const disabled = toggle.isPending || lockedForMe || (perm.owner_power && !isMainAdmin);
                    return (
                      <div
                        key={perm.key}
                        className="flex items-center justify-between gap-3 p-3 rounded-xl bg-[#101216] border border-[#262a33]"
                        title={perm.description}
                      >
                        <span className="text-xs text-white">
                          {label(perm.key)}
                          {perm.state && perm.state !== "inherited" && !perm.owner_power && (
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
