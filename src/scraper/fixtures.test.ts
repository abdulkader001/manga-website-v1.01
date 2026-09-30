import fs from 'fs';
import path from 'path';
import * as cheerio from 'cheerio';
import { SOURCE_PARSER_SPECS } from './sourceSpecs';
import { normalizeChapterNumber, extractJsonState } from './sharedEngine';

export function runFixtureTests(): { passed: number; failed: number; log: string[] } {
  const log: string[] = [];
  let passed = 0;
  let failed = 0;

  const fixtureSources = ['baozimh', 'rawkuma', 'comicdays', 'naver'];

  for (const sourceId of fixtureSources) {
    const spec = SOURCE_PARSER_SPECS[sourceId];
    if (!spec) {
      log.push(`[SKIP] No spec registered for ${sourceId}`);
      continue;
    }

    const fixturePath = path.join(process.cwd(), 'tests', 'fixtures', sourceId, 'series.html');
    if (!fs.existsSync(fixturePath)) {
      log.push(`[SKIP] Fixture file missing for ${sourceId}`);
      continue;
    }

    try {
      const html = fs.readFileSync(fixturePath, 'utf-8');
      const $ = cheerio.load(html);
      let chapterCount = 0;

      // Check stateSource or selector
      if (spec.seriesPage.stateSource?.kind && spec.seriesPage.stateSource.kind !== 'none') {
        const stateData = extractJsonState(
          html,
          spec.seriesPage.stateSource.kind,
          spec.seriesPage.stateSource.jsonPath
        );
        if (stateData) {
          const episodes = Array.isArray(stateData)
            ? stateData
            : stateData.episodes || stateData.chapters || [];
          chapterCount = episodes.length;
        }
      }

      if (chapterCount === 0 && spec.seriesPage.chapterList?.selector) {
        chapterCount = $(spec.seriesPage.chapterList.selector).length;
      }

      if (chapterCount > 0) {
        passed++;
        log.push(`[PASS] ${sourceId}: extracted ${chapterCount} chapters from fixture HTML`);
      } else {
        failed++;
        log.push(`[FAIL] ${sourceId}: zero chapters extracted from fixture HTML`);
      }
    } catch (e: any) {
      failed++;
      log.push(`[ERROR] ${sourceId}: fixture parsing error: ${e.message}`);
    }
  }

  return { passed, failed, log };
}
