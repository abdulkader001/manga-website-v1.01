import { apiFetch } from "../services/api";

// Sends readers' browser errors to Admin -> Error Report (POST /errors/report).
// Only the page path is sent (no query string, no account, no address); the
// server masks e-mails and tokens again before saving. Each distinct error is
// sent once per page load, and at most MAX_PER_LOAD errors in total, so a
// render loop can't flood the server.

const MAX_PER_LOAD = 10;
const sent = new Set();
let count = 0;
let installed = false;

function describe(error) {
  if (error instanceof Error) {
    return { kind: error.name || "Error", message: error.message || String(error), stack: error.stack || null };
  }
  if (error && typeof error === "object") {
    const message = typeof error.message === "string" ? error.message : safeJson(error);
    return { kind: error.name || "Error", message, stack: error.stack || null };
  }
  return { kind: "Error", message: String(error ?? "Unknown error"), stack: null };
}

function safeJson(value) {
  try {
    return JSON.stringify(value).slice(0, 500);
  } catch {
    return String(value);
  }
}

export function reportError(error, extra = {}) {
  try {
    if (typeof window === "undefined") return false;
    const info = describe(error);
    // A failed report must never report itself.
    if (info.message && info.message.includes("/errors/report")) return false;
    const stack = [info.stack, extra.componentStack].filter(Boolean).join("\n").slice(0, 16000) || null;
    const payload = {
      kind: String(extra.kind || info.kind).slice(0, 128),
      message: String(info.message || "").slice(0, 4000),
      stack,
      page: window.location.pathname.slice(0, 500),
    };
    const key = `${payload.kind}|${payload.message}|${payload.page}`;
    if (sent.has(key) || count >= MAX_PER_LOAD) return false;
    sent.add(key);
    count += 1;
    apiFetch("/errors/report", { method: "POST", body: JSON.stringify(payload), keepalive: true }).catch(() => {});
    return true;
  } catch {
    return false;
  }
}

export function installErrorReporter() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("error", (event) => {
    // Failed <img>/<script> loads also fire "error", without an error object;
    // broken page images are already handled by chapter reports.
    if (!event.error && !event.message) return;
    reportError(event.error || { name: "Error", message: event.message });
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    // API refusals (4xx) are answers, not faults; the server records its own 5xx.
    if (reason && typeof reason.status === "number") return;
    reportError(reason, { kind: reason?.name || "UnhandledRejection" });
  });
}

// For tests.
export function _resetErrorReporter() {
  sent.clear();
  count = 0;
}
