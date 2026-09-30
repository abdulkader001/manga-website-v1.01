export class ChapterNormalizer {
  /**
   * Normalizes raw chapter titles across languages (CN, KR, JP, Generic) to canonical float values
   */
  public static normalize(rawStr: string): number {
    if (!rawStr) return 0;
    const clean = rawStr.trim().toLowerCase();

    // Suffix / Keyword Mapping
    if (/prologue|프롤로그|序章|序/i.test(clean)) return 0.01;
    if (/extra|side story|특별편|외전|番外編/i.test(clean)) return 0.5;
    if (/epilogue|에필로그|終章|完結/i.test(clean)) return 999.5;

    // CN Regex: /第?\s*(\d+(?:\.\d+)?)\s*[話话回]/
    const cnMatch = clean.match(/第?\s*(\d+(?:\.\d+)?)\s*[話话回章]/);
    if (cnMatch && cnMatch[1]) {
      return parseFloat(cnMatch[1]);
    }

    // KR Regex: /(\d+(?:\.\d+)?)\s*화/
    const krMatch = clean.match(/(\d+(?:\.\d+)?)\s*화/);
    if (krMatch && krMatch[1]) {
      return parseFloat(krMatch[1]);
    }

    // JP Regex: /第(\d+(?:\.\d+)?)[話话]/
    const jpMatch = clean.match(/第(\d+(?:\.\d+)?)[話话]/);
    if (jpMatch && jpMatch[1]) {
      return parseFloat(jpMatch[1]);
    }

    // Generic Regex: /#?\s*(\d+(?:\.\d+)?)/
    const genMatch = clean.match(/(?:ch\.?|chapter|ep|episode|#)?\s*(\d+(?:\.\d+)?)/i);
    if (genMatch && genMatch[1]) {
      return parseFloat(genMatch[1]);
    }

    return 1;
  }

  /**
   * Formats a canonical float chapter number back into a clean string representation (e.g. 10.5 -> "10.5", 0.01 -> "Prologue")
   */
  public static formatChapterTitle(num: number): string {
    if (num === 0.01) return 'Prologue';
    if (num === 0.5) return 'Extra / Side Story';
    if (num === 999.5) return 'Epilogue';
    return `Chapter ${num}`;
  }
}
