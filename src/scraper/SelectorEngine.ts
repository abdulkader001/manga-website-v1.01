import * as cheerio from 'cheerio';

export class SelectorEngine {
  /**
   * Loads raw HTML string into a Cheerio API instance
   */
  public static parseHtml(html: string): cheerio.CheerioAPI {
    return cheerio.load(html);
  }

  /**
   * Extracts an attribute value from an element using the standard fallback chain:
   * [data-src -> data-original -> src -> data-url -> srcset]
   */
  public static extractAttributeWithFallback($el: cheerio.Cheerio<any>): string {
    const fallbackAttrs = ['data-src', 'data-original', 'src', 'data-url', 'srcset'];
    for (const attr of fallbackAttrs) {
      const val = $el.attr(attr);
      if (val && typeof val === 'string' && val.trim().length > 0) {
        if (attr === 'srcset') {
          const firstSrc = val.split(',')[0].trim().split(' ')[0];
          if (firstSrc) return firstSrc;
        }
        return val.trim();
      }
    }
    return '';
  }

  /**
   * Extracts array of image URLs matching selector using the attribute fallback chain
   */
  public static extractImages(
    $: cheerio.CheerioAPI,
    selector: string,
    skipFirstImage = false
  ): string[] {
    const images: string[] = [];
    let elements = $(selector);

    if (skipFirstImage && elements.length > 1) {
      elements = elements.slice(1);
    }

    elements.each((_, el) => {
      const imgUrl = this.extractAttributeWithFallback($(el));
      if (imgUrl) {
        images.push(imgUrl);
      }
    });

    return images;
  }

  /**
   * Extracts text content from element and optionally applies a regex extraction
   */
  public static extractText(
    $: cheerio.CheerioAPI,
    selector: string,
    regexPattern?: string
  ): string {
    const rawText = $(selector).first().text().trim();
    if (!rawText) return '';

    if (regexPattern) {
      const match = rawText.match(new RegExp(regexPattern, 'i'));
      return match && match[1] ? match[1].trim() : rawText;
    }

    return rawText;
  }

  /**
   * Extracts embedded JSON state blob (__NEXT_DATA__, __NUXT__, __INITIAL_STATE__, viewer_config)
   * and optionally navigates to a nested path using dot-notation (e.g. "props.pageProps.episodes")
   */
  public static extractJsonState(
    html: string,
    kind: 'none' | 'next_data' | 'nuxt' | 'initial_state' | 'viewer_config' | string,
    jsonPath?: string
  ): any {
    if (!kind || kind === 'none') return null;

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
}
