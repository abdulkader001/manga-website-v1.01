// Centralized frontend config.
//
// The API base is resolved in priority order:
//   1. Runtime config served by nginx at /config.json (written from the
//      API_BASE env var when the `web` container starts — see
//      deployment/nginx/entrypoint.sh). This lets ops repoint the frontend at a
//      different backend without rebuilding the image.
//   2. REACT_APP_API_BASE, a CRA build-time variable baked into the bundle.
//   3. A hardcoded default, "/api/v1".
//
// `npm start` has no nginx in front of it, so /config.json 404s there and
// step 2/3 apply -- that's the intended dev fallback, not a bug.

const DEFAULT_API_BASE = "/api/v1";

function normalizeBase(value) {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (!trimmed) return "";
  return trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed;
}

const rawEnv = typeof process !== "undefined" && process.env ? process.env : {};
const metaEnv = typeof import.meta !== "undefined" && import.meta.env ? import.meta.env : {};

let apiBase =
  normalizeBase(metaEnv.VITE_API_BASE) ||
  normalizeBase(rawEnv.REACT_APP_API_BASE) ||
  DEFAULT_API_BASE;

const configReady = (async () => {
  try {
    const res = await fetch("/config.json", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      const fetchedBase = normalizeBase(data && data.apiBase);
      if (fetchedBase) {
        apiBase = fetchedBase;
      }
    }
  } catch (err) {
    // /config.json unavailable
  }
  return apiBase;
})();

const CONFIG = {
  get API_BASE() {
    return apiBase;
  },
  FRONTEND_URL:
    metaEnv.VITE_FRONTEND_URL ||
    rawEnv.REACT_APP_FRONTEND_URL ||
    (typeof window !== "undefined" && window.location ? window.location.origin : ""),
  BRAND_NAME:
    metaEnv.VITE_BRAND_NAME ||
    rawEnv.REACT_APP_BRAND_NAME ||
    "MangaWorld",
};

export { configReady };
export default CONFIG;
