import type { OcrProvider, OcrRunResult, OcrRunOptions, OverlayBox } from "../types";

const LANGUAGE_MAP: Record<string, string> = {
  en: "eng",
  eng: "eng",
  ja: "jpn",
  jp: "jpn",
  jpn: "jpn",
  zh: "chi_sim",
  "zh-cn": "chi_sim",
  "zh-hans": "chi_sim",
  "zh-tw": "chi_tra",
  "zh-hant": "chi_tra",
  ko: "kor",
  kor: "kor",
  es: "spa",
  spa: "spa",
  fr: "fra",
  fra: "fra",
  de: "deu",
  deu: "deu",
  pt: "por",
  por: "por",
};

let workerPromise: Promise<any> | null = null;
let currentLanguage = "";
const loadedLanguages = new Set<string>();

function normalizeLang(language?: string): string {
  if (!language) return "eng";
  const normalized = language.trim().toLowerCase();
  if (!normalized) return "eng";
  return LANGUAGE_MAP[normalized] || (normalized.length === 3 ? normalized : "eng");
}

async function ensureWorker(language: string) {
  if (!workerPromise) {
    workerPromise = (async () => {
      // tesseract.js is only pulled in here, in response to an actual OCR
      // request, so it never ships in the base reader bundle.
      const { createWorker } = await import("tesseract.js");
      // Provide a default language so we can supply worker options (e.g. logger)
      // without running into the strict TypeScript overload that expects a
      // language argument in the first position.
      const worker = await createWorker("eng");
      if (typeof worker.load === "function") {
        await worker.load();
      }
      return worker;
    })();
  }

  const worker = await workerPromise;
  const tessLang = normalizeLang(language);

  if (!loadedLanguages.has(tessLang)) {
    if (typeof worker.loadLanguage === "function") {
      await worker.loadLanguage(tessLang);
    }
    loadedLanguages.add(tessLang);
  }

  if (currentLanguage !== tessLang) {
    if (typeof worker.initialize === "function") {
      await worker.initialize(tessLang);
    }
    currentLanguage = tessLang;
  }

  return worker;
}

function clamp01(value: unknown): number {
  const num = Number(value);
  if (!Number.isFinite(num)) return 0;
  if (num < 0) return 0;
  if (num > 1) return 1;
  return num;
}

function mapWordsToBoxes(words: any[], width: number, height: number): OverlayBox[] {
  return words
    .map((word) => {
      if (!word || typeof word !== "object") return null;
      const text = typeof word.text === "string" ? word.text.trim() : "";
      if (!text) return null;
      const bbox = word.bbox && typeof word.bbox === "object" ? word.bbox : null;
      if (!bbox) return null;
      const x0 = Number(bbox.x0);
      const y0 = Number(bbox.y0);
      const x1 = Number(bbox.x1);
      const y1 = Number(bbox.y1);
      if (!Number.isFinite(x0) || !Number.isFinite(y0) || !Number.isFinite(x1) || !Number.isFinite(y1)) {
        return null;
      }
      const w = x1 - x0;
      const h = y1 - y0;
      if (w <= 0 || h <= 0) return null;
      return {
        x: clamp01(x0 / width),
        y: clamp01(y0 / height),
        w: clamp01(w / width),
        h: clamp01(h / height),
        text,
        confidence: typeof word.confidence === "number" ? clamp01(word.confidence / 100) : undefined,
      } satisfies OverlayBox;
    })
    .filter(Boolean) as OverlayBox[];
}

async function runTesseract(image: string, options?: OcrRunOptions): Promise<OcrRunResult> {
  const language = options?.language || "eng";
  const worker = await ensureWorker(language);
  if (typeof worker.recognize !== "function") {
    throw new Error("Tesseract worker missing recognize function");
  }

  const result = await worker.recognize(image);
  const words = Array.isArray(result?.data?.words) ? result.data.words : [];
  if (!words.length) {
    return { boxes: [], warnings: ["No readable text detected"] };
  }

  const width = Number(result?.data?.imageSize?.width) || 0;
  const height = Number(result?.data?.imageSize?.height) || 0;
  if (!width || !height) {
    return { boxes: [], warnings: ["OCR result missing image dimensions"] };
  }

  return {
    boxes: mapWordsToBoxes(words, width, height),
    warnings: [],
    metadata: {
      workerLanguage: language,
      engine: "tesseract.js",
    },
  };
}

const tesseractProvider: OcrProvider = {
  id: "tesseract",
  label: "Tesseract.js",
  description: "On-device OCR running in the browser",
  async run(image, options) {
    return runTesseract(image, options);
  },
  isAvailable() {
    return typeof window !== "undefined";
  },
};

export function resetTesseractWorker() {
  workerPromise = null;
  currentLanguage = "";
  loadedLanguages.clear();
}

export default tesseractProvider;
