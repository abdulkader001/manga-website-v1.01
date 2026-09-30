export function resetUsage(period?: string) {
  try {
    localStorage.removeItem("ocr_translation_usage");
  } catch (e) {
    // Ignore localStorage errors
  }
}
