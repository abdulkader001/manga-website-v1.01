import React, { useState, useMemo, useEffect } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { apiFetch } from "../../services/api";
import useAuth from "../../hooks/useAuth";
import { maskEmail } from "../../utils/maskEmail";

const PRESET_POWER_LEVELS = [
  {
    id: "full",
    title: "⚡ Full Power Sub-Admin",
    desc: "Grants all operational powers: Series, Scraper, Chapters, OCR, Community, Ads, and Cache.",
    color: "border-purple-500/40 bg-purple-500/10 text-purple-300",
    powers: {
      series_create: true,
      series_edit: true,
      series_delete: true,
      series_scrape_schedule: true,
      series_trigger_scrape: true,
      chapters_upload: true,
      chapters_edit: true,
      chapters_delete: true,
      chapters_manage_ocr: true,
      moderate_comments: true,
      announcements_broadcast: true,
      reports_resolve: true,
      manage_ads: true,
      branding_edit: true,
      system_health: true,
    },
  },
  {
    id: "content",
    title: "📚 Content & Scraper Specialist",
    desc: "Focuses on series catalogue, chapter uploads, scraper crawling, and OCR translation engines.",
    color: "border-[#00AEF0]/40 bg-[#00AEF0]/10 text-[#00AEF0]",
    powers: {
      series_create: true,
      series_edit: true,
      series_delete: false,
      series_scrape_schedule: true,
      series_trigger_scrape: true,
      chapters_upload: true,
      chapters_edit: true,
      chapters_delete: false,
      chapters_manage_ocr: true,
      moderate_comments: false,
      announcements_broadcast: false,
      reports_resolve: true,
      manage_ads: false,
      branding_edit: false,
      system_health: true,
    },
  },
  {
    id: "moderator",
    title: "🛡️ Community & Quality Moderator",
    desc: "Pins top comments, deletes spam, broadcasts site notices, and resolves chapter error alerts.",
    color: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    powers: {
      series_create: false,
      series_edit: false,
      series_delete: false,
      series_scrape_schedule: false,
      series_trigger_scrape: false,
      chapters_upload: false,
      chapters_edit: false,
      chapters_delete: false,
      chapters_manage_ocr: false,
      moderate_comments: true,
      announcements_broadcast: true,
      reports_resolve: true,
      manage_ads: false,
      branding_edit: false,
      system_health: false,
    },
  },
];

