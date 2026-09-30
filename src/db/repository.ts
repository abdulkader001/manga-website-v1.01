import { queryAll, queryOne, executeRun, getDb } from './database';

export interface MangaRow {
  id: number;
  title: string;
  slug: string;
  alt_titles?: string;
  description?: string;
  cover_image?: string;
  cover_url?: string;
  banner_image?: string;
  status?: string;
  type?: string;
  country?: string;
  author?: string;
  artist?: string;
  original_publisher?: string;
  genres?: string;
  categories?: string;
  tags?: string;
  views?: number;
  daily_views?: number;
  weekly_views?: number;
  monthly_views?: number;
  rating?: number;
  rating_count?: number;
  chapters_count?: number;
  last_chapter_title?: string;
  mangaupdates_url?: string;
  source_url?: string;
  source_id?: string;
  auto_scrape_enabled?: number;
  scrape_frequency?: string;
  scrape_interval_value?: number;
  scrape_interval_unit?: string;
  last_scraped_at?: string;
  next_scrape_at?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ChapterRow {
  id: number;
  manga_id: number;
  source_id: string;
  canonical_number: number;
  chapter_number: string;
  native_title?: string;
  title: string;
  chapter_title: string;
  source_chapter_url?: string;
  pages: string;
  raw_pages?: string;
  views?: number;
  release_date?: string;
  is_paid?: number;
  requires_login?: number;
  is_quarantined?: number;
  quarantine_reason?: string;
  created_at?: string;
  updated_at?: string;
}

// Convert SQLite Manga Row to Client Object
export function formatMangaRow(row: MangaRow): any {
  if (!row) return null;
  const genresArr = row.genres ? JSON.parse(row.genres) : [];
  const categoriesArr = row.categories ? JSON.parse(row.categories) : [];
  const tagsArr = row.tags ? JSON.parse(row.tags) : [];
  const altTitlesArr = row.alt_titles ? JSON.parse(row.alt_titles) : [];

  return {
    ...row,
    auto_scrape_enabled: Boolean(row.auto_scrape_enabled),
    genres: Array.isArray(genresArr) ? genresArr : [],
    categories: Array.isArray(categoriesArr) ? categoriesArr : [],
    tags: Array.isArray(tagsArr) ? tagsArr : [],
    alt_titles: Array.isArray(altTitlesArr) ? altTitlesArr : [],
    cover_url: row.cover_url || row.cover_image,
    views_formatted: formatNumber(row.views || 0),
  };
}

// Convert SQLite Chapter Row to Client Object
export function formatChapterRow(row: ChapterRow): any {
  if (!row) return null;
  const pagesArr = row.pages ? JSON.parse(row.pages) : [];
  const rawPagesArr = row.raw_pages ? JSON.parse(row.raw_pages) : [];

  return {
    ...row,
    is_paid: Boolean(row.is_paid),
    requires_login: Boolean(row.requires_login),
    is_quarantined: Boolean(row.is_quarantined),
    pages: Array.isArray(pagesArr) ? pagesArr : [],
    raw_pages: Array.isArray(rawPagesArr) ? rawPagesArr : [],
    views_formatted: formatNumber(row.views || 0),
  };
}

function formatNumber(num: number): string {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1).replace(/\.0$/, '')}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return String(num);
}

// --- MANGA REPOSITORY ---
export function getAllManga(): any[] {
  const rows = queryAll<MangaRow>('SELECT * FROM manga ORDER BY id DESC');
  return rows.map(formatMangaRow);
}

export function getMangaByIdOrSlug(idOrSlug: string | number): any | null {
  const isNum = !isNaN(Number(idOrSlug));
  let row: MangaRow | null = null;
  if (isNum) {
    row = queryOne<MangaRow>('SELECT * FROM manga WHERE id = ?', [Number(idOrSlug)]);
  } else {
    row = queryOne<MangaRow>('SELECT * FROM manga WHERE slug = ?', [String(idOrSlug)]);
  }
  return row ? formatMangaRow(row) : null;
}

