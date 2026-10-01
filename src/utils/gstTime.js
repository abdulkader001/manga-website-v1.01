/**
 * Accurate UTC (Coordinated Universal Time) & Real-Time Utility
 * Ensures 100% accurate timestamps, clean relative time formatting, and zero artificial offsets.
 */

/**
 * The server stores and sends UTC, but its ISO strings carry no "Z" or offset
 * ("2026-10-01T10:00:00"). JavaScript reads such a string as LOCAL time, which
 * shifted every date by the viewer's offset. Treat offset-less strings as UTC.
 */
export function parseUtc(input) {
  if (input instanceof Date) return input;
  if (typeof input === "string" && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(input) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(input)) {
    return new Date(input.replace(" ", "T") + "Z");
  }
  return new Date(input);
}

/**
 * Returns current Date in UTC
 */
export function getNowInUtc() {
  return new Date();
}

/**
 * Formats a Date or ISO string into a clean UTC time string
 * Example: "14:32 UTC" or "Sep 29, 2026, 14:32 UTC"
 */
export function formatUtcTime(dateInput, includeDate = true) {
  if (!dateInput) return "Recently";
  try {
    const d = parseUtc(dateInput);
    if (isNaN(d.getTime())) return "Recently";

    const hours = String(d.getUTCHours()).padStart(2, "0");
    const minutes = String(d.getUTCMinutes()).padStart(2, "0");
    const seconds = String(d.getUTCSeconds()).padStart(2, "0");
    const timeStr = `${hours}:${minutes}:${seconds} UTC`;

    if (!includeDate) return timeStr;

    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const month = months[d.getUTCMonth()];
    const day = d.getUTCDate();
    const year = d.getUTCFullYear();

    return `${month} ${day}, ${year} ${timeStr}`;
  } catch {
    return "Recently";
  }
}

/**
 * Legacy GST alias pointing to UTC for compatibility
 */
export const formatGstTime = formatUtcTime;

/**
 * Computes exact real-time relative distance from now without hallucinated offsets
 * Example: "Just now", "5m ago", "18m ago", "2h ago", "3d ago"
 */
export function formatTimeAgo(dateInput) {
  // No time known is not "just now": show nothing rather than a wrong time.
  if (!dateInput) return "";
  try {
    const d = parseUtc(dateInput);
    const timeMs = d.getTime();
    if (isNaN(timeMs)) return "";

    const diffMs = Date.now() - timeMs;
    // A few seconds ahead is clock drift; further ahead is a bad timestamp.
    if (diffMs < 0) return diffMs > -5 * 60 * 1000 ? "Just now" : "";

    const diffSeconds = Math.floor(diffMs / 1000);
    if (diffSeconds < 45) return "Just now";

    const diffMinutes = Math.floor(diffSeconds / 60);
    if (diffMinutes < 60) return `${diffMinutes}m ago`;

    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours}h ago`;

    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 30) return `${diffDays}d ago`;

    const diffMonths = Math.floor(diffDays / 30);
    if (diffMonths < 12) return `${diffMonths}mo ago`;

    const diffYears = Math.floor(diffDays / 365);
    return `${diffYears}y ago`;
  } catch {
    return "";
  }
}
