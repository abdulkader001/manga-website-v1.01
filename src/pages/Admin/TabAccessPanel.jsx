import React, { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../../services/api";

// Role Management -> Tab access. Owner only, and not delegable: not even an
// Admin who may manage roles sees this. The owner chooses, person by person,
// which admin tabs an Admin or sub-admin sees, or switches ALL of a person's
// powers off (they keep the title and the seat; nothing in the admin area opens).

const QUICK_PICKS = [
  { label: "Reports only", tabs: ["chapter-reports"] },
  { label: "Users only", tabs: ["users"] },
  { label: "Series only", tabs: ["series"] },
];

function Person({ person, tabs, flash }) {
  const queryClient = useQueryClient();
  const isSub = person.role === "sub_admin";
  // A sub-admin can never hold a site-owner power, so those tabs are not offered.
  const offered = tabs.filter((t) => !(isSub && t.owner_power));
  const [follow, setFollow] = useState(person.tabs === null);
  const [picked, setPicked] = useState(person.tabs || []);
  const [error, setError] = useState("");

  useEffect(() => {
    setFollow(person.tabs === null);
    setPicked(person.tabs || []);
  }, [person.tabs]);

  const save = useMutation({
    mutationFn: (body) => api.admin.tabAccess.set(person.user_id, body),
    onSuccess: (res) => {
      queryClient.setQueryData(["tabAccess"], res);
      queryClient.invalidateQueries({ queryKey: ["staffPermissions"] });
      setError("");
      flash(true, `Saved for ${person.name}.`);
    },
    onError: (e) => setError(e.message),
  });

  const flip = (key) => setPicked((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]));
  const body = { tabs: follow ? null : picked, suspended: person.suspended };

  return (
    <li className="p-3 rounded-xl bg-[#101216] border border-[#262a33] space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-white font-bold">{person.name}</span>
        <span className="px-1.5 py-0.5 rounded-md border border-[#262a33] text-[9px] font-bold uppercase text-[#8b93a3]">
          {isSub ? "sub-admin" : "Admin"}
        </span>
        {person.suspended ? (
          <span className="px-1.5 py-0.5 rounded-md border border-red-500/40 bg-red-500/10 text-[9px] font-bold uppercase text-red-300">
            all powers off
          </span>
        ) : person.tabs === null ? (
          <span className="text-[10px] text-[#8b93a3]">follows permissions</span>
        ) : (
          <span className="text-[10px] text-amber-300">
            {person.tabs.length ? `${person.tabs.length} tab(s)` : "no tabs"}
          </span>
        )}
      </div>

      <label className="flex items-center gap-2 text-[11px] text-gray-300">
        <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
        Follow their permissions (every tab their permissions allow)
      </label>

      {!follow && (
        <div className="space-y-2">
          <div className="flex gap-1.5 flex-wrap">
            {QUICK_PICKS.map((q) => (
              <button
                key={q.label}
                type="button"
                onClick={() => setPicked(q.tabs.filter((k) => offered.some((t) => t.key === k)))}
                className="px-2 py-1 rounded-lg border border-[#262a33] text-[10px] text-[#8b93a3] hover:text-white"
              >
                {q.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setPicked([])}
              className="px-2 py-1 rounded-lg border border-[#262a33] text-[10px] text-[#8b93a3] hover:text-white"
            >
              No tabs
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {offered.map((t) => (
              <label key={t.key} className="flex items-center gap-2 p-2 rounded-lg bg-[#15171c] border border-[#262a33]">
                <input
                  type="checkbox"
                  aria-label={`${person.name}: ${t.label}`}
                  checked={picked.includes(t.key)}
                  onChange={() => flip(t.key)}
                />
                <span className="text-white">{t.label}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {error && <p className="text-red-400 text-[11px]">{error}</p>}
      <div className="flex gap-2 flex-wrap">
        <button
          type="button"
          disabled={save.isPending}
          onClick={() => save.mutate(body)}
          className="px-3 py-1.5 rounded-lg bg-[#00AEF0] text-white font-bold disabled:opacity-50"
        >
          Save tabs
        </button>
        <button
          type="button"
          disabled={save.isPending}
          onClick={() => save.mutate({ tabs: person.tabs, suspended: !person.suspended })}
          className={`px-3 py-1.5 rounded-lg font-bold disabled:opacity-50 ${
            person.suspended ? "bg-emerald-600 text-white" : "bg-red-600/80 text-white"
          }`}
        >
          {person.suspended ? "Switch powers back on" : "Switch all powers off"}
        </button>
      </div>
    </li>
  );
}

export default function TabAccessPanel({ flash }) {
  const { data } = useQuery({ queryKey: ["tabAccess"], queryFn: () => api.admin.tabAccess.get() });
  if (!data) return null;
  return (
    <div className="bg-[#15171c] border border-emerald-500/30 rounded-2xl p-5 space-y-3 text-xs">
      <div>
        <h2 className="text-base font-bold text-white">Tab access</h2>
        <p className="text-[11px] text-[#8b93a3]">
          Choose which admin tabs each Admin and sub-admin sees. A moderator for reports and comments
          needn&apos;t see the scraper or the API tabs. A tab left out is hidden and its API refuses them too.
          <strong className="text-gray-300"> Switch all powers off</strong> keeps the person&apos;s title and seat but
          closes the whole admin area for them. Only you can see this section; it can&apos;t be given to anyone.
        </p>
      </div>
      {data.people.length === 0 ? (
        <p className="text-[#8b93a3]">No Admins or sub-admins yet.</p>
      ) : (
        <ul className="space-y-2">
          {data.people.map((p) => (
            <Person key={p.user_id} person={p} tabs={data.tabs} flash={flash} />
          ))}
        </ul>
      )}
    </div>
  );
}