export function saveManga(mangaData: any): any {
  const genresJson = JSON.stringify(mangaData.genres || []);
  const categoriesJson = JSON.stringify(mangaData.categories || []);
  const tagsJson = JSON.stringify(mangaData.tags || []);
  const altTitlesJson = JSON.stringify(mangaData.alt_titles || []);

  if (mangaData.id) {
    executeRun(
      `UPDATE manga SET
        title = ?, slug = ?, alt_titles = ?, description = ?, cover_image = ?, cover_url = ?,
        banner_image = ?, status = ?, type = ?, country = ?, author = ?, artist = ?,
        original_publisher = ?, genres = ?, categories = ?, tags = ?, views = ?,
        daily_views = ?, weekly_views = ?, monthly_views = ?, rating = ?, rating_count = ?,
        chapters_count = ?, last_chapter_title = ?, mangaupdates_url = ?, source_url = ?,
        source_id = ?, auto_scrape_enabled = ?, scrape_frequency = ?, scrape_interval_value = ?,
        scrape_interval_unit = ?, last_scraped_at = ?, next_scrape_at = ?, updated_at = datetime('now')
       WHERE id = ?`,
      [
        mangaData.title,
        mangaData.slug,
        altTitlesJson,
        mangaData.description || '',
        mangaData.cover_image || mangaData.cover_url || '',
        mangaData.cover_url || mangaData.cover_image || '',
        mangaData.banner_image || mangaData.cover_image || '',
        mangaData.status || 'ongoing',
        mangaData.type || 'manga',
        mangaData.country || 'JP',
        mangaData.author || '',
        mangaData.artist || '',
        mangaData.original_publisher || '',
        genresJson,
        categoriesJson,
        tagsJson,
        mangaData.views || 0,
        mangaData.daily_views || 0,
        mangaData.weekly_views || 0,
        mangaData.monthly_views || 0,
        mangaData.rating || 0,
        mangaData.rating_count || 0,
        mangaData.chapters_count || 0,
        mangaData.last_chapter_title || '',
        mangaData.mangaupdates_url || '',
        mangaData.source_url || '',
        mangaData.source_id || 'baozimh',
        mangaData.auto_scrape_enabled !== false ? 1 : 0,
        mangaData.scrape_frequency || 'weekly',
        mangaData.scrape_interval_value || 7,
        mangaData.scrape_interval_unit || 'days',
        mangaData.last_scraped_at || new Date().toISOString(),
        mangaData.next_scrape_at || new Date().toISOString(),
        mangaData.id,
      ]
    );
    return getMangaByIdOrSlug(mangaData.id);
  } else {
    const res = executeRun(
      `INSERT INTO manga (
        title, slug, alt_titles, description, cover_image, cover_url, banner_image,
        status, type, country, author, artist, original_publisher, genres, categories,
        tags, views, daily_views, weekly_views, monthly_views, rating, rating_count,
        chapters_count, last_chapter_title, mangaupdates_url, source_url, source_id,
        auto_scrape_enabled, scrape_frequency, scrape_interval_value, scrape_interval_unit,
        last_scraped_at, next_scrape_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        mangaData.title,
        mangaData.slug,
        altTitlesJson,
        mangaData.description || '',
        mangaData.cover_image || mangaData.cover_url || '',
        mangaData.cover_url || mangaData.cover_image || '',
        mangaData.banner_image || mangaData.cover_image || '',
        mangaData.status || 'ongoing',
        mangaData.type || 'manga',
        mangaData.country || 'JP',
        mangaData.author || '',
        mangaData.artist || '',
        mangaData.original_publisher || '',
        genresJson,
        categoriesJson,
        tagsJson,
        mangaData.views || 0,
        mangaData.daily_views || 0,
        mangaData.weekly_views || 0,
        mangaData.monthly_views || 0,
        mangaData.rating || 0,
        mangaData.rating_count || 0,
        mangaData.chapters_count || 0,
        mangaData.last_chapter_title || '',
        mangaData.mangaupdates_url || '',
        mangaData.source_url || '',
        mangaData.source_id || 'baozimh',
        mangaData.auto_scrape_enabled !== false ? 1 : 0,
        mangaData.scrape_frequency || 'weekly',
        mangaData.scrape_interval_value || 7,
        mangaData.scrape_interval_unit || 'days',
        mangaData.last_scraped_at || new Date().toISOString(),
        mangaData.next_scrape_at || new Date().toISOString(),
      ]
    );
    return getMangaByIdOrSlug(res.lastInsertRowid);
  }
}

export function deleteManga(id: number): boolean {
  executeRun('DELETE FROM manga WHERE id = ?', [id]);
  return true;
}

// --- CHAPTER REPOSITORY ---
export function getChaptersForManga(mangaId: number): any[] {
  const rows = queryAll<ChapterRow>(
    'SELECT * FROM chapters WHERE manga_id = ? ORDER BY canonical_number ASC',
    [mangaId]
  );
  return rows.map(formatChapterRow);
}

export function getChapterById(chapterId: number): any | null {
  const row = queryOne<ChapterRow>('SELECT * FROM chapters WHERE id = ?', [chapterId]);
  return row ? formatChapterRow(row) : null;
}

export function saveChapter(chData: any): any {
  const pagesJson = JSON.stringify(chData.pages || []);
  const rawPagesJson = JSON.stringify(chData.raw_pages || chData.pages || []);
  const canonicalNum = parseFloat(chData.chapter_number) || parseFloat(chData.canonical_number) || 0;

  if (chData.id && getChapterById(chData.id)) {
    executeRun(
      `UPDATE chapters SET
        manga_id = ?, source_id = ?, canonical_number = ?, chapter_number = ?, native_title = ?,
        title = ?, chapter_title = ?, source_chapter_url = ?, pages = ?, raw_pages = ?,
        views = ?, release_date = ?, is_paid = ?, requires_login = ?, is_quarantined = ?,
        quarantine_reason = ?, updated_at = datetime('now')
       WHERE id = ?`,
      [
        chData.manga_id,
        chData.source_id || 'baozimh',
        canonicalNum,
        String(chData.chapter_number || canonicalNum),
        chData.native_title || '',
        chData.title || `Chapter ${canonicalNum}`,
        chData.chapter_title || chData.title || `Chapter ${canonicalNum}`,
        chData.source_chapter_url || '',
        pagesJson,
        rawPagesJson,
        chData.views || 0,
        chData.release_date || new Date().toISOString(),
        chData.is_paid ? 1 : 0,
        chData.requires_login ? 1 : 0,
        chData.is_quarantined ? 1 : 0,
        chData.quarantine_reason || '',
        chData.id,
      ]
    );
    return getChapterById(chData.id);
  } else {
    // Check unique constraint (manga_id, canonical_number, source_id)
    const sourceId = chData.source_id || 'baozimh';
    const existing = queryOne<ChapterRow>(
      'SELECT id FROM chapters WHERE manga_id = ? AND canonical_number = ? AND source_id = ?',
      [chData.manga_id, canonicalNum, sourceId]
    );

    if (existing) {
      executeRun(
        `UPDATE chapters SET
          pages = ?, raw_pages = ?, release_date = ?, updated_at = datetime('now')
         WHERE id = ?`,
        [pagesJson, rawPagesJson, chData.release_date || new Date().toISOString(), existing.id]
      );
      return getChapterById(existing.id);
    }

    const res = executeRun(
      `INSERT INTO chapters (
        manga_id, source_id, canonical_number, chapter_number, native_title, title,
        chapter_title, source_chapter_url, pages, raw_pages, views, release_date,
        is_paid, requires_login, is_quarantined, quarantine_reason
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        chData.manga_id,
        sourceId,
        canonicalNum,
        String(chData.chapter_number || canonicalNum),
        chData.native_title || '',
        chData.title || `Chapter ${canonicalNum}`,
        chData.chapter_title || chData.title || `Chapter ${canonicalNum}`,
        chData.source_chapter_url || '',
        pagesJson,
        rawPagesJson,
        chData.views || 0,
        chData.release_date || new Date().toISOString(),
        chData.is_paid ? 1 : 0,
        chData.requires_login ? 1 : 0,
        chData.is_quarantined ? 1 : 0,
        chData.quarantine_reason || '',
      ]
    );
    return getChapterById(res.lastInsertRowid);
  }
}

