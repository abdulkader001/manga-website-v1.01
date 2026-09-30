import * as cheerio from 'cheerio';
import iconv from 'iconv-lite';
import crypto from 'crypto';
import sharp from 'sharp';
import {
  ParserSpec,
  RequestProfile,
  ScrapedChapter,
  ChapterExtractionResult,
  CharacterEncoding,
} from './types';

// ==========================================
// E1. HTTP FETCHER (SSRF Check, Robots, Charsets, CookieJar)
// ==========================================

const domainCookieJars = new Map<string, Map<string, string>>();

export function isPrivateIp(hostname: string): boolean {
  if (
    hostname === 'localhost' ||
    hostname === '127.0.0.1' ||
    hostname === '0.0.0.0' ||
    hostname === '::1' ||
    hostname.startsWith('10.') ||
    hostname.startsWith('192.168.') ||
    hostname.startsWith('169.254.')
  ) {
    return true;
  }
  const parts = hostname.split('.').map(Number);
  if (parts.length === 4 && parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) {
    return true;
  }
  return false;
}

export async function fetchWithProfile(
  targetUrl: string,
  profile: RequestProfile
): Promise<{ html: string; statusCode: number; finalUrl: string }> {
  const parsedUrl = new URL(targetUrl);
  if (isPrivateIp(parsedUrl.hostname)) {
    throw new Error(`[SSRF Blocked] Refusing to fetch private/internal target ${parsedUrl.hostname}`);
  }

  // Cookie jar management
  const domain = parsedUrl.hostname;
  if (!domainCookieJars.has(domain)) {
    domainCookieJars.set(domain, new Map());
  }
  const jar = domainCookieJars.get(domain)!;
  const cookieHeader = Array.from(jar.entries())
    .map(([k, v]) => `${k}=${v}`)
    .join('; ');

  const headers: Record<string, string> = {
    'User-Agent':
      profile.headers['User-Agent'] ||
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': profile.headers['Accept-Language'] || 'en-US,en;q=0.9,ko;q=0.8,ja;q=0.7,zh;q=0.6',
    Referer: profile.headers['Referer'] || `${parsedUrl.protocol}//${parsedUrl.host}/`,
    ...(cookieHeader ? { Cookie: cookieHeader } : {}),
  };

  const controller = new AbortController();
  const timeoutMs = profile.timeoutMs || 8000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const resp = await fetch(targetUrl, {
      headers,
      signal: controller.signal,
    });
    clearTimeout(timer);

    // Save set-cookie headers
    const setCookie = resp.headers.get('set-cookie');
    if (setCookie) {
      const parts = setCookie.split(';');
      const [kv] = parts;
      if (kv && kv.includes('=')) {
        const [k, v] = kv.split('=');
        jar.set(k.trim(), v.trim());
      }
    }

    const arrayBuffer = await resp.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);

    // Charset detection & decoding
    let encoding: CharacterEncoding = profile.encoding || 'utf-8';
    const contentType = resp.headers.get('content-type') || '';
    if (contentType.toLowerCase().includes('euc-kr')) {
      encoding = 'euc-kr';
    } else if (contentType.toLowerCase().includes('gbk') || contentType.toLowerCase().includes('gb18030')) {
      encoding = 'gbk';
    }

    let html = '';
    if (encoding === 'utf-8') {
      html = buffer.toString('utf-8');
    } else {
      html = iconv.decode(buffer, encoding);
    }

    return {
      html,
      statusCode: resp.status,
      finalUrl: resp.url || targetUrl,
    };
  } catch (err: any) {
    clearTimeout(timer);
    throw new Error(`HttpFetcher failed for ${targetUrl}: ${err.message}`);
  }
}

// ==========================================
// E2. SELECTOR ENGINE & JSON-STATE EXTRACTOR
// ==========================================

export function extractJsonState(html: string, kind: string, jsonPath?: string): any {
  if (kind === 'none' || !kind) return null;

  const $ = cheerio.load(html);
  let rawJson = '';

  if (kind === 'next_data') {
    rawJson = $('#__NEXT_DATA__').html() || '';
  } else if (kind === 'nuxt') {
    const script = $('script:contains("__NUXT__")').html() || '';
    const match = script.match(/window\.__NUXT__\s*=\s*(\{.+?\});?/s);
    if (match) rawJson = match[1];
  } else if (kind === 'initial_state') {
    const script = $('script:contains("__INITIAL_STATE__")').html() || '';
    const match = script.match(/window\.__INITIAL_STATE__\s*=\s*(\{.+?\});?/s);
    if (match) rawJson = match[1];
  } else if (kind === 'viewer_config') {
    const script = $('script:contains("viewerConfig")').html() || '';
    const match = script.match(/viewerConfig\s*=\s*(\{.+?\});?/s);
    if (match) rawJson = match[1];
  }

  if (!rawJson) return null;

  try {
    let parsed = JSON.parse(rawJson);
    if (jsonPath) {
      const keys = jsonPath.split('.');
      for (const k of keys) {
        if (parsed && typeof parsed === 'object' && k in parsed) {
          parsed = parsed[k];
        } else {
          return null;
        }
      }
    }
    return parsed;
  } catch {
    return null;
  }
}

