import { describe, it, expect, vi, beforeEach } from "vitest";
import fs from "node:fs";
import path from "node:path";

// Runs public/sw.js against a fake worker scope and checks what its fetch
// handler does with covers, chapter pages and offline navigations.
const source = fs.readFileSync(path.resolve(__dirname, "../../public/sw.js"), "utf8");

function makeCache() {
  const store = new Map();
  return {
    store,
    match: vi.fn(async (req) => store.get(typeof req === "string" ? req : req.url)),
    put: vi.fn(async (req, res) => store.set(req.url, res)),
    add: vi.fn(async () => {}),
    keys: vi.fn(async () => [...store.keys()].map((url) => ({ url }))),
    delete: vi.fn(async (k) => store.delete(k.url)),
  };
}

function load() {
  const listeners = {};
  const caches = new Map();
  const cacheStorage = {
    open: vi.fn(async (name) => {
      if (!caches.has(name)) caches.set(name, makeCache());
      return caches.get(name);
    }),
    keys: vi.fn(async () => [...caches.keys()]),
    delete: vi.fn(async (name) => caches.delete(name)),
    match: vi.fn(async (req) => {
      for (const c of caches.values()) {
        const hit = await c.match(req);
        if (hit) return hit;
      }
      return undefined;
    }),
  };
  const scope = {
    location: { origin: "https://site.test" },
    addEventListener: (type, fn) => (listeners[type] = fn),
    skipWaiting: () => {},
    clients: { claim: () => {} },
  };
  const fetchMock = vi.fn(async () => ({ ok: true, clone() { return this; } }));
  const run = new Function("self", "caches", "fetch", "Response", source);
  const ResponseStub = { error: () => ({ type: "error" }) };
  run(scope, cacheStorage, fetchMock, ResponseStub);
  return { listeners, caches, cacheStorage, fetchMock };
}

function fire(listeners, request) {
  let responded = null;
  listeners.fetch({ request, respondWith: (p) => (responded = p) });
  return responded;
}

const req = (url, extra = {}) => ({ url: `https://site.test${url}`, method: "GET", destination: "", mode: "cors", ...extra });

describe("service worker", () => {
  let sw;
  beforeEach(() => {
    sw = load();
  });

  it("leaves chapter pages to the browser", () => {
    const r = fire(sw.listeners, req("/api/v1/manga/pages/1/2/0001-a.webp", { destination: "image" }));
    expect(r).toBeNull();
    expect(sw.fetchMock).not.toHaveBeenCalled();
  });

  it("serves a cover from the cache without downloading it again", async () => {
    const cover = req("/api/v1/manga/covers/5.webp", { destination: "image" });
    await fire(sw.listeners, cover);
    await fire(sw.listeners, cover);
    expect(sw.fetchMock).toHaveBeenCalledTimes(1);
  });

  it("opens the app shell for an offline navigation", async () => {
    sw.fetchMock.mockRejectedValue(new Error("offline"));
    const cache = await sw.cacheStorage.open("manga-reader-cache-v2");
    cache.store.set("/index.html", { shell: true });
    const res = await fire(sw.listeners, req("/manga/5", { mode: "navigate" }));
    expect(res).toEqual({ shell: true });
  });

  it("deletes the old unlimited image cache on activate", async () => {
    await sw.cacheStorage.open("manga-reader-cache-v1");
    let done;
    sw.listeners.activate({ waitUntil: (p) => (done = p) });
    await done;
    expect(sw.cacheStorage.delete).toHaveBeenCalledWith("manga-reader-cache-v1");
  });
});