// --- SOURCES & DOMAIN REGISTRY ---
export interface SourceRow {
  id: string;
  name: string;
  language: 'CN' | 'JP' | 'KR';
  parser_spec: string;
  parser_version: number;
  status: 'active' | 'broken';
  risk: string;
  notes?: string;
  created_at?: string;
  updated_at?: string;
}

export function getAllSources(): any[] {
  const sources = queryAll<SourceRow>('SELECT * FROM sources ORDER BY id ASC');
  return sources.map((s) => {
    const domains = queryAll<{ domain: string; is_primary: number }>(
      'SELECT domain, is_primary FROM source_domains WHERE source_id = ?',
      [s.id]
    );
    return {
      ...s,
      parser_spec: s.parser_spec ? JSON.parse(s.parser_spec) : {},
      domains: domains.map((d) => d.domain),
    };
  });
}

export function findSourceByDomain(domain: string): any | null {
  const cleanDomain = domain.toLowerCase().replace(/^https?:\/\//, '').split('/')[0].split(':')[0];
  const domRow = queryOne<{ source_id: string }>(
    'SELECT source_id FROM source_domains WHERE domain = ?',
    [cleanDomain]
  );
  if (!domRow) return null;
  const srcRow = queryOne<SourceRow>('SELECT * FROM sources WHERE id = ?', [domRow.source_id]);
  if (!srcRow) return null;

  return {
    ...srcRow,
    parser_spec: srcRow.parser_spec ? JSON.parse(srcRow.parser_spec) : {},
  };
}

export function addDomainToSource(sourceId: string, domain: string, isPrimary = false): boolean {
  const cleanDomain = domain.toLowerCase().replace(/^https?:\/\//, '').split('/')[0].split(':')[0];
  executeRun(
    `INSERT OR REPLACE INTO source_domains (domain, source_id, is_primary) VALUES (?, ?, ?)`,
    [cleanDomain, sourceId, isPrimary ? 1 : 0]
  );
  return true;
}

// --- USER & AUTH REPOSITORY ---
export function getUserByEmail(email: string): any | null {
  const row = queryOne('SELECT * FROM users WHERE email = ?', [email.trim().toLowerCase()]);
  if (!row) return null;
  return {
    ...row,
    is_main_admin: Boolean(row.is_main_admin),
    is_secondary_admin: Boolean(row.is_secondary_admin),
    is_under_18: Boolean(row.is_under_18),
    age_locked: Boolean(row.age_locked),
    profile_completed: Boolean(row.profile_completed),
  };
}

export function saveUser(userData: any): any {
  const email = userData.email.trim().toLowerCase();
  const existing = getUserByEmail(email);

  if (existing) {
    executeRun(
      `UPDATE users SET
        name = ?, username = ?, password = ?, role = ?, is_main_admin = ?, is_secondary_admin = ?,
        language = ?, gender = ?, birth_date = ?, age = ?, is_under_18 = ?, age_locked = ?,
        profile_completed = ?, profile_image = ?
       WHERE email = ?`,
      [
        userData.name || existing.name,
        userData.username || existing.username,
        userData.password || existing.password || '',
        userData.role || existing.role,
        userData.is_main_admin ? 1 : 0,
        userData.is_secondary_admin ? 1 : 0,
        userData.language || existing.language || 'en',
        userData.gender || existing.gender || '',
        userData.birth_date || existing.birth_date || '',
        userData.age ?? existing.age ?? null,
        userData.is_under_18 ? 1 : 0,
        userData.age_locked ? 1 : 0,
        userData.profile_completed !== false ? 1 : 0,
        userData.profile_image || existing.profile_image || '',
        email,
      ]
    );
    return getUserByEmail(email);
  } else {
    const res = executeRun(
      `INSERT INTO users (
        email, name, username, password, role, is_main_admin, is_secondary_admin, language,
        gender, birth_date, age, is_under_18, age_locked, profile_completed, profile_image
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        email,
        userData.name || email.split('@')[0],
        userData.username || email.split('@')[0],
        userData.password || '',
        userData.role || 'user',
        userData.is_main_admin ? 1 : 0,
        userData.is_secondary_admin ? 1 : 0,
        userData.language || 'en',
        userData.gender || '',
        userData.birth_date || '',
        userData.age ?? null,
        userData.is_under_18 ? 1 : 0,
        userData.age_locked ? 1 : 0,
        userData.profile_completed !== false ? 1 : 0,
        userData.profile_image || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150&auto=format&fit=crop&q=80',
      ]
    );
    return getUserByEmail(email);
  }
}

// --- BOOKMARKS & HISTORY ---
export function getBookmarksForUser(userId = 1): any[] {
  const rows = queryAll(`
    SELECT b.id as bookmark_id, b.added_at, m.*, c.id as ch_id, c.title as ch_title
    FROM bookmarks b
    JOIN manga m ON b.manga_id = m.id
    LEFT JOIN chapters c ON b.chapter_id = c.id
    WHERE b.user_id = ?
    ORDER BY b.added_at DESC
  `, [userId]);

  return rows.map((r: any) => {
    const formattedManga = formatMangaRow(r);
    const mangaChapters = getChaptersForManga(r.id);
    const latestChapter = mangaChapters.length > 0 ? mangaChapters[mangaChapters.length - 1] : null;

    return {
      id: r.bookmark_id,
      manga_id: r.id,
      chapter_id: r.ch_id,
      manga_title: r.title,
      chapter_title: r.ch_title,
      added_at: r.added_at,
      created_at: r.added_at,
      latest_chapter: latestChapter,
      manga: {
        ...formattedManga,
        latest_chapter: latestChapter,
      },
    };
  });
}

export function toggleBookmark(userId: number, mangaId: number, chapterId?: number): boolean {
  const existing = queryOne(
    'SELECT id FROM bookmarks WHERE user_id = ? AND manga_id = ?',
    [userId, mangaId]
  );
  if (existing) {
    executeRun('DELETE FROM bookmarks WHERE id = ?', [existing.id]);
    return false;
  } else {
    executeRun(
      'INSERT INTO bookmarks (user_id, manga_id, chapter_id, added_at) VALUES (?, ?, ?, datetime("now"))',
      [userId, mangaId, chapterId || null]
    );
    return true;
  }
}

export function getReadingHistory(userId = 1): any[] {
  const rows = queryAll(`
    SELECT h.id as history_id, h.read_at, m.id as m_id, m.title as m_title, c.id as c_id, c.title as c_title
    FROM reading_history h
    JOIN manga m ON h.manga_id = m.id
    JOIN chapters c ON h.chapter_id = c.id
    WHERE h.user_id = ?
    ORDER BY h.read_at DESC
    LIMIT 100
  `, [userId]);

  return rows.map((r: any) => ({
    id: r.history_id,
    manga_id: r.m_id,
    chapter_id: r.c_id,
    manga_title: r.m_title,
    chapter_title: r.c_title,
    last_read_at: r.read_at,
    read_at: r.read_at,
    created_at: r.read_at,
    manga: getMangaByIdOrSlug(r.m_id),
    chapter: getChapterById(r.c_id),
  }));
}

export function recordHistory(userId: number, mangaId: number, chapterId: number): void {
  executeRun(
    'DELETE FROM reading_history WHERE user_id = ? AND manga_id = ? AND chapter_id = ?',
    [userId, mangaId, chapterId]
  );
  executeRun(
    'INSERT INTO reading_history (user_id, manga_id, chapter_id, read_at) VALUES (?, ?, ?, datetime("now"))',
    [userId, mangaId, chapterId]
  );
}

// --- PAGE TRANSLATIONS REPOSITORY ---
export interface PageTranslationRow {
  id?: number;
  chapter_id: number;
  page_index: number;
  raw_image_url: string;
  translated_image_path: string;
  detected_boxes?: string;
  validation_status?: string;
  pipeline_version: string;
  created_at?: string;
}

export function savePageTranslation(data: PageTranslationRow): any {
  const boxesJson = typeof data.detected_boxes === 'string' ? data.detected_boxes : JSON.stringify(data.detected_boxes || []);
  const existing = queryOne<PageTranslationRow>(
    'SELECT id FROM page_translations WHERE chapter_id = ? AND page_index = ? AND pipeline_version = ?',
    [data.chapter_id, data.page_index, data.pipeline_version]
  );

  if (existing) {
    executeRun(
      `UPDATE page_translations SET
        raw_image_url = ?, translated_image_path = ?, detected_boxes = ?, validation_status = ?
       WHERE id = ?`,
      [data.raw_image_url, data.translated_image_path, boxesJson, data.validation_status || 'valid', existing.id]
    );
    return queryOne('SELECT * FROM page_translations WHERE id = ?', [existing.id]);
  } else {
    const res = executeRun(
      `INSERT INTO page_translations (
        chapter_id, page_index, raw_image_url, translated_image_path, detected_boxes, validation_status, pipeline_version
       ) VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        data.chapter_id,
        data.page_index,
        data.raw_image_url,
        data.translated_image_path,
        boxesJson,
        data.validation_status || 'valid',
        data.pipeline_version,
      ]
    );
    return queryOne('SELECT * FROM page_translations WHERE id = ?', [res.lastInsertRowid]);
  }
}

export function getPageTranslations(chapterId: number, pipelineVersion = 'v1'): PageTranslationRow[] {
  return queryAll<PageTranslationRow>(
    'SELECT * FROM page_translations WHERE chapter_id = ? AND pipeline_version = ? ORDER BY page_index ASC',
    [chapterId, pipelineVersion]
  );
}

// --- SITE SETTINGS & CONFIG ---
export function getSiteSetting(key: string, defaultValue = ''): string {
  const row = queryOne<{ value: string }>('SELECT value FROM site_settings WHERE key = ?', [key]);
  return row ? row.value : defaultValue;
}

export function setSiteSetting(key: string, value: string): void {
  executeRun('INSERT OR REPLACE INTO site_settings (key, value) VALUES (?, ?)', [key, value]);
}

// --- SCRAPE RUNS LOGS REPOSITORY ---
export function recordScrapeRunStart(seriesId: number | null, sourceId: string, runType: 'auto' | 'manual' = 'auto'): number {
  const res = executeRun(
    `INSERT INTO scrape_runs (series_id, source_id, run_type, status, chapters_found, chapters_added, started_at)
     VALUES (?, ?, ?, 'running', 0, 0, datetime('now'))`,
    [seriesId, sourceId || 'baozimh', runType]
  );
  return res.lastInsertRowid;
}

export function recordScrapeRunFinish(
  runId: number,
  status: 'success' | 'failed' | 'partial',
  chaptersFound: number,
  chaptersAdded: number,
  errorMessage?: string
): void {
  executeRun(
    `UPDATE scrape_runs SET
      status = ?, chapters_found = ?, chapters_added = ?, error_message = ?, finished_at = datetime('now')
     WHERE id = ?`,
    [status, chaptersFound, chaptersAdded, errorMessage || null, runId]
  );
}

export function getRecentScrapeRuns(limit = 50): any[] {
  return queryAll(`
    SELECT r.*, m.title as series_title
    FROM scrape_runs r
    LEFT JOIN manga m ON r.series_id = m.id
    ORDER BY r.id DESC
    LIMIT ?
  `, [limit]);
}

export function getMangaDueForScraping(): any[] {
  const nowStr = new Date().toISOString();
  const rows = queryAll<MangaRow>(
    `SELECT * FROM manga
     WHERE auto_scrape_enabled = 1
       AND (next_scrape_at IS NULL OR next_scrape_at <= datetime('now') OR next_scrape_at <= ?)
     ORDER BY next_scrape_at ASC`,
    [nowStr]
  );
  return rows.map(formatMangaRow);
}

export function seedInitialMangaAndChapters(seedMangaList: any[], seedChaptersList: any[]): void {
  const count = queryOne<{ count: number }>('SELECT COUNT(*) as count FROM manga');
  if (count && count.count > 0) return;

  console.log('[DB Migration] Seeding initial manga and chapters into SQLite...');
  for (const m of seedMangaList) {
    saveManga(m);
  }

  for (const c of seedChaptersList) {
    saveChapter({
      ...c,
      canonical_number: parseFloat(c.chapter_number) || 1,
      source_id: 'baozimh',
    });
  }
}

// --- DATABASE DUMP EXPORT & IMPORT ---
export function exportFullDatabaseDump(): Record<string, any> {
  const manga = queryAll('SELECT * FROM manga');
  const chapters = queryAll('SELECT * FROM chapters');
  const sources = queryAll('SELECT * FROM sources');
  const sourceDomains = queryAll('SELECT * FROM source_domains');
  const siteSettings = queryAll('SELECT * FROM site_settings');
  const pageTranslations = queryAll('SELECT * FROM page_translations');
  const scrapeRuns = queryAll('SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 100');

  return {
    version: '1.0',
    exported_at: new Date().toISOString(),
    manga,
    chapters,
    sources,
    source_domains: sourceDomains,
    site_settings: siteSettings,
    page_translations: pageTranslations,
    scrape_runs: scrapeRuns,
  };
}

export function importFullDatabaseDump(dump: Record<string, any>): { success: boolean; importedManga: number; importedChapters: number } {
  if (!dump || typeof dump !== 'object') {
    throw new Error('Invalid database dump payload.');
  }

  let importedManga = 0;
  let importedChapters = 0;

  if (Array.isArray(dump.manga)) {
    for (const m of dump.manga) {
      saveManga(m);
      importedManga++;
    }
  }

  if (Array.isArray(dump.chapters)) {
    for (const c of dump.chapters) {
      saveChapter(c);
      importedChapters++;
    }
  }

  return { success: true, importedManga, importedChapters };
}
