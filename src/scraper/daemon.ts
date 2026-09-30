import {
  getMangaDueForScraping,
  getAllManga,
  saveManga,
  saveChapter,
  getChaptersForManga,
  recordScrapeRunStart,
  recordScrapeRunFinish,
  findSourceByDomain,
} from '../db/repository';
import { scrapeChaptersFromSource } from './engine';

let daemonInterval: NodeJS.Timeout | null = null;
let isScraping = false;

export function calculateNextScrapeDate(unit = 'days', val = 7): string {
  const intervalMs = unit === 'hours' ? val * 3600000 : val * 86400000;
  return new Date(Date.now() + intervalMs).toISOString();
}

export async function processSeriesScrape(manga: any, runType: 'auto' | 'manual' = 'auto'): Promise<{
  success: boolean;
  chaptersFound: number;
  chaptersAdded: number;
  message: string;
}> {
  const sourceUrl = manga.source_url || '';
  if (!sourceUrl) {
    return { success: false, chaptersFound: 0, chaptersAdded: 0, message: 'Series has no source URL set.' };
  }

  const detectedSource = findSourceByDomain(sourceUrl);
  const sourceId = detectedSource ? detectedSource.id : manga.source_id || 'baozimh';
  const runId = recordScrapeRunStart(manga.id, sourceId, runType);

  try {
    const existingChapters = getChaptersForManga(manga.id);
    const existingNums = new Set(existingChapters.map((c) => String(c.canonical_number)));

    const extraction = await scrapeChaptersFromSource(sourceUrl, detectedSource?.parser_spec, sourceId);
    let newlyAdded = 0;

    for (const ch of extraction.chapters) {
      if (!existingNums.has(String(ch.canonical_number))) {
        saveChapter({
          manga_id: manga.id,
          source_id: sourceId,
          canonical_number: ch.canonical_number,
          chapter_number: ch.chapter_number,
          native_title: ch.native_title,
          title: ch.title,
          chapter_title: ch.chapter_title,
          source_chapter_url: ch.source_chapter_url,
          pages: ch.pages,
          release_date: ch.release_date,
        });
        newlyAdded++;
      }
    }

    const updatedChapters = getChaptersForManga(manga.id);
    const totalChaptersCount = updatedChapters.length;
    const lastChTitle = totalChaptersCount > 0 ? updatedChapters[totalChaptersCount - 1].title : manga.last_chapter_title;

    const unit = manga.scrape_interval_unit || 'days';
    const val = manga.scrape_interval_value || 7;
    const lastScrapedAt = new Date().toISOString();
    const nextScrapeAt = calculateNextScrapeDate(unit, val);

    saveManga({
      ...manga,
      chapters_count: totalChaptersCount,
      last_chapter_title: lastChTitle,
      last_scraped_at: lastScrapedAt,
      next_scrape_at: nextScrapeAt,
    });

    recordScrapeRunFinish(runId, 'success', extraction.total_chapters_detected, newlyAdded);

    return {
      success: true,
      chaptersFound: extraction.total_chapters_detected,
      chaptersAdded: newlyAdded,
      message: `Scrape completed for "${manga.title}": ${extraction.total_chapters_detected} detected, ${newlyAdded} new chapters added.`,
    };
  } catch (err: any) {
    console.error(`[Scraper Daemon] Error scraping "${manga.title}":`, err);
    recordScrapeRunFinish(runId, 'failed', 0, 0, err.message || 'Scrape execution failed');
    return {
      success: false,
      chaptersFound: 0,
      chaptersAdded: 0,
      message: `Scrape failed for "${manga.title}": ${err.message || 'Unknown error'}`,
    };
  }
}

export async function runScraperTick(): Promise<void> {
  if (isScraping) return;
  isScraping = true;

  try {
    const dueManga = getMangaDueForScraping();
    if (dueManga.length > 0) {
      console.log(`[Scraper Daemon] Ticker cycle starting: ${dueManga.length} series due for auto-scraping.`);
      for (const m of dueManga) {
        await processSeriesScrape(m, 'auto');
      }
    }
  } catch (e) {
    console.error('[Scraper Daemon] Ticker error:', e);
  } finally {
    isScraping = false;
  }
}

export async function runAllSeriesScrape(): Promise<{ totalProcessed: number; totalNewChapters: number }> {
  const allManga = getAllManga().filter((m) => m.auto_scrape_enabled);
  let totalProcessed = 0;
  let totalNewChapters = 0;

  for (const manga of allManga) {
    const res = await processSeriesScrape(manga, 'manual');
    if (res.success) {
      totalProcessed++;
      totalNewChapters += res.chaptersAdded;
    }
  }

  return { totalProcessed, totalNewChapters };
}

export function startScraperDaemon(intervalMs = 60000): void {
  if (daemonInterval) return;

  console.log(`[Scraper Daemon] Daemon initialized & active (ticker interval: ${intervalMs / 1000}s).`);
  // Run an immediate initial tick after boot
  setTimeout(() => {
    runScraperTick().catch((e) => console.warn('[Scraper Daemon] Initial tick warning:', e));
  }, 5000);

  daemonInterval = setInterval(() => {
    runScraperTick().catch((e) => console.warn('[Scraper Daemon] Tick warning:', e));
  }, intervalMs);
}

export function stopScraperDaemon(): void {
  if (daemonInterval) {
    clearInterval(daemonInterval);
    daemonInterval = null;
    console.log('[Scraper Daemon] Daemon stopped.');
  }
}
