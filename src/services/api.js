// frontend/src/services/api.js
import CONFIG, { configReady } from "../config";

/**
 * Base URL rules
 * - CONFIG.API_BASE should already point at your FastAPI prefix (e.g. "/api" in production
 *   behind nginx, or "http://localhost:8000/api" in local development). We do not append an
 *   extra "/api" here because the FastAPI application already exposes routes beneath that
 *   prefix.
 */
function computeBaseUrl() {
  return (CONFIG.API_BASE || "").replace(/\/$/, ""); // ensure no trailing slash
}

// Mutable so callers that read BASE_URL directly (e.g. AuthContext's OAuth
// redirect) see the runtime-config value once it resolves. Safe to update
// here because this .then() is registered before request() ever awaits
// configReady, so it always runs first on the shared promise's job queue.
let BASE_URL = computeBaseUrl();
configReady.then(() => {
  BASE_URL = computeBaseUrl();
});

function resolveAuthBase() {
  const trimmed = BASE_URL.replace(/\/$/, "");

  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }

  if (typeof window !== "undefined" && window.location) {
    const origin = window.location.origin ? window.location.origin.replace(/\/$/, "") : "";

    if (!trimmed) {
      return origin;
    }

    const prefix = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
    return `${origin}${prefix}`.replace(/\/$/, "");
  }

  return trimmed;
}

function buildAuthUrl(path = "") {
  const safePath = String(path || "").replace(/^\/+/, "");
  const base = resolveAuthBase();

  if (!base) {
    return `/${safePath}`;
  }

  const normalizedBase = base.replace(/\/$/, "");

  try {
    return new URL(safePath, `${normalizedBase}/`).toString();
  } catch (err) {
    return `${normalizedBase}/${safePath}`;
  }
}

// ---- Optional token helpers (cookies are primary auth; these are passthroughs) ----
// C6: the server issues a double-submit `csrf_token` cookie and validates the
// `X-CSRF-Token` header against it. Prefer the cookie value so the header always
// matches what the server compares against; fall back to localStorage for
// backwards compatibility with older sessions.
function getCsrfFromCookie() {
  try {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  } catch {
    return null;
  }
}
function getCsrf() {
  const fromCookie = getCsrfFromCookie();
  if (fromCookie) return fromCookie;
  try {
    return localStorage.getItem("csrf_token");
  } catch {
    return null;
  }
}

// ---- F-39: global session-expiry handling ----
// `/auth/me` (and friends) are polled to *discover* whether a session exists at
// all, so a 401 there is the normal anonymous-visitor outcome, not a session
// dying mid-use -- redirecting on it would bounce every logged-out visitor to
// /login, which is exactly what public browsing/reading must not do.
const SESSION_CHECK_PATHS = ["/auth/me", "/auth/refresh", "/auth/options"];
function isSessionCheckPath(path) {
  return SESSION_CHECK_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}

// Only 401 (truly unauthenticated / expired session) forces a redirect. 403 in
// this API means "authenticated but not allowed to do this specific thing"
// (content rights, comment ownership, admin permission tiers, community
// moderation, etc.) and must keep surfacing to the caller instead of logging
// the user out.
// Anonymous visitors browse and read freely. A background GET that comes back
// 401 for someone who was never signed in is just "no access", not a dying
// session, so only redirect when a session existed (or the visitor tried to
// perform an action that needs one).
let sessionActive = false;
export function setSessionActive(value) {
  sessionActive = !!value;
}

function handleSessionExpired() {
  try {
    localStorage.removeItem("csrf_token");
  } catch {}
  if (
    typeof window !== "undefined" &&
    window.location &&
    window.location.pathname !== "/login"
  ) {
    window.location.assign("/login");
  }
}

