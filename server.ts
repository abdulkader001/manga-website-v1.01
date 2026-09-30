import express, { type Request, type Response } from 'express';
import http from 'node:http';
import https from 'node:https';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

// Front door for the web app: serves the React UI (Vite in development, the
// built `dist/` in production) and reverse-proxies every backend path to the
// FastAPI service. All data, auth, scraping and security logic lives in
// backend_fastapi — this process holds no state of its own.

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PORT = parseInt(process.env.WEB_PORT || '3000', 10);
const isDev = process.env.NODE_ENV !== 'production';
const BACKEND_URL = new URL(process.env.BACKEND_URL || 'http://127.0.0.1:8000');
const PUBLIC_API_BASE = process.env.API_BASE || '/api/v1';

const PROXIED_PREFIXES = ['/api/', '/sitemap.xml', '/rss.xml', '/feed.xml'];

const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

const upstreamAgent = (BACKEND_URL.protocol === 'https:' ? https : http) as typeof http;

function isProxiedPath(url: string): boolean {
  return PROXIED_PREFIXES.some((prefix) => url === prefix.replace(/\/$/, '') || url.startsWith(prefix));
}

function proxyToBackend(req: Request, res: Response): void {
  const headers: http.OutgoingHttpHeaders = {};
  for (const [name, value] of Object.entries(req.headers)) {
    if (value !== undefined && !HOP_BY_HOP_HEADERS.has(name.toLowerCase())) {
      headers[name] = value;
    }
  }

  // Append (never replace) the peer address, exactly like nginx's
  // $proxy_add_x_forwarded_for: the backend trusts only the LAST hop, and only
  // when the immediate peer (this gateway) is an internal address.
  const peer = req.socket.remoteAddress || '';
  const prior = req.headers['x-forwarded-for'];
  headers['x-forwarded-for'] = prior ? `${prior}, ${peer}` : peer;
  headers['x-forwarded-proto'] = (req.socket as { encrypted?: boolean }).encrypted ? 'https' : 'http';
  if (req.headers.host) headers['x-forwarded-host'] = req.headers.host;

  const upstream = upstreamAgent.request(
    {
      protocol: BACKEND_URL.protocol,
      hostname: BACKEND_URL.hostname,
      port: BACKEND_URL.port || (BACKEND_URL.protocol === 'https:' ? 443 : 80),
      method: req.method,
      path: req.originalUrl,
      headers,
    },
    (upstreamRes) => {
      const responseHeaders: http.OutgoingHttpHeaders = {};
      for (const [name, value] of Object.entries(upstreamRes.headers)) {
        if (value !== undefined && !HOP_BY_HOP_HEADERS.has(name.toLowerCase())) {
          responseHeaders[name] = value;
        }
      }
      res.writeHead(upstreamRes.statusCode || 502, responseHeaders);
      upstreamRes.pipe(res);
    }
  );

  upstream.setTimeout(120_000, () => upstream.destroy(new Error('upstream timeout')));
  upstream.on('error', (err) => {
    console.error(`[gateway] ${req.method} ${req.originalUrl} -> backend failed: ${err.message}`);
    if (!res.headersSent) {
      res.status(502).json({
        success: false,
        error: { code: 'BACKEND_UNAVAILABLE', message: 'The API service is unavailable. Please try again shortly.' },
      });
    } else {
      res.destroy();
    }
  });

  req.pipe(upstream);
}

const app = express();
app.disable('x-powered-by');

app.use((_req, res, next) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'SAMEORIGIN');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  res.setHeader('Permissions-Policy', 'geolocation=(), microphone=(), camera=()');
  next();
});

app.use((req, res, next) => {
  if (isProxiedPath(req.path)) {
    proxyToBackend(req, res);
    return;
  }
  next();
});

app.get('/config.json', (_req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.json({ apiBase: PUBLIC_API_BASE });
});

async function startServer() {
  const distIndex = path.resolve(__dirname, 'dist', 'index.html');
  const useVite = isDev || !fs.existsSync(distIndex);

  if (useVite) {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
    app.use('*', async (req, res, next) => {
      try {
        const template = fs.readFileSync(path.resolve(__dirname, 'index.html'), 'utf-8');
        const html = await vite.transformIndexHtml(req.originalUrl, template);
        res.status(200).set({ 'Content-Type': 'text/html' }).end(html);
      } catch (e) {
        vite.ssrFixStacktrace(e as Error);
        next(e);
      }
    });
  } else {
    app.use(express.static(path.resolve(__dirname, 'dist'), { index: false }));
    app.get('*', (_req, res) => {
      res.sendFile(distIndex);
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`[Manga Reader] Web gateway on http://0.0.0.0:${PORT} -> API ${BACKEND_URL.origin}`);
  });
}

startServer().catch((err) => {
  console.error('[Manga Reader] Failed to start server:', err);
  process.exit(1);
});
