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

// ---- Core request wrapper ----
async function request(path, { method = "GET", body, headers = {}, params, signal } = {}) {
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

    if (res.status === 401 && !isSessionCheckPath(p)) {
      handleSessionExpired();
    }

    throw err;
  }

  return data;
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
  },

  // ---- Manga & Chapters (public) ----
  manga: {
    browse: (params) => api.get("/manga/", { params }),
    detail: (id) => api.get(`/manga/${id}`),
    chapters: (id, params) => api.get(`/manga/${id}/chapters`, { params }),
    chapter: (mangaId, chapterId) => api.get(`/manga/${mangaId}/chapters/${chapterId}`),
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

  // ---- Read History (primary: /history; legacy fallbacks still exist server-side) ----
  history: {
    list: (params) => api.get("/history/", { params }),
    /**
     * Add/Upsert history
     * @param {{mangaId:number, chapterId:number}} payload
     */
    add: ({ mangaId, chapterId }) =>
      api.post("/history/", { manga_id: mangaId, chapter_id: chapterId }),
    remove: (id) => api.del(`/history/${id}`),
    clearAll: () => api.del("/history/clear/all"),
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
      effective: (userId) => api.get(`/admin/users/${userId}/permissions`),
      setOverrides: (userId, overrides) =>
        api.put(`/admin/users/${userId}/permissions`, { overrides }),
    },

    footer: (payload) => api.footer.update(payload),
    settings: {
      get: () => api.get("/admin/settings"),
      update: (payload) => api.post("/admin/settings", payload),
      clearCache: () => api.post("/admin/settings/clear-cache"),
      deleteAllManga: () => api.post("/admin/maintenance/delete-all-manga"),
      purgeAllImages: () => api.post("/admin/maintenance/purge-all-images"),
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
      rescrape: (id) => api.post(`/admin/series/${id}/rescrape`),
      updateSchedule: (id, schedule) => api.post(`/admin/series/${id}/schedule`, schedule),
      batchSchedule: (mangaIds, schedule) => api.post("/admin/series/batch-schedule", { manga_ids: mangaIds, ...schedule }),
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
    redeemAdminToken: ({ token }) => api.post("/system/admin-token/redeem", { token }),
    // Requires a session (F-77) — used to decide whether the one-time
    // admin-claim form is worth showing at all.
    bootstrap: () => api.get("/system/bootstrap"),
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
    addSeriesByUrl: (url) => api.post("/admin/series", { url }),
    rescrapeSeries: (seriesId, confirmTitle) =>
      api.post(`/admin/series/${seriesId}/rescrape`, { confirm_title: confirmTitle }),
    rescrapeChapter: (chapterId, { delete_previous = false } = {}) =>
      api.post(`/admin/chapters/${chapterId}/rescrape`, { delete_previous }),
    listApprovedDomains: () => api.get("/admin/approved-domains"),
    addApprovedDomain: (payload) => api.post("/admin/approved-domains", payload),
    removeApprovedDomain: (id) => api.del(`/admin/approved-domains/${id}`),
  },

  // ---- Custom Tabs ----
  tabs: {
    list: () => api.get("/custom-tabs"),
    add: (payload) => api.post("/custom-tabs", payload),
    remove: (id) => api.del(`/custom-tabs/${id}`),
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
