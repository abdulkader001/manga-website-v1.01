import React, { useEffect, useState } from "react";
import { Link } from "react-router";
import { apiFetch } from "../services/api";
import NotFound from "./NotFound";

// One-time Admin sign-in for the site owner: e-mail + the one-time password
// kept (hashed) in the server's .env + a code from the authenticator app.
// Nothing on the site links here. Once the password has been used (or when
// none is set) the server answers 404 and this shows the normal "not found"
// page, as if the address never existed. Loaded as its own chunk (app.js).

const field =
  "w-full px-4 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0]";
const button =
  "w-full py-2.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-sm transition disabled:opacity-50";

async function post(body) {
  const res = await apiFetch("/api/v1/auth/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 404) return { step: "gone" };
  if (!res.ok) throw new Error(data?.error?.message || "Sign-in failed.");
  return data;
}

export default function AdminLogin() {
  const [open, setOpen] = useState(null); // null = checking
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState("password"); // password | enrol | code
  const [enrol, setEnrol] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch("/api/v1/auth/admin/status")
      .then((r) => setOpen(r.ok))
      .catch(() => setOpen(false));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await post({ email: email.trim(), password, code: step === "password" ? null : code.trim() });
      if (data.step === "gone") {
        setOpen(false);
        return;
      }
      if (data.step === "done") {
        // Full reload so every part of the app picks up the new session.
        window.location.assign("/admin");
        return;
      }
      if (data.step === "enrol") setEnrol(data);
      setStep(data.step);
      setCode("");
    } catch (err) {
      setError(err.message);
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  if (open === null) return <div className="min-h-screen bg-[#0b0d10]" />;
  if (!open) return <NotFound />;

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-[#0b0d10]">
      <form
        onSubmit={submit}
        className="w-full max-w-sm p-6 rounded-2xl bg-[#15171c] border border-[#262a33] space-y-4 text-gray-200"
      >
        <div>
          <h1 className="text-lg font-bold text-white flex items-center gap-2">
            <i className="fas fa-user-shield text-[#00AEF0]"></i> Admin sign-in
          </h1>
          <p className="text-xs text-[#8b93a3] mt-1">
            The site owner&apos;s first sign-in: your e-mail, the one-time admin password from
            the server, and your authenticator app. After this, the page disappears and you
            sign in like everyone else.
          </p>
        </div>

        {step === "password" && (
          <>
            <input
              className={field}
              type="email"
              autoComplete="username"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <input
              className={field}
              type="password"
              autoComplete="current-password"
              placeholder="One-time admin password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </>
        )}

        {step === "enrol" && enrol && (
          <div className="space-y-2 text-xs text-[#8b93a3]">
            <p>
              First sign-in: add this key to an authenticator app (Google Authenticator, Aegis,
              1Password… choose &quot;enter a setup key&quot;, time based), then type the 6-digit
              code it shows.
            </p>
            <code className="block break-all p-2 rounded-lg bg-[#0b0d10] text-white select-all">
              {enrol.secret}
            </code>
            <a className="text-[#00AEF0] underline" href={enrol.otpauth_uri}>
              Open in authenticator app
            </a>
          </div>
        )}

        {step !== "password" && (
          <input
            className={`${field} text-center tracking-[0.4em] text-lg`}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={7}
            placeholder="123456"
            aria-label="Authenticator code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoFocus
          />
        )}

        {error && <p className="text-xs text-red-400">{error}</p>}

        <button
          type="submit"
          className={button}
          disabled={busy || (step !== "password" && code.trim().length < 6)}
        >
          {busy ? "Checking…" : step === "password" ? "Continue" : "Sign in"}
        </button>

        <p className="text-[11px] text-[#8b93a3] text-center">
          <Link to="/login" className="hover:text-white">
            Back to normal sign-in
          </Link>
        </p>
      </form>
    </div>
  );
}