// The access token lasts an hour but the refresh cookie much longer. When a
// call comes back 401, renew the token once (all concurrent callers share one
// refresh) and repeat the call, instead of throwing the person to /login in
// the middle of what they were doing.
let refreshInFlight = null;
export function refreshSession() {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const csrf = getCsrf();
        const res = await fetch(new URL(`${BASE_URL}/auth/refresh`, window.location.origin).toString(), {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}) },
          body: "{}",
        });
        return res.ok;
      } catch {
        return false;
      } finally {
        setTimeout(() => {
          refreshInFlight = null;
        }, 0);
      }
    })();
  }
  return refreshInFlight;
}

// ---- Core request wrapper ----
async function request(path, options = {}, retried = false) {
  const { method = "GET", body, headers = {}, params, signal } = options;
  await configReady;
  const p = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`${BASE_URL}${p}`, window.location.origin);

  if (params && typeof params === "object") {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, v);
    }
  }

  const csrf = getCsrf();
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;

  const finalHeaders = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    ...headers,
  };

  let res;
  try {
    res = await fetch(url.toString(), {
      method,
      headers: finalHeaders,
      credentials: "include", // REQUIRED for cookie/JWT flows
      body: body
        ? isFormData
          ? body
          : typeof body === "string"
          ? body
          : JSON.stringify(body)
        : undefined,
      signal,
    });
  } catch (err) {
    const networkError = new Error(
      "Unable to reach the FastAPI backend. Confirm the service is running and that ALLOWED_ORIGINS / REACT_APP_API_BASE allow this origin."
    );
    networkError.cause = err;
    networkError.isNetworkError = true;
    networkError.url = url.toString();
    throw networkError;
  }

  if (res.status === 401 && !retried && !isSessionCheckPath(p) && (sessionActive || method !== "GET")) {
    if (await refreshSession()) return request(path, options, true);
  }

  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      // Narrow fallback: a non-JSON body (e.g. an HTML error page from a
      // proxy/gateway in front of the API) — treated as no data below so a
      // sane HTTP-status message is used instead of crashing on parse.
    }
  }

  if (!res.ok) {
    // Standard error envelope (SRS 1B.4.2): { success:false, error:{code,message,details?} }.
    const message = data && typeof data === "object" ? data.error?.message : null;
    const err = new Error(
      message || `HTTP ${res.status}: ${res.statusText || "Request failed"}`
    );
    err.status = res.status;
    err.body = data;
    err.code = data && typeof data === "object" ? data.error?.code : undefined;

    // Roadmap item 15: the admin step-up ran out (or was never done). Tell the
    // admin gate so it asks for a code instead of showing a raw error.
    if (
      res.status === 403 &&
      err.code === "REVERIFICATION_REQUIRED" &&
      typeof window !== "undefined"
    ) {
      window.dispatchEvent(new Event("admin-step-up-required"));
    }

    // Geolock: the visitor's country is blocked; show the notice page.
    if (res.status === 451 && err.code === "REGION_BLOCKED" && typeof window !== "undefined") {
      window.dispatchEvent(new Event("region-blocked"));
    }

    if (res.status === 401 && !isSessionCheckPath(p) && (sessionActive || method !== "GET")) {
      handleSessionExpired();
    }

    throw err;
  }

  return data;
}

// ---- fetch() with the same base URL, cookies and CSRF header as `api.*` ----
// For call sites that need the raw Response (status handling, non-JSON bodies).
// Unlike request() it never redirects on 401: a wrong password is a normal
// answer on the login form, not an expired session. Accepts the historical
// "/api/v1/..." paths as well as bare "/..." ones.
export async function apiFetch(path, init = {}, retried = false) {
  await configReady;
  let p = String(path || "");
  p = p.replace(/^\/api(\/v1)?(?=\/)/, "");
  if (!p.startsWith("/")) p = `/${p}`;
  const url = new URL(`${BASE_URL}${p}`, window.location.origin);
  const method = (init.method || "GET").toUpperCase();
  const csrf = getCsrf();
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  const headers = {
    ...(isFormData || method === "GET" ? {} : { "Content-Type": "application/json" }),
    ...(csrf && method !== "GET" ? { "X-CSRF-Token": csrf } : {}),
    ...(init.headers || {}),
  };
  const res = await fetch(url.toString(), { ...init, method, headers, credentials: "include" });
  if (res.status === 401 && !retried && !isSessionCheckPath(p) && (sessionActive || method !== "GET")) {
    if (await refreshSession()) return apiFetch(path, init, true);
  }
  return res;
}

