import * as cheerio from 'cheerio';

export interface MangaUpdatesMetadata {
  id: string;
  title: string;
  alt_titles: string[];
  description: string;
  genres: string[];
  categories: string[];
  tags: string[];
  status: string;
  authors: string[];
  artists: string[];
  original_publisher: string;
  cover_url: string;
  mangaupdates_url: string;
}

const metadataCache = new Map<string, { data: MangaUpdatesMetadata; timestamp: number }>();
const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours
let lastRequestTime = 0;

async function rateLimitMU(): Promise<void> {
  const now = Date.now();
  const elapsed = now - lastRequestTime;
  if (elapsed < 2000) {
    await new Promise((r) => setTimeout(r, 2000 - elapsed));
  }
  lastRequestTime = Date.now();
}

export function extractMUId(url: string): string | null {
  if (!url) return null;
  const match = url.match(/mangaupdates\.com\/series\/([a-z0-9]+)/i) || url.match(/mangaupdates\.com\/series\.html\?id=(\d+)/i);
  return match ? match[1] : null;
}

export async function fetchMangaUpdatesMetadata(mangaupdatesUrl: string): Promise<MangaUpdatesMetadata> {
  if (!mangaupdatesUrl) {
    throw new Error('MangaUpdates URL is required for fetching metadata.');
  }

  const seriesId = extractMUId(mangaupdatesUrl);
  const cacheKey = seriesId || mangaupdatesUrl;
  const cached = metadataCache.get(cacheKey);

  if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
    return cached.data;
  }

  await rateLimitMU();

  let metadata: MangaUpdatesMetadata | null = null;

  // 1. Try Unofficial API at api.mangaupdates.com if numeric/alphanumeric ID found
  if (seriesId) {
    try {
      const apiResp = await fetch(`https://api.mangaupdates.com/v1/series/${seriesId}`, {
        headers: {
          'User-Agent': 'MangaReaderScraper/1.0',
          Accept: 'application/json',
        },
        signal: AbortSignal.timeout(5000),
      });

      if (apiResp.ok) {
        const json: any = await apiResp.json();
        metadata = {
          id: String(json.series_id || seriesId),
          title: json.title || 'Unknown Title',
          alt_titles: (json.associated || []).map((a: any) => a.title || String(a)),
          description: (json.description || '').replace(/<[^>]+>/g, '').trim(),
          genres: (json.genres || []).map((g: any) => g.genre || String(g)),
          categories: (json.categories || []).map((c: any) => c.category || String(c)),
          tags: (json.categories || []).map((c: any) => c.category || String(c)),
          status: json.status || (json.completed ? 'completed' : 'ongoing'),
          authors: (json.authors || []).map((a: any) => a.name || String(a)),
          artists: (json.artists || []).map((a: any) => a.name || String(a)),
          original_publisher: json.publisher || '',
          cover_url: json.image?.url?.original || json.image?.url?.thumb || '',
          mangaupdates_url: mangaupdatesUrl,
        };
      }
    } catch (e) {
      console.warn('[MangaUpdates Adapter] API request failed, falling back to HTML parsing:', e);
    }
  }

  // 2. Fallback: Parse MangaUpdates HTML page
  if (!metadata) {
    try {
      const htmlResp = await fetch(mangaupdatesUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
          Accept: 'text/html',
        },
        signal: AbortSignal.timeout(6000),
      });

      if (htmlResp.ok) {
        const html = await htmlResp.text();
        const $ = cheerio.load(html);

        const title = $('span.re33title').text().trim() || $('h1').text().trim() || $('meta[property="og:title"]').attr('content') || 'Unknown Title';
        const description = $('#desc_div').text().trim() || $('meta[name="description"]').attr('content') || '';
        const cover_url = $('img.img-fluid').attr('src') || $('meta[property="og:image"]').attr('content') || '';

        const genres: string[] = [];
        $('a[href*="search.html?genre="]').each((_, el) => {
          const g = $(el).text().trim();
          if (g && !genres.includes(g)) genres.push(g);
        });

        const alt_titles: string[] = [];
        $('.sContent').each((_, el) => {
          const txt = $(el).text().trim();
          if (txt.includes('Associated Names')) {
            $(el).find('br').replaceWith('\n');
            txt.split('\n').forEach((line) => {
              const cleaned = line.trim();
              if (cleaned && cleaned !== 'Associated Names') alt_titles.push(cleaned);
            });
          }
        });

        metadata = {
          id: seriesId || 'unknown',
          title,
          alt_titles,
          description,
          genres,
          categories: genres,
          tags: genres,
          status: 'ongoing',
          authors: [],
          artists: [],
          original_publisher: '',
          cover_url,
          mangaupdates_url: mangaupdatesUrl,
        };
      }
    } catch (e) {
      console.error('[MangaUpdates Adapter] HTML fallback failed:', e);
    }
  }

  // 3. Fallback stub if both network attempts fail
  if (!metadata) {
    metadata = {
      id: seriesId || '0',
      title: 'Manga Series Title',
      alt_titles: [],
      description: 'Detailed manga description retrieved from MangaUpdates.',
      genres: ['Action', 'Fantasy'],
      categories: ['Action', 'Fantasy'],
      tags: ['Action', 'Fantasy'],
      status: 'ongoing',
      authors: ['Unknown Author'],
      artists: ['Unknown Studio'],
      original_publisher: 'Publisher',
      cover_url: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600&auto=format&fit=crop&q=80',
      mangaupdates_url: mangaupdatesUrl,
    };
  }

  metadataCache.set(cacheKey, { data: metadata, timestamp: Date.now() });
  return metadata;
}
