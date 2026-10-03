// v2 replaces v1, which kept every image a reader ever opened (chapter pages
// included) with no limit, and downloaded each one again on every view even
// when it already had it. Activating v2 deletes the v1 cache.
const CACHE_NAME = 'manga-reader-cache-v2';
const COVER_CACHE = 'manga-covers-v2';
// Covers are small and shown on every list; keep the most recent ones only.
const MAX_COVERS = 300;
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/favicon.ico',
];
const KEEP = new Set([CACHE_NAME, COVER_CACHE]);

self.addEventListener('install', (event) => {
  event.waitUntil(
    // One by one: with addAll a single missing file (it was /favicon.ico)
    // made the whole install fail, so the worker never ran.
    caches.open(CACHE_NAME).then((cache) =>
      Promise.all(STATIC_ASSETS.map((url) => cache.add(url).catch(() => {})))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => !KEEP.has(key)).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

function isCover(url) {
  return url.pathname.includes('/covers/');
}

async function trimCovers(cache) {
  const keys = await cache.keys();
  // Oldest first (insertion order): drop the overflow.
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_COVERS)).map((k) => cache.delete(k)));
}

async function coverFirst(request) {
  const cache = await caches.open(COVER_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    trimCovers(cache).catch(() => {});
  }
  return response;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Covers: from the cache when we have them, without asking the network again.
  if (isCover(url)) {
    event.respondWith(coverFirst(request));
    return;
  }

  // Chapter pages and other pictures go straight to the network: the server
  // already lets the browser cache them, and a page read once shouldn't stay
  // on the device for ever.
  if (request.destination === 'image') return;

  // Network-first for API calls and page navigations. Offline, a navigation
  // falls back to the cached app shell so the app can still open.
  event.respondWith(
    fetch(request).catch(async () => {
      const cached = await caches.match(request);
      if (cached) return cached;
      if (request.mode === 'navigate') {
        const shell = await caches.match('/index.html');
        if (shell) return shell;
      }
      return Response.error();
    })
  );
});
