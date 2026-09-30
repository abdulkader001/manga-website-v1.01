import initSqlJs, { Database as SqlJsDatabase } from 'sql.js';
import fs from 'fs';
import path from 'path';

const DB_DIR = path.resolve(process.cwd(), 'data');
const DB_FILE = path.resolve(DB_DIR, 'manga_reader.sqlite');

let dbInstance: SqlJsDatabase | null = null;

export function getDb(): SqlJsDatabase {
  if (!dbInstance) {
    throw new Error('Database not initialized. Call initDatabase() first.');
  }
  return dbInstance;
}

export function saveDb(): void {
  if (!dbInstance) return;
  try {
    if (!fs.existsSync(DB_DIR)) {
      fs.mkdirSync(DB_DIR, { recursive: true });
    }
    const data = dbInstance.export();
    const buffer = Buffer.from(data);
    fs.writeFileSync(DB_FILE, buffer);
  } catch (err) {
    console.error('[DB] Error saving database to disk:', err);
  }
}

export async function initDatabase(): Promise<SqlJsDatabase> {
  if (dbInstance) return dbInstance;

  const SQL = await initSqlJs();

  if (!fs.existsSync(DB_DIR)) {
    fs.mkdirSync(DB_DIR, { recursive: true });
  }

  if (fs.existsSync(DB_FILE)) {
    const fileBuffer = fs.readFileSync(DB_FILE);
    dbInstance = new SQL.Database(fileBuffer);
  } else {
    dbInstance = new SQL.Database();
  }

  // Create Tables
  dbInstance.run(`
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS sources (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      language TEXT NOT NULL CHECK(language IN ('CN', 'JP', 'KR')),
      parser_spec TEXT NOT NULL,
      parser_version INTEGER NOT NULL DEFAULT 1,
      status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'broken')),
      risk TEXT NOT NULL DEFAULT 'low',
      notes TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS source_domains (
      domain TEXT PRIMARY KEY,
      source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
      is_primary INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS parser_versions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
      version INTEGER NOT NULL,
      parser_spec TEXT NOT NULL,
      created_by TEXT DEFAULT 'system',
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS scrape_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      series_id INTEGER,
      source_id TEXT NOT NULL,
      run_type TEXT NOT NULL,
      status TEXT NOT NULL,
      chapters_found INTEGER DEFAULT 0,
      chapters_added INTEGER DEFAULT 0,
      error_message TEXT,
      started_at TEXT NOT NULL DEFAULT (datetime('now')),
      finished_at TEXT
    );

    CREATE TABLE IF NOT EXISTS manga (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      slug TEXT NOT NULL UNIQUE,
      alt_titles TEXT,
      description TEXT,
      cover_image TEXT,
      cover_url TEXT,
      banner_image TEXT,
      status TEXT DEFAULT 'ongoing',
      type TEXT DEFAULT 'manga',
      country TEXT DEFAULT 'JP',
      author TEXT,
      artist TEXT,
      original_publisher TEXT,
      genres TEXT,
      categories TEXT,
      tags TEXT,
      views INTEGER DEFAULT 0,
      daily_views INTEGER DEFAULT 0,
      weekly_views INTEGER DEFAULT 0,
      monthly_views INTEGER DEFAULT 0,
      rating REAL DEFAULT 0,
      rating_count INTEGER DEFAULT 0,
      chapters_count INTEGER DEFAULT 0,
      last_chapter_title TEXT,
      mangaupdates_url TEXT,
      source_url TEXT,
      source_id TEXT REFERENCES sources(id),
      auto_scrape_enabled INTEGER DEFAULT 1,
      scrape_frequency TEXT DEFAULT 'weekly',
      scrape_interval_value INTEGER DEFAULT 7,
      scrape_interval_unit TEXT DEFAULT 'days',
      last_scraped_at TEXT,
      next_scrape_at TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS chapters (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
      source_id TEXT NOT NULL REFERENCES sources(id),
      canonical_number REAL NOT NULL,
      chapter_number TEXT NOT NULL,
      native_title TEXT,
      title TEXT NOT NULL,
      chapter_title TEXT NOT NULL,
      source_chapter_url TEXT,
      pages TEXT NOT NULL,
      raw_pages TEXT,
      views INTEGER DEFAULT 0,
      release_date TEXT,
      is_paid INTEGER DEFAULT 0,
      requires_login INTEGER DEFAULT 0,
      is_quarantined INTEGER DEFAULT 0,
      quarantine_reason TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now')),
      CONSTRAINT uq_chapter_series_num UNIQUE (manga_id, canonical_number, source_id)
    );

    CREATE TABLE IF NOT EXISTS page_translations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
      page_index INTEGER NOT NULL,
      raw_image_url TEXT NOT NULL,
      translated_image_path TEXT NOT NULL,
      detected_boxes TEXT,
      validation_status TEXT DEFAULT 'valid',
      pipeline_version TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      CONSTRAINT uq_page_trans UNIQUE (chapter_id, page_index, pipeline_version)
    );

    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT NOT NULL UNIQUE,
      name TEXT,
      username TEXT UNIQUE,
      password TEXT,
      role TEXT DEFAULT 'user',
      is_main_admin INTEGER DEFAULT 0,
      is_secondary_admin INTEGER DEFAULT 0,
      language TEXT DEFAULT 'en',
      gender TEXT,
      birth_date TEXT,
      age INTEGER,
      is_under_18 INTEGER DEFAULT 0,
      age_locked INTEGER DEFAULT 0,
      profile_completed INTEGER DEFAULT 1,
      profile_image TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS user_sessions (
      session_id TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      expires_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS bookmarks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER DEFAULT 1,
      manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
      chapter_id INTEGER,
      added_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS reading_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER DEFAULT 1,
      manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
      chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
      read_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS comments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      target_type TEXT NOT NULL,
      target_id TEXT NOT NULL,
      user_id INTEGER NOT NULL REFERENCES users(id),
      user_name TEXT NOT NULL,
      user_avatar TEXT,
      content TEXT NOT NULL,
      upvotes INTEGER DEFAULT 0,
      downvotes INTEGER DEFAULT 0,
      reactions TEXT DEFAULT '{}',
      parent_id INTEGER,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS chapter_reports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chapter_id INTEGER NOT NULL,
      manga_id INTEGER NOT NULL,
      manga_title TEXT NOT NULL,
      chapter_title TEXT NOT NULL,
      chapter_number TEXT NOT NULL,
      report_type TEXT NOT NULL,
      details TEXT,
      status TEXT DEFAULT 'investigating',
      user_name TEXT DEFAULT 'Reader',
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS notifications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      message TEXT NOT NULL,
      body TEXT,
      type TEXT NOT NULL,
      category TEXT NOT NULL,
      read INTEGER DEFAULT 0,
      is_read INTEGER DEFAULT 0,
      target_type TEXT,
      target_id TEXT,
      data TEXT DEFAULT '{}',
      link TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS manga_ratings (
      manga_id INTEGER NOT NULL,
      user_identifier TEXT NOT NULL,
      rating INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      PRIMARY KEY (manga_id, user_identifier)
    );

    CREATE TABLE IF NOT EXISTS site_settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
  `);

  seedSourcesAndDomains(dbInstance);
  saveDb();
  return dbInstance;
}