// ---- Public verbs ----
const api = {
  get: (path, opt = {}) => request(path, { ...opt, method: "GET" }),
  post: (path, body, opt = {}) => request(path, { ...opt, method: "POST", body }),
  put: (path, body, opt = {}) => request(path, { ...opt, method: "PUT", body }),
  patch: (path, body, opt = {}) => request(path, { ...opt, method: "PATCH", body }),
  del: (path, opt = {}) => request(path, { ...opt, method: "DELETE" }),

  // ---- Configuration ----
  config: {
    providers: () => api.get("/config/providers"),
    siteAccess: () => api.get("/config/site-access"),
    // Which website functions are on (the owner's switches); on/off only.
    siteFunctions: () => api.get("/config/site-functions"),
  },

  // ---- Authentication ----
  auth: {
    me: () => api.get("/auth/me"),
    refresh: () => api.post("/auth/refresh", {}),
    // `everywhere` also invalidates sessions on the user's other devices —
    // the server-side half, so a token copied elsewhere stops working rather
    // than merely losing its cookie in this browser.
    logout: ({ everywhere = false } = {}) =>
      api.post(`/auth/logout${everywhere ? "?all=true" : ""}`, {}),
    requestMagicLink: (email) => api.post("/auth/request-magic-link", { email }),
    consumeMagicLink: (token) => api.get(`/auth/magic-link/${encodeURIComponent(token)}`),
    loginUrl: (provider = "google") => buildAuthUrl(`auth/${provider}`),
    login: (provider = "google") => {
      const target = buildAuthUrl(`auth/${provider}`);
      if (typeof window !== "undefined" && window.location && typeof window.location.assign === "function") {
        window.location.assign(target);
      } else if (typeof window !== "undefined") {
        window.location.href = target;
      }
    },
    options: () => api.get("/auth/options"),
    checkUsername: (username) =>
      api.get("/auth/check-username", { params: { username } }),
    completeProfile: (payload) => api.post("/auth/complete-profile", payload),
    updateProfile: (payload) => api.post("/auth/profile", payload),
  },

  announcements: {
    list: () => api.get("/announcements"),
    broadcast: (payload) => api.post("/admin/broadcast", payload),
    remove: (id) => api.del(`/admin/announcements/${id}`),
  },

  // ---- Manga & Chapters (public) ----
  manga: {
    browse: (params) => api.get("/manga/", { params }),
    detail: (id) => api.get(`/manga/${id}`),
    chapters: (id, params) => api.get(`/manga/${id}/chapters`, { params }),
    chapter: (mangaId, chapterId) => api.get(`/manga/${mangaId}/chapters/${chapterId}`),
    batch: (ids) => api.get("/manga/batch", { params: { ids } }),
    chapterTitles: (mangaId, lang) => api.get(`/manga/${mangaId}/chapter-titles`, { params: { lang } }),
    rate: (id, rating) => api.post(`/manga/${id}/rate`, { rating }),
    likeChapter: (chapterId) => api.post(`/chapters/${chapterId}/like`),
    reportChapter: (chapterId, payload) => api.post(`/chapters/${chapterId}/report`, payload),
  },

  // ---- Chapter Issue Reports & Alerts ----
  reports: {
    list: (params) => api.get("/reports/chapters", { params }),
    getChapterReports: (chapterId) => api.get(`/chapters/${chapterId}/reports`),
    resolve: (id) => api.post(`/reports/${id}/resolve`),
    remove: (id) => api.del(`/reports/${id}`),
  },

  // ---- Bookmarks (per-user, cookie auth) ----
  bookmarks: {
    list: () => api.get("/bookmarks"),
    importBackup: (payload) => api.post("/bookmarks/import", payload),
    /**
     * Add bookmark
     * @param {number} mangaId
     * @param {number|undefined|null} chapterId optional chapter-level bookmark
     */
    add: (mangaId, chapterId = null) =>
      api.post("/bookmarks", { mangaId, chapterId }),
    /**
     * Remove bookmark
     * - If chapterId provided → removes only that chapter's bookmark
     * - Else → removes the manga-level bookmark (and any chapter-specific ones for this manga)
     */
    remove: (mangaId, chapterId = null) =>
      chapterId == null
        ? api.del(`/bookmarks/${mangaId}`)
        : api.del(`/bookmarks/${mangaId}`, { params: { chapterId } }),
  },

  // ---- Read chapters of a signed-in reader (components/HistorySync.jsx) ----
  history: {
    /** One chapter was just opened. */
    read: (chapterId, readAt) =>
      api.post("/history/read", { chapter_id: chapterId, read_at: readAt }),
    /**
     * Send changes ({entries, clear_manga, clear_all, return_entries}); the
     * answer is the account's whole list of read chapters.
     */
    sync: (payload) => api.post("/history/sync", payload),
  },

  // ---- Ads / Branding ----
  ads: {
    slots: (params) => api.get("/ads/slots", { params }),
    config: () => api.get("/ads/config"),
    placements: () => api.get("/ads/placements"),
    trackClick: (slotId) => api.post(`/ads/click/${slotId}`, {}),
  },

  // Direct ad creatives (admin-managed rows in the ad_slots table).
  adSlots: {
    list: (params) => api.get("/ad-slots", { params }),
    create: (payload) => api.post("/ad-slots", payload),
    update: (id, payload) => api.patch(`/ad-slots/${id}`, payload),
    remove: (id) => api.del(`/ad-slots/${id}`),
  },
  branding: {
    get: () => api.get("/branding"),
    update: (payload) => api.post("/branding", payload),
    uploadLogo: (file, { cleanup } = {}) => {
      const form = new FormData();
      form.append("file", file);
      const cleanupList = Array.isArray(cleanup)
        ? cleanup.filter((token) => typeof token === "string" && token.trim())
        : [];
      if (cleanupList.length) {
        form.append("cleanup", JSON.stringify(cleanupList));
      }
      return request("/branding/logo", { method: "POST", body: form });
    },
  },
  support: {
    get: () => api.get("/support"),
  },
  footer: {
    get: () => api.get("/footer"),
    update: (payload) => api.post("/footer", payload),
    getSocialLinks: () => api.get("/social-links"),
    saveSocialLinks: (links) => api.post("/social-links", { links }),
    addSocialLink: (link) => api.post("/social-links/add", link),
    updateSocialLink: (id, payload) => api.put(`/social-links/${id}`, payload),
    deleteSocialLink: (id) => api.del(`/social-links/${id}`),
  },

  // ---- Health ----
  health: {
    simple: () => api.get("/health"),
    runDiagnostics: () => api.post("/health/diagnostics"),
  },

  // ---- Admin (users, roles, settings) ----
  admin: {
    users: () => api.get("/admin/users/all"),
    userDirectory: {
      list: ({ page, search } = {}) =>
        api.get("/admin/users", {
          params: {
            page,
            search,
          },
        }),
      promote: (userId, body = { role: "secondary_admin" }) =>
        api.post(`/admin/promote/${userId}`, body),
      demote: (userId) => api.post(`/admin/demote/${userId}`),
    },
    promoteSecondary: (identifier) =>
      api.post("/admin/promote-secondary",
        typeof identifier === "object" && identifier !== null
          ? identifier
          : { user_id: identifier }
      ),
    demoteSecondary: (identifier) =>
      api.post("/admin/demote-secondary",
        typeof identifier === "object" && identifier !== null
          ? identifier
          : { user_id: identifier }
      ),
    demoteMain: (identifier) =>
      api.post("/admin/demote-main",
        typeof identifier === "object" && identifier !== null
          ? identifier
          : { user_id: identifier }
      ),
    promoteSecondaryByEmail: (email) =>
      api.post("/admin/promote-secondary", { email }),
    demoteSecondaryByEmail: (email) => api.post("/admin/demote-secondary", { email }),

    permissions: {
      catalogue: () => api.get("/admin/permissions/catalogue"),
      mine: () => api.get("/admin/permissions/me"),
      effective: (userId) => api.get(`/admin/users/${userId}/permissions`),
      // `code`: the owner's authenticator code, needed to give a site-owner power.
      setOverrides: (userId, overrides, code) =>
        api.put(`/admin/users/${userId}/permissions`, code ? { overrides, code } : { overrides }),
      managed: () => api.get("/admin/permissions/managed"),
      succession: () => api.get("/admin/roles/succession"),
      saveSuccession: (body) => api.put("/admin/roles/succession", body),
      reset: (userId) => api.post(`/admin/users/${userId}/permissions/reset`),
      presets: () => api.get("/admin/permissions/presets"),
      applyPreset: (userId, preset) =>
        api.post(`/admin/users/${userId}/permissions/apply-preset`, { preset }),
    },

    // Admins, their seats and succession lines, and the sub-admin ceiling.
    roles: {
      admins: () => api.get("/admin/roles/admins"),
      makeAdmin: (userId, code) => api.post("/admin/roles/admins", { user_id: userId, code }),
      removeAdmin: (userId, to) => api.post(`/admin/roles/admins/${userId}/demote`, { to }),
      setQuota: (userId, quota) => api.put(`/admin/roles/admins/${userId}/quota`, { quota }),
      setSuccessors: (userId, ids) =>
        api.put(`/admin/roles/admins/${userId}/successors`, { successor_ids: ids }),
      handOver: (userId, successorId, code) =>
        api.post(`/admin/roles/admins/${userId}/hand-over`, { successor_id: successorId || null, code }),
      limits: () => api.get("/admin/roles/sub-admin-limits"),
      saveLimits: (blocked, code) => api.put("/admin/roles/sub-admin-limits", { blocked, code }),
    },

    footer: (payload) => api.footer.update(payload),
    settings: {
      get: () => api.get("/admin/settings"),
      update: (payload) => api.post("/admin/settings", payload),
      clearCache: () => api.post("/admin/settings/clear-cache"),
      deleteAllManga: () => api.post("/admin/maintenance/delete-all-manga"),
      purgeAllImages: () => api.post("/admin/maintenance/purge-all-images"),
    },
    // Main admin only: donation / support links.
    support: {
      get: () => api.get("/admin/support"),
      update: (links) => api.put("/admin/support", { links }),
    },
    // Owner only (never delegable): every website function and its on/off switch.
    // Admin -> Error Report: recorded errors with a likely cause and fix.
    errorReports: {
      list: ({ status = "open", source } = {}) => api.get("/admin/error-reports", { params: { status, source } }),
      resolve: (id) => api.post(`/admin/error-reports/${id}/resolve`),
      reopen: (id) => api.post(`/admin/error-reports/${id}/reopen`),
      clearResolved: () => api.del("/admin/error-reports/resolved"),
    },
    siteFunctions: {
      list: () => api.get("/admin/site-functions"),
      set: (key, enabled) => api.put(`/admin/site-functions/${key}`, { enabled: Boolean(enabled) }),
    },
    // Owner only (never delegable): which admin tabs each Admin / sub-admin sees.
    tabAccess: {
      get: () => api.get("/admin/roles/tab-access"),
      set: (userId, { tabs, suspended }) =>
        api.put(`/admin/roles/tab-access/${userId}`, { tabs, suspended: Boolean(suspended) }),
    },
    apiRegistry: {
      get: () => api.get("/admin/api-registry"),
      saveProvider: (category, provider) => api.post("/admin/api-registry/provider", { category, provider }),
      deleteProvider: (category, id) => api.del(`/admin/api-registry/provider/${category}/${id}`),
      testConnection: (payload) => api.post("/admin/api-registry/test-connection", payload),
    },
    ads: {
      get: () => api.get("/admin/ads"),
      update: (payload) => api.post("/admin/ads", payload),
    },

    // Old content management routes (kept only if your backend still exposes them)
    series: {
      list: (params) => api.get("/admin/series", { params }),
      add: (payload) => api.post("/admin/series", typeof payload === "string" ? { url: payload } : payload),
      remove: (id) => api.del(`/admin/series/${id}`),
      // The server refuses a full re-scrape unless the series name is typed
      // back (confirm_title); without it every click failed with 422.
      rescrape: (id, confirmTitle) => api.post(`/admin/series/${id}/rescrape`, { confirm_title: confirmTitle }),
      updateSchedule: (id, schedule) => api.post(`/admin/series/${id}/schedule`, schedule),
      mirrorImages: (id) => api.post(`/admin/series/${id}/mirror-images`),
      updateLayout: (id, layout) => api.post(`/admin/series/${id}/layout`, layout),
      batchSchedule: (mangaIds, schedule) => api.post("/admin/series/batch-schedule", { manga_ids: mangaIds, ...schedule }),
      // status: none | requested | taken_down. taken_down deletes the stored pictures.
      takedown: (id, { status, reason }) => api.post(`/admin/series/${id}/takedown`, { status, reason }),
    },
    rescrapeChapter: (chapterId, { delete_previous = false } = {}) =>
      api.post(`/admin/chapters/${chapterId}/rescrape`, { delete_previous }),
    deleteChapterPage: (chapterId, pageIndex) =>
      api.del(`/admin/chapters/${chapterId}/pages/${pageIndex}`),
  },

  // ---- Notifications (SRS 1I) ----
  notifications: {
    list: (params) => api.get("/notifications", { params }),
    unreadCount: () => api.get("/notifications/unread-count"),
    markRead: (id) => api.post(`/notifications/${id}/read`),
    markAllRead: () => api.post("/notifications/read-all"),
    remove: (id) => api.del(`/notifications/${id}`),
    getPrefs: () => api.get("/users/me/notification-prefs"),
    updatePrefs: (payload) => api.put("/users/me/notification-prefs", payload),
  },

  // ---- System state ----
  system: {
    state: () => api.get("/system/state"),
    // Per-process uptime/RSS/CPU snapshot. Formerly served at /metrics, which
    // now belongs exclusively to the Prometheus exposition endpoint.
    stats: () => api.get("/system/stats"),
  },

  user: {
    getSettings: () => api.get("/user/settings"),
    updateSettings: (payload) => api.post("/user/settings", payload),
    updateApiKeys: (payload) => api.put("/user/api-keys", payload),
    uploadProfileImage: (file) => {
      const formData = new FormData();
      formData.append("file", file);
      return api.post("/user/profile-image", formData);
    },
    // Part 2: 2A.3/2C.4.4/2E.1/2F.2 processing preferences.
    getProcessingSettings: () => api.get("/user/processing-settings"),
    updateProcessingSettings: (payload) => api.put("/user/processing-settings", payload),
    overlayFonts: () => api.get("/user/overlay-fonts"),
  },

    integrations: {
    list: () => api.get("/integrations/list"),
    add: (service, config) => api.post("/integrations/add", { service, config }),
    remove: (service) => api.del("/integrations/remove", { body: { service } }),
  },

  // ---- Admin: Scraper endpoints (Secondary+ / Main Admin) ----
  scraper: {
    getAiConfig: () => api.get("/admin/scraper/ai-config"),
    saveAiConfig: (payload) => api.post("/admin/scraper/ai-config", payload),
    // Preview / parser generation run on a background worker: start returns a
    // task id, getTask is polled until status is "done" or "failed".
    startPreview: (payload) => api.post("/admin/scraper/preview", payload),
    startParserGeneration: (url) => api.post("/admin/scraper/parsers/generate", { url }),
    getTask: (taskId) => api.get(`/admin/scraper/tasks/${encodeURIComponent(taskId)}`),
    listParsers: () => api.get("/admin/scraper/parsers"),
    addSeriesByUrl: (url) => api.post("/admin/series", { url }),
    rescrapeSeries: (seriesId, confirmTitle) =>
      api.post(`/admin/series/${seriesId}/rescrape`, { confirm_title: confirmTitle }),
    rescrapeChapter: (chapterId, { delete_previous = false } = {}) =>
      api.post(`/admin/chapters/${chapterId}/rescrape`, { delete_previous }),
    listApprovedDomains: () => api.get("/admin/approved-domains"),
    addApprovedDomain: (payload) => api.post("/admin/approved-domains", payload),
    removeApprovedDomain: (id) => api.del(`/admin/approved-domains/${id}`),
  },

  // ---- Native comments (SRS Part 3 / 3A) ----
  comments: {
    config: () => api.get("/comments/config"),
    list: (targetType, targetId, params) =>
      api.get(`/comments/${targetType}/${targetId}`, { params }),
    create: (payload) => api.post("/comments/", payload),
    edit: (id, content) => api.patch(`/comments/${id}`, { content }),
    remove: (id) => api.del(`/comments/${id}`),
    vote: (id, value) => api.post(`/comments/${id}/vote`, { value }),
    react: (id, emoji) => api.post(`/comments/${id}/react`, { emoji }),
    report: (id, reason) => api.post(`/comments/${id}/report`, { reason }),
    moderatorRemove: (id, reason) => api.post(`/comments/${id}/remove`, { reason }),
    listReports: (params) => api.get("/comments/moderation/reports", { params }),
    resolveReport: (id, actioned) =>
      api.post(`/comments/moderation/reports/${id}/resolve`, { actioned }),
  },

  // ---- Community: emojis, rank, Pills, GIFs/memes, user moderation (Part 3) ----
  community: {
    emojis: (q) => api.get("/community/emojis", { params: q ? { q } : undefined }),
    addCustomEmoji: (payload) => api.post("/community/emojis/custom", payload),
    removeCustomEmoji: (id) => api.del(`/community/emojis/custom/${id}`),

    rankMe: () => api.get("/community/rank/me"),
    rank: (userId) => api.get(`/community/rank/${userId}`),
    realms: () => api.get("/community/realms"),
    updateRealm: (id, payload) => api.patch(`/community/realms/${id}`, payload),

    pills: () => api.get("/community/pills"),
    claimPill: (id) => api.post(`/community/pills/${id}/claim`),

    blockUser: (userId, reason) => api.post(`/community/users/${userId}/block`, { reason }),
    unblockUser: (userId) => api.post(`/community/users/${userId}/unblock`),
    timeoutUser: (userId, hours, reason) =>
      api.post(`/community/users/${userId}/timeout`, { hours, reason }),

    searchGifs: (q) => api.get("/community/gifs/search", { params: { q } }),

    uploadMeme: (file) => {
      const form = new FormData();
      form.append("file", file);
      return api.post("/community/memes", form);
    },
    removeMeme: (id) => api.del(`/community/memes/${id}`),
    reportMeme: (id, reason) => api.post(`/community/memes/${id}/report`, { reason }),
  },
};

export default api;
export { BASE_URL };
