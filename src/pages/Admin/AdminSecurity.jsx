import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import api from "../../services/api";
import { AdminSignInHint, CodeForm, Enrolment } from "../../components/AdminSecondFactor";

// Roadmap item 15: turn the admin second factor on or off.
export default function AdminSecurity() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setStatus(await api.get("/admin/2fa/status"));
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const disable = async (code) => {
    setBusy(true);
    setError("");
    try {
      await api.post("/admin/2fa/disable", { code });
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-xl mx-auto space-y-6 text-gray-200">
      <div>
        <Link to="/admin" className="text-xs text-[#8b93a3] hover:text-white transition">
          Admin
        </Link>
        <h1 className="text-lg font-bold text-white">Two-step sign-in</h1>
      </div>
      {!status && !error && <p className="text-xs text-[#8b93a3]">Loading…</p>}
      {error && !status && <p className="text-xs text-red-400">{error}</p>}
      {status && !status.enabled && status.managed_by_admin_sign_in && <AdminSignInHint />}
      {status && !status.enabled && !status.managed_by_admin_sign_in && <Enrolment onDone={load} />}
      {status && status.enabled && (
        <div className="space-y-3">
          <p className="text-xs text-emerald-400">
            On. Admin pages ask for an authenticator code every 30 minutes.
          </p>
          {status.required ? (
            <p className="text-xs text-[#8b93a3]">
              This site requires it for main admins, so it cannot be turned off here.
              {status.managed_by_admin_sign_in &&
                " Lost your phone? Reset it on the server with cli_bootstrap reset-2fa (GUIDE.md section 6)."}
            </p>
          ) : (
            <CodeForm
              onSubmit={disable}
              label="To turn it off, enter a code from your app"
              busy={busy}
              error={error}
            />
          )}
        </div>
      )}
    </div>
  );
}
