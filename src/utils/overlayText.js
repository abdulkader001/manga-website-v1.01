// Size of the translated text drawn over manga pages (and nothing else on
// the site). Readers pick 1-100 in half steps; the overlay draws
// value * PX_PER_STEP pixels, so 100 is 70 px. Matches the backend
// (models/processing_settings.py).

export const TEXT_SCALE_MIN = 1;
export const TEXT_SCALE_MAX = 100;
export const TEXT_SCALE_STEP = 0.5;
export const PX_PER_STEP = 0.7;
export const DEFAULT_TEXT_SCALE = 28.5; // the old 20 px baseline

export function clampTextScale(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return DEFAULT_TEXT_SCALE;
  const stepped = Math.round(n / TEXT_SCALE_STEP) * TEXT_SCALE_STEP;
  return Math.min(TEXT_SCALE_MAX, Math.max(TEXT_SCALE_MIN, stepped));
}

export function textScaleToPx(value) {
  return Math.round(clampTextScale(value) * PX_PER_STEP * 100) / 100;
}
