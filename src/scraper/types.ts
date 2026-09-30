/**
 * Parser Spec Schema (13.B) & Engine Types
 */

export type CharacterEncoding = 'utf-8' | 'euc-kr' | 'gbk' | 'gb18030';

export interface RequestProfile {
  headers: Record<string, string>;
  encoding?: CharacterEncoding;
  timeoutMs?: number;
  maxRedirects?: number;
}

export interface FieldSpec {
  selector?: string;
  regex?: string;
  attr?: 'text' | 'href' | 'src' | 'data-src' | 'data-original' | string;
  format?: string;
}

export interface ChapterListSpec {
  selector: string;
  item?: string;
  fields: {
    number: FieldSpec;
    title: FieldSpec;
    date?: FieldSpec;
    url: FieldSpec;
  };
}

export interface StateSourceSpec {
  kind: 'none' | 'next_data' | 'nuxt' | 'initial_state' | 'viewer_config';
  jsonPath?: string;
}

export interface FlagsSpec {
  paywall?: string;
  loginRequired?: string;
}

export interface SeriesPageSpec {
  chapterList?: ChapterListSpec;
  stateSource?: StateSourceSpec;
  flags?: FlagsSpec;
}

export interface ImagesSpec {
  selector?: string;
  attr?: string;
  baseUrl?: string;
  jsonPath?: string;
  skipFirstImage?: boolean;
}

export interface PaginationSpec {
  kind: 'none' | 'next' | 'ajax';
  nextSelector?: string;
  ajaxUrl?: string;
}

export interface ChapterPageSpec {
  images: ImagesSpec;
  pagination?: PaginationSpec;
}

export interface ParserSpec {
  version: number;
  sourceId: string;
  name: string;
  urlPatterns: {
    series: string;
    chapter: string;
    pagination?: string;
  };
  requestProfile: RequestProfile;
  seriesPage: SeriesPageSpec;
  chapterPage: ChapterPageSpec;
}

export interface ScrapedChapter {
  canonical_number: number;
  chapter_number: string;
  native_title: string;
  title: string;
  chapter_title: string;
  source_chapter_url: string;
  release_date: string;
  is_paid: boolean;
  requires_login: boolean;
  is_region_locked: boolean;
  pages: string[];
}

export interface ChapterExtractionResult {
  source_id: string;
  total_chapters_detected: number;
  chapters: ScrapedChapter[];
  watermark_hash?: string;
}