// Seed the 16 Sources & Source Domains
function seedSourcesAndDomains(db: SqlJsDatabase): void {
  const sourcesSeed = [
    // CN
    { id: 'baozimh', name: 'Baozi Manga', language: 'CN', domain: 'baozimh.com', risk: 'low' },
    { id: 'wujinmh', name: 'Wujin Manga', language: 'CN', domain: 'wujinmh.com', risk: 'low' },
    { id: 'm_yueman1', name: 'YueMan Manhua', language: 'CN', domain: 'm.yueman1.cc', risk: 'medium' },
    { id: 'kuaikanmanhua', name: 'Kuaikan Manhua', language: 'CN', domain: 'kuaikanmanhua.com', risk: 'high' },
    { id: 'mkzhan', name: 'ManKeZhan', language: 'CN', domain: 'mkzhan.com', risk: 'medium' },
    // JP
    { id: 'tonarinoyj', name: 'Tonari no Young Jump', language: 'JP', domain: 'tonarinoyj.jp', risk: 'low' },
    { id: 'senmanga', name: 'Sen Manga Raw', language: 'JP', domain: 'raw.senmanga.com', risk: 'low' },
    { id: 'comic_days', name: 'Comic Days', language: 'JP', domain: 'comic-days.com', risk: 'medium' },
    { id: 'mangaz', name: 'MangaZ', language: 'JP', domain: 'mangaz.com', risk: 'low' },
    { id: 'comic_walker', name: 'Comic Walker', language: 'JP', domain: 'comic-walker.com', risk: 'medium' },
    { id: 'sunday_webry', name: 'Sunday Webry', language: 'JP', domain: 'sunday-webry.com', risk: 'medium' },
    { id: 'pocket_shonenmagazine', name: 'Pocket Shonen Magazine', language: 'JP', domain: 'pocket.shonenmagazine.com', risk: 'medium' },
    { id: 'shonenjumpplus', name: 'Shonen Jump+', language: 'JP', domain: 'shonenjumpplus.com', risk: 'high' },
    // KR
    { id: 'rawkuma', name: 'Rawkuma', language: 'KR', domain: 'rawkuma.com', risk: 'low' },
    { id: 'wfwf505', name: 'WFWF505', language: 'KR', domain: 'wfwf505.com', risk: 'high' },
    { id: 'naver', name: 'Naver Webtoon', language: 'KR', domain: 'comic.naver.com', risk: 'high' },
  ];

  for (const s of sourcesSeed) {
    const res = db.exec(`SELECT id FROM sources WHERE id = '${s.id}'`);
    if (res.length === 0 || res[0].values.length === 0) {
      const defaultSpec = JSON.stringify({
        selectors: { chapterList: 'a.chapter', pageImages: 'img.page' },
        urlPatterns: { series: `https://${s.domain}/series/`, chapter: `https://${s.domain}/chapter/` },
        pagination: { style: 'infinite' },
        imageExtraction: 'img.src',
      });
      db.run(
        `INSERT INTO sources (id, name, language, parser_spec, parser_version, status, risk, notes)
         VALUES (?, ?, ?, ?, 1, 'active', ?, ?)`,
        [s.id, s.name, s.language, defaultSpec, s.risk, `Official source parser for ${s.name}`]
      );
    }

    const domainRes = db.exec(`SELECT domain FROM source_domains WHERE domain = '${s.domain}'`);
    if (domainRes.length === 0 || domainRes[0].values.length === 0) {
      db.run(
        `INSERT INTO source_domains (domain, source_id, is_primary) VALUES (?, ?, 1)`,
        [s.domain, s.id]
      );
    }
  }
}

// SQL Query Utility Functions
export function queryAll<T = any>(sql: string, params: any[] = []): T[] {
  const db = getDb();
  const stmt = db.prepare(sql);
  stmt.bind(params);
  const results: T[] = [];
  while (stmt.step()) {
    results.push(stmt.getAsObject() as T);
  }
  stmt.free();
  return results;
}

export function queryOne<T = any>(sql: string, params: any[] = []): T | null {
  const rows = queryAll<T>(sql, params);
  return rows.length > 0 ? rows[0] : null;
}

export function executeRun(sql: string, params: any[] = []): { changes: number; lastInsertRowid: number } {
  const db = getDb();
  db.run(sql, params);
  const res = db.exec('SELECT last_insert_rowid() as id, changes() as changes');
  let lastInsertRowid = 0;
  let changes = 0;
  if (res.length > 0 && res[0].values.length > 0) {
    lastInsertRowid = Number(res[0].values[0][0]);
    changes = Number(res[0].values[0][1]);
  }
  saveDb();
  return { changes, lastInsertRowid };
}