export default function RoleManagement() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();

  const [selectedUserId, setSelectedUserId] = useState(3);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  const [newSubAdminEmail, setNewSubAdminEmail] = useState("");
  const [showRawEmails, setShowRawEmails] = useState(false);

  const isMainAdmin = Boolean(
    currentUser?.is_main_admin ||
    currentUser?.role === "admin" ||
    currentUser?.email === "admin@mangareader.local"
  );

  // Fetch all users
  const { data: usersData, isLoading: loadingUsers } = useQuery({
    queryKey: ["adminUsersDirectory"],
    queryFn: () => api.admin.users(),
    enabled: isMainAdmin,
  });

  const users = useMemo(() => {
    if (Array.isArray(usersData)) return usersData;
    if (Array.isArray(usersData?.items)) return usersData.items;
    return [];
  }, [usersData]);

  // Filter exclusively active sub-admins and staff (excluding normal readers)
  const subAdmins = useMemo(() => {
    return users.filter((u) => u.role === "secondary_admin" || u.is_secondary_admin);
  }, [users]);

  // Automatically ensure selectedUserId matches an active sub-admin
  useEffect(() => {
    if (subAdmins.length > 0 && !subAdmins.some((u) => u.id === Number(selectedUserId))) {
      setSelectedUserId(subAdmins[0].id);
    }
  }, [subAdmins, selectedUserId]);

  // Fetch permissions catalogue
  const { data: catalogueData, isLoading: loadingCatalogue } = useQuery({
    queryKey: ["permissionsCatalogue"],
    queryFn: () => api.admin.permissions.catalogue(),
    enabled: isMainAdmin,
  });

  const catalogue = useMemo(() => {
    return Array.isArray(catalogueData?.permissions) ? catalogueData.permissions : [];
  }, [catalogueData]);

  // Group catalogue permissions
  const groupedPermissions = useMemo(() => {
    const map = new Map();
    catalogue.forEach((p) => {
      const g = p.group || p.category || "General";
      if (!map.has(g)) map.set(g, []);
      map.get(g).push(p);
    });
    return Array.from(map.entries());
  }, [catalogue]);

  // Fetch active permissions for selected sub-admin
  const { data: userPermsData, isLoading: loadingPerms } = useQuery({
    queryKey: ["userPermissions", selectedUserId],
    queryFn: () => apiFetch(`/api/v1/admin/users/${selectedUserId}/permissions`).then((r) => r.json()),
    enabled: isMainAdmin && !!selectedUserId,
  });

  const activeOverrides = useMemo(() => {
    return userPermsData?.overrides || {};
  }, [userPermsData]);

  // Update permissions mutation with instant optimistic feedback
  const updatePermsMutation = useMutation({
    mutationFn: async ({ userId, overrides }) => {
      const res = await apiFetch(`/api/v1/admin/users/${userId}/permissions`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ overrides }),
      });
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["userPermissions", selectedUserId] });
      setNotice({ type: "success", message: "Power configuration updated instantly!" });
      setTimeout(() => setNotice(null), 3000);
    },
    onError: (err) => {
      setError(err?.message || "Failed to update permissions");
    },
  });

  const handleTogglePower = (key, currentVal) => {
    const updated = {
      ...activeOverrides,
      [key]: !currentVal,
    };
    updatePermsMutation.mutate({ userId: selectedUserId, overrides: updated });
  };

  const handleApplyPreset = (preset) => {
    updatePermsMutation.mutate({ userId: selectedUserId, overrides: preset.powers });
    setNotice({ type: "success", message: `Applied ${preset.title} preset successfully!` });
  };

  const handlePromoteEmail = async (e) => {
    e.preventDefault();
    if (!newSubAdminEmail.trim()) return;
    setError(null);
    try {
      const res = await api.admin.promoteSecondaryByEmail(newSubAdminEmail.trim());
      setNotice({ type: "success", message: `✅ ${newSubAdminEmail} appointed as Sub-Admin!` });
      setNewSubAdminEmail("");
      await queryClient.invalidateQueries({ queryKey: ["adminUsersDirectory"] });
      await queryClient.invalidateQueries({ queryKey: ["usersDirectory"] });
      if (res?.user?.id) {
        setSelectedUserId(res.user.id);
      }
    } catch (err) {
      setError(err?.message || "Promotion failed.");
    }
  };

  if (!isMainAdmin) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6">
        <div className="bg-[#15171c] border border-red-500/40 p-8 rounded-2xl max-w-md text-center space-y-3">
          <div className="text-3xl">🔒</div>
          <h2 className="text-xl font-bold text-white">Main Admin Access Only</h2>
          <p className="text-xs text-gray-400">
            Only the primary system owner (<strong className="text-white">admin@mangareader.local</strong>) can access the user database and calibrate sub-admin roles.
          </p>
          <Link to="/admin" className="inline-block mt-3 px-4 py-2 rounded-xl bg-[#00AEF0] text-white text-xs font-bold">
            ← Return to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  const selectedUser = users.find((u) => u.id === Number(selectedUserId));

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-6">
      {/* Header & Authority Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#262a33] pb-4">
        <div>
          <Link to="/admin" className="text-xs text-[#00AEF0] hover:underline mb-1 flex items-center gap-1 font-semibold">
            ← Back to Admin Console
          </Link>
          <h1 className="text-2xl font-extrabold text-white flex items-center gap-2.5">
            <span>🛡️ Sub-Admin Role &amp; Power Calibration</span>
            <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/40">
              Main Admin Exclusive
            </span>
          </h1>
          <p className="text-xs text-[#8b93a3] mt-1">
            Empower your sub-admins with fine-grained permissions so they can manage chapters, OCR, scrapers, ads, and community moderation.
          </p>
        </div>

        <div className="flex items-center gap-2 p-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-gray-300">
          <i className="fas fa-crown text-amber-400"></i>
          <span>Authorized as: <strong className="text-white">admin@mangareader.local</strong></span>
        </div>
      </div>

      {notice && (
        <div className="p-3.5 rounded-xl bg-emerald-950/40 border border-emerald-500/40 text-emerald-300 text-xs flex items-center justify-between">
          <span className="flex items-center gap-2">
            <i className="fas fa-check-circle text-emerald-400"></i>
            <span>{notice.message}</span>
          </span>
          <button type="button" onClick={() => setNotice(null)} className="text-gray-400 hover:text-white">✕</button>
        </div>
      )}

      {error && (
        <div className="p-3.5 rounded-xl bg-red-950/40 border border-red-500/40 text-red-300 text-xs flex items-center justify-between">
          <span className="flex items-center gap-2">
            <i className="fas fa-exclamation-triangle text-red-400"></i>
            <span>{error}</span>
          </span>
          <button type="button" onClick={() => setError(null)} className="text-gray-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Top Grid: Appoint Sub-Admin & Quick Selection */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Card 1: Appoint New Sub-Admin */}
        <div className="bg-[#15171c] border border-[#262a33] p-4 rounded-2xl space-y-3">
          <div className="flex items-center gap-2 text-white font-bold text-xs">
            <i className="fas fa-user-plus text-[#00AEF0]"></i>
            <span>Appoint New Sub-Admin</span>
          </div>
          <form onSubmit={handlePromoteEmail} className="space-y-2">
            <input
              type="email"
              required
              value={newSubAdminEmail}
              onChange={(e) => setNewSubAdminEmail(e.target.value)}
              placeholder="e.g. helper@mail.com"
              className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0]"
            />
            <button
              type="submit"
              className="w-full py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs transition flex items-center justify-center gap-1.5 shadow-md"
            >
              <i className="fas fa-shield-alt"></i>
              <span>Promote to Sub-Admin</span>
            </button>
          </form>
        </div>

        {/* Card 2: Select Sub-Admin Dropdown Menu */}
        <div className="bg-[#15171c] border border-[#262a33] p-4 rounded-2xl space-y-3 md:col-span-2">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2 text-white font-bold text-xs">
              <i className="fas fa-users-cog text-purple-400"></i>
              <span>Active Sub-Admin &amp; Staff Selector</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowRawEmails(!showRawEmails)}
                className="px-2.5 py-1 rounded-lg border border-purple-500/40 bg-purple-500/15 text-purple-300 hover:bg-purple-500/25 font-bold text-[10px] flex items-center gap-1 transition shadow"
                title="Toggle email privacy mask"
              >
                <i className={showRawEmails ? "fas fa-eye-slash" : "fas fa-shield-alt"}></i>
                <span>{showRawEmails ? "Mask Emails" : "Unmask Emails"}</span>
              </button>
              <span className="text-[11px] text-[#8b93a3]">
                {subAdmins.length} Appointed Sub-Admins
              </span>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-[11px] font-semibold text-gray-400 block">Select Active Sub-Admin / Staff from Dropdown:</label>
            <select
              value={selectedUserId || (subAdmins[0]?.id || "")}
              onChange={(e) => setSelectedUserId(Number(e.target.value))}
              className="w-full px-3 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white font-medium focus:outline-none focus:border-[#00AEF0] shadow-inner font-mono"
            >
              {subAdmins.map((u) => (
                <option key={u.id} value={u.id}>
                  🛡️ {u.username || u.name} ({showRawEmails ? u.email : maskEmail(u.email)}) — Active Sub-Admin Staff
                </option>
              ))}
              {subAdmins.length === 0 && (
                <option value="" disabled>No active sub-admins appointed yet. Appoint one on the left.</option>
              )}
            </select>
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            {subAdmins.map((u) => {
              const isSelected = selectedUserId === u.id;
              return (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => setSelectedUserId(u.id)}
                  className={`px-3 py-1.5 rounded-xl border text-xs font-bold transition flex items-center gap-2 ${
                    isSelected
                      ? "bg-purple-600/30 border-purple-500 text-white shadow"
                      : "bg-[#101216] border-[#262a33] text-gray-400 hover:text-white"
                  }`}
                >
                  <span>🛡️ {u.username || u.name}</span>
                  <span className="text-[10px] text-gray-400 font-mono">
                    ({showRawEmails ? u.email : maskEmail(u.email)})
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Preset Power Toggles */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold text-gray-300 flex items-center gap-1.5">
            <i className="fas fa-bolt text-amber-400"></i>
            <span>Quick Workload Power Presets</span>
          </span>
          <span className="text-[11px] text-[#8b93a3]">
            Click any preset to assign full authority sets instantly
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {PRESET_POWER_LEVELS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => handleApplyPreset(preset)}
              className={`p-3.5 rounded-2xl border text-left transition hover:scale-[1.01] active:scale-[0.99] shadow-lg ${preset.color}`}
            >
              <span className="font-bold text-xs block mb-1">{preset.title}</span>
              <p className="text-[10px] text-gray-300 leading-relaxed">{preset.desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Fine-Grained Capability Matrix */}
      <div className="bg-[#15171c] border border-[#262a33] rounded-2xl p-5 sm:p-6 shadow-2xl space-y-6">
        <div className="flex items-center justify-between border-b border-[#262a33] pb-4">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <i className="fas fa-sliders-h text-[#00AEF0]"></i>
              <span>Fine-Grained Capability Power Matrix</span>
            </h3>
            <p className="text-xs text-[#8b93a3] mt-0.5">
              Calibrate exact capabilities for <strong className="text-white">{selectedUser?.name || selectedUser?.username || "Selected Sub-Admin"}</strong> ({selectedUser?.email || "ID #" + selectedUserId}).
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold px-3 py-1 rounded-xl bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
              Instant Auto-Save Active
            </span>
          </div>
        </div>

        {loadingCatalogue || loadingPerms ? (
          <div className="p-12 text-center text-xs text-[#8b93a3] flex items-center justify-center gap-2">
            <i className="fas fa-spinner fa-spin text-[#00AEF0]"></i>
            <span>Loading capability matrix…</span>
          </div>
        ) : (
          <div className="space-y-6">
            {groupedPermissions.map(([groupName, perms]) => (
              <div key={groupName} className="space-y-3">
                <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
                  <i className="fas fa-folder-open text-[#00AEF0]"></i>
                  <span>{groupName}</span>
                </h4>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {perms.map((perm) => {
                    const isGranted = Boolean(activeOverrides[perm.key]);
                    return (
                      <div
                        key={perm.key}
                        className={`p-3.5 rounded-xl border transition flex items-start justify-between gap-3 ${
                          isGranted
                            ? "bg-[#101216] border-emerald-500/40 shadow-sm"
                            : "bg-[#101216]/60 border-[#262a33] opacity-75"
                        }`}
                      >
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-xs text-white">{perm.name}</span>
                            <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold ${
                              isGranted ? "bg-emerald-500/20 text-emerald-300" : "bg-gray-800 text-gray-400"
                            }`}>
                              {isGranted ? "POWER ACTIVE" : "DISABLED"}
                            </span>
                          </div>
                          <p className="text-[11px] text-[#8b93a3] leading-relaxed">
                            {perm.description || `Allows the sub-admin to perform ${perm.name.toLowerCase()}.`}
                          </p>
                        </div>

                        {/* Modern Glowing Power Toggle Button */}
                        <button
                          type="button"
                          onClick={() => handleTogglePower(perm.key, isGranted)}
                          className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                            isGranted ? "bg-[#00AEF0] ring-2 ring-[#00AEF0]/40" : "bg-gray-700"
                          }`}
                          role="switch"
                          aria-checked={isGranted}
                          title={`Toggle ${perm.name}`}
                        >
                          <span
                            aria-hidden="true"
                            className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
                              isGranted ? "translate-x-5" : "translate-x-0"
                            }`}
                          />
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
