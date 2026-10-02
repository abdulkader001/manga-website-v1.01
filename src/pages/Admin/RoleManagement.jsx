import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../../services/api";
import useAuth from "../../hooks/useAuth";
import { maskEmail } from "../../utils/maskEmail";

// Three roles: the main admin (everything), sub-admins (adjustable powers,
// managed here), and users (no admin powers, not adjustable).

const label = (key) => String(key).replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export default function RoleManagement() {
  const { isAdmin: isMainAdmin } = useAuth();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState(null);
  const [email, setEmail] = useState("");
  const [showEmails, setShowEmails] = useState(false);
  const [notice, setNotice] = useState(null);

  const flash = (ok, message) => {
    setNotice({ ok, message });
    if (ok) setTimeout(() => setNotice(null), 3000);
  };

  const { data: usersData } = useQuery({
    queryKey: ["adminUsersDirectory"],
    queryFn: () => api.admin.users(),
    enabled: isMainAdmin,
  });
  const subAdmins = useMemo(() => {
    const list = Array.isArray(usersData) ? usersData : usersData?.items || [];
    return list.filter((u) => u.role === "secondary_admin" || u.is_secondary_admin);
  }, [usersData]);

  useEffect(() => {
    if (subAdmins.length && !subAdmins.some((u) => u.id === selectedId)) setSelectedId(subAdmins[0].id);
    if (!subAdmins.length) setSelectedId(null);
  }, [subAdmins, selectedId]);

  const { data: catalogueData } = useQuery({
    queryKey: ["permissionsCatalogue"],
    queryFn: () => api.admin.permissions.catalogue(),
    enabled: isMainAdmin,
  });
  const { data: presetsData } = useQuery({
    queryKey: ["permissionPresets"],
    queryFn: () => api.admin.permissions.presets(),
    enabled: isMainAdmin,
  });
  const { data: effectiveData, isLoading: loadingEffective } = useQuery({
    queryKey: ["userPermissions", selectedId],
    queryFn: () => api.admin.permissions.effective(selectedId),
    enabled: isMainAdmin && Boolean(selectedId),
  });

  const groups = useMemo(() => {
    const byKey = new Map((effectiveData?.permissions || []).map((p) => [p.key, p]));
    const map = new Map();
    for (const entry of catalogueData?.permissions || []) {
      // Main-admin-only powers (the Scraper AI) have no sub-admin toggle.
      if (entry.main_admin_only) continue;
      const group = entry.group || "General";
      if (!map.has(group)) map.set(group, []);
      map.get(group).push({ ...entry, ...(byKey.get(entry.key) || {}) });
    }
    return [...map.entries()];
  }, [catalogueData, effectiveData]);

  const refreshPerms = () => queryClient.invalidateQueries({ queryKey: ["userPermissions", selectedId] });
  const refreshUsers = () => queryClient.invalidateQueries({ queryKey: ["adminUsersDirectory"] });

  const toggle = useMutation({
    mutationFn: ({ key, next }) =>
      api.admin.permissions.setOverrides(selectedId, [{ permission: key, state: next ? "granted" : "revoked" }]),
    onSuccess: refreshPerms,
    onError: (e) => flash(false, e.message),
  });
  const applyPreset = useMutation({
    mutationFn: (preset) => api.admin.permissions.applyPreset(selectedId, preset.key),
    onSuccess: (_d, preset) => {
      refreshPerms();
      flash(true, `Applied "${preset.label}".`);
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

  if (!isMainAdmin) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6">
        <div className="bg-[#15171c] border border-red-500/40 p-8 rounded-2xl max-w-md text-center space-y-3">
          <div className="text-3xl">🔒</div>
          <h2 className="text-xl font-bold text-white">Main admin only</h2>
          <p className="text-xs text-gray-400">Only the main admin can appoint sub-admins and set their powers.</p>
          <Link to="/admin" className="inline-block mt-3 px-4 py-2 rounded-xl bg-[#00AEF0] text-white text-xs font-bold">
            ← Back to the admin hub
          </Link>
        </div>
      </div>
    );
  }

  const selected = subAdmins.find((u) => u.id === selectedId);
  const shownEmail = (u) => (showEmails ? u.email : maskEmail(u.email));
  const presets = presetsData?.presets || [];

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-6 text-gray-200">
      <div className="border-b border-[#262a33] pb-4">
        <Link to="/admin" className="text-xs text-[#00AEF0] hover:underline font-semibold">
          ← Admin hub
        </Link>
        <h1 className="text-2xl font-extrabold text-white mt-1">Roles &amp; sub-admin powers</h1>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px]">
          <div className="p-3 rounded-xl bg-[#101216] border border-amber-500/30">
            <b className="text-amber-300">Admin</b> — you. Every power, plus this page and the Secret Vault.
          </div>
          <div className="p-3 rounded-xl bg-[#101216] border border-purple-500/30">
            <b className="text-purple-300">Sub-admin</b> — staff. Powers below, adjustable per person.
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
              {subAdmins.map((u) => (
                <div
                  key={u.id}
                  className={`flex items-center justify-between gap-2 p-2 rounded-xl border cursor-pointer ${
                    u.id === selectedId ? "border-purple-500 bg-purple-600/15" : "border-[#262a33] bg-[#101216] hover:border-purple-500/50"
                  }`}
                  onClick={() => setSelectedId(u.id)}
                >
                  <span className="text-xs text-white font-semibold truncate">
                    {u.username || u.name || `#${u.id}`}{" "}
                    <span className="text-[10px] text-gray-400 font-mono">{shownEmail(u)}</span>
                  </span>
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
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {selected && (
        <div className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 space-y-5">
          <div className="flex items-center justify-between flex-wrap gap-2 border-b border-[#262a33] pb-3">
            <div>
              <h2 className="text-base font-bold text-white">Powers of {selected.username || selected.name || `#${selected.id}`}</h2>
              <p className="text-[11px] text-[#8b93a3]">Changes save immediately and apply on their next request.</p>
            </div>
            <button
              type="button"
              disabled={reset.isPending}
              onClick={() => reset.mutate()}
              className="px-3 py-1.5 rounded-xl border border-[#262a33] text-xs text-gray-300 hover:text-white disabled:opacity-50"
            >
              Reset to defaults
            </button>
          </div>

          {presets.length > 0 && (
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
              <div key={group} className="space-y-2">
                <h3 className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">{group}</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {perms.map((perm) => (
                    <div
                      key={perm.key}
                      className="flex items-center justify-between gap-3 p-3 rounded-xl bg-[#101216] border border-[#262a33]"
                    >
                      <span className="text-xs text-white">
                        {label(perm.key)}
                        {perm.state && perm.state !== "inherited" && (
                          <span className="ml-2 text-[9px] font-bold text-amber-300 uppercase">changed</span>
                        )}
                      </span>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={Boolean(perm.effective)}
                        disabled={toggle.isPending}
                        onClick={() => toggle.mutate({ key: perm.key, next: !perm.effective })}
                        className={`shrink-0 w-10 h-6 rounded-full p-0.5 transition ${perm.effective ? "bg-[#00AEF0]" : "bg-[#262a33]"}`}
                      >
                        <span
                          className={`block w-5 h-5 rounded-full bg-white shadow transition-transform ${perm.effective ? "translate-x-4" : ""}`}
                        ></span>
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
