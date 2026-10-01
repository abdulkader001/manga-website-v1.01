import React, { useCallback, useEffect, useState } from "react";
import api from "../services/api";

// Roadmap item 15. Wraps admin pages: when the account has a second factor
// (authenticator app) and this browser has not entered a code recently, ask for
// one. When ADMIN_2FA_REQUIRED is on and a main admin has not enrolled yet, walk
// them through enrolment first.

export const STEP_UP_EVENT = "admin-step-up-required";

const box =
  "max-w-md mx-auto mt-16 p-6 rounded-2xl bg-[#101216] border border-[#262a33] text-gray-200 space-y-4";
const input =
  "w-full px-3 py-2 rounded-xl bg-[#0b0d10] border border-[#262a33] text-center tracking-[0.4em] text-lg";
const button =
  "px-4 py-2 rounded-xl text-xs font-bold bg-[#00AEF0] hover:bg-[#0F5065] text-white transition disabled:opacity-50";

export function CodeForm({ onSubmit, label, busy, error }) {
  const [code, setCode] = useState("");
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(code);
        setCode("");
      }}
    >
      <label className="block text-xs text-[#8b93a3]">{label}</label>
      <input
        className={input}
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={7}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        autoFocus
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      <button type="submit" className={button} disabled={busy || code.length < 6}>
        {busy ? "Checking…" : "Continue"}
      </button>
    </form>
  );
}

export function Enrolment({ onDone }) {
  const [setup, setSetup] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      setSetup(await api.post("/admin/2fa/setup", {}));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (code) => {
    setBusy(true);
    setError("");
    try {
      await api.post("/admin/2fa/enable", { code });
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!setup) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-[#8b93a3]">
          Use an authenticator app (Google Authenticator, Aegis, 1Password…) to
          add a second step to admin sign-in.
        </p>
        {error && <p className="text-xs text-red-400">{error}</p>}
        <button type="button" className={button} onClick={start} disabled={busy}>
          Set up authenticator
        </button>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-[#8b93a3]">
        Add this key to your authenticator app (choose “enter a setup key”, time
        based), then type the 6-digit code it shows.
      </p>
      <code className="block break-all p-2 rounded-lg bg-[#0b0d10] text-xs select-all">
        {setup.secret}
      </code>
      <a className="text-xs text-[#00AEF0] underline" href={setup.otpauth_uri}>
        Open in authenticator app
      </a>
      <CodeForm onSubmit={confirm} label="Code from the app" busy={busy} error={error} />
    </div>
  );
}

// With Admin sign-in set up on the server, the main admin's authenticator is
// enrolled there (email + server password), never from a plain session.
export function AdminSignInHint() {
  return (
    <div className="space-y-3 text-xs text-[#8b93a3]">
      <p>
        This site uses Admin sign-in. Sign in there with your e-mail, the one-time admin
        password from the server and your authenticator app; it sets the app up.
      </p>
      <a className={button + " inline-block"} href="/admin-login">
        Go to Admin sign-in
      </a>
    </div>
  );
}

export default function AdminSecondFactor({ children }) {
  const [state, setState] = useState(null); // {enabled, unlocked, required}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setState(await api.get("/admin/2fa/status"));
    } catch {
      // Not an admin or the API is down: let the page and its own errors speak.
      setState({ enabled: false, unlocked: true, required: false });
    }
  }, []);

  useEffect(() => {
    refresh();
    const onLocked = () => setState((s) => (s ? { ...s, unlocked: false } : s));
    window.addEventListener(STEP_UP_EVENT, onLocked);
    return () => window.removeEventListener(STEP_UP_EVENT, onLocked);
  }, [refresh]);

  const verify = async (code) => {
    setBusy(true);
    setError("");
    try {
      await api.post("/admin/2fa/verify", { code });
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!state) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center text-xs text-[#8b93a3]">
        Checking admin access…
      </div>
    );
  }
  if (state.required && !state.enabled) {
    return (
      <div className={box}>
        <h2 className="text-sm font-bold text-white">Set up two-step sign-in</h2>
        {state.managed_by_admin_sign_in ? <AdminSignInHint /> : <Enrolment onDone={refresh} />}
      </div>
    );
  }
  if (state.enabled && !state.unlocked) {
    return (
      <div className={box}>
        <h2 className="text-sm font-bold text-white">Confirm it’s you</h2>
        <CodeForm
          onSubmit={verify}
          label="Enter the 6-digit code from your authenticator app"
          busy={busy}
          error={error}
        />
      </div>
    );
  }
  return children;
}