export function extractAttributeWithFallback($el: cheerio.Cheerio<any>): string {
  const fallbackAttrs = ['data-src', 'data-original', 'src', 'data-url', 'srcset'];
  for (const attr of fallbackAttrs) {
    const val = $el.attr(attr);
    if (val && typeof val === 'string' && val.trim().length > 0) {
      // If srcset, pick first entry
      if (attr === 'srcset') {
        const firstSrc = val.split(',')[0].trim().split(' ')[0];
        if (firstSrc) return firstSrc;
      }
      return val.trim();
    }
  }
  return '';
}

// ==========================================
// E3. CHAPTER NORMALIZER
// ==========================================

export function parseCanonicalChapterNumber(rawStr: string): number {
  return normalizeChapterNumber(rawStr);
}

export function normalizeChapterNumber(rawStr: string): number {
  if (!rawStr) return 0;
  const clean = rawStr.trim().toLowerCase();

  // Suffix/Keyword map
  if (/prologue|프롤로그|序章|序/i.test(clean)) return 0.01;
  if (/extra|side story|특별편|외전|番外編/i.test(clean)) return 0.5;

  // CN: /第?\s*(\d+(?:\.\d+)?)\s*[話话回]/
  const cnMatch = clean.match(/第?\s*(\d+(?:\.\d+)?)\s*[話话回章]/);
  if (cnMatch && cnMatch[1]) return parseFloat(cnMatch[1]);

  // KR: /(\d+(?:\.\d+)?)\s*화/
  const krMatch = clean.match(/(\d+(?:\.\d+)?)\s*화/);
  if (krMatch && krMatch[1]) return parseFloat(krMatch[1]);

  // JP: /第(\d+(?:\.\d+)?)[話话]/
  const jpMatch = clean.match(/第(\d+(?:\.\d+)?)[話话]/);
  if (jpMatch && jpMatch[1]) return parseFloat(jpMatch[1]);

  // Generic: /#?\s*(\d+(?:\.\d+)?)/
  const genMatch = clean.match(/(?:ch\.?|chapter|ep|episode|#)?\s*(\d+(?:\.\d+)?)/i);
  if (genMatch && genMatch[1]) return parseFloat(genMatch[1]);

  return 1;
}

// ==========================================
// E4. RATE LIMITER (Token Bucket)
// ==========================================

const rateLimiterStore = new Map<string, number>();

export async function enforceRateLimit(domain: string, intervalMs = 1000): Promise<void> {
  const lastTime = rateLimiterStore.get(domain) || 0;
  const now = Date.now();
  const diff = now - lastTime;

  if (diff < intervalMs) {
    const waitTime = intervalMs - diff;
    await new Promise((resolve) => setTimeout(resolve, waitTime));
  }
  rateLimiterStore.set(domain, Date.now());
}

// ==========================================
// E5. WATERMARK STORE
// ==========================================

export function computeHtmlWatermark(html: string): string {
  return crypto.createHash('sha256').update(html).digest('hex');
}

// ==========================================
// E6. IMAGE PIPELINE (Download -> Magic Check -> WebP)
// ==========================================

export async function processAndEncodeImage(
  imageUrl: string,
  refererUrl: string
): Promise<{ buffer: Buffer; mimeType: string }> {
  const resp = await fetch(imageUrl, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
      Referer: refererUrl,
    },
  });

  if (!resp.ok) {
    throw new Error(`Failed to fetch chapter image: ${resp.status}`);
  }

  const arrayBuffer = await resp.arrayBuffer();
  const inputBuffer = Buffer.from(arrayBuffer);

  // Magic byte check
  const isJpg = inputBuffer[0] === 0xff && inputBuffer[1] === 0xd8;
  const isPng = inputBuffer[0] === 0x89 && inputBuffer[1] === 0x50;
  const isGif = inputBuffer[0] === 0x47 && inputBuffer[1] === 0x49;
  const isWebp = inputBuffer[8] === 0x57 && inputBuffer[9] === 0x45;

  if (!isJpg && !isPng && !isGif && !isWebp) {
    throw new Error('Invalid image file header (magic byte mismatch)');
  }

  // Convert to WebP via Sharp
  const webpBuffer = await sharp(inputBuffer)
    .webp({ quality: 85 })
    .toBuffer();

  return {
    buffer: webpBuffer,
    mimeType: 'image/webp',
  };
}

// ==========================================
// E7. HEALTH PROBE & RUN LOGGER
// ==========================================

export async function runHealthProbe(spec: ParserSpec): Promise<{ sourceId: string; ok: boolean; message: string }> {
  try {
    const testUrl = spec.urlPatterns.series.replace('<slug>', 'test').replace('<id>', '1');
    const { statusCode } = await fetchWithProfile(testUrl, spec.requestProfile);
    return {
      sourceId: spec.sourceId,
      ok: statusCode < 500,
      message: `HTTP ${statusCode}`,
    };
  } catch (err: any) {
    return {
      sourceId: spec.sourceId,
      ok: false,
      message: err.message || 'Probe error',
    };
  }
}
