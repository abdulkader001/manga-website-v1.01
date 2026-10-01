/**
 * Email Masking & Privacy Guard
 * Masks email addresses to prevent phishing, scraping, and social engineering.
 * Example: "reader.name42@gmail.com" -> "re•••••••••42@gmail.com"
 * Example: "admin@mangareader.local" -> "ad•••••n@mangareader.local"
 */
export function maskEmail(email) {
  if (!email || typeof email !== "string") return "••••••••@••••.•••";
  const trimmed = email.trim();
  const atIndex = trimmed.indexOf("@");
  if (atIndex <= 1) return "••••••••@••••.•••";

  const userPart = trimmed.substring(0, atIndex);
  const domainPart = trimmed.substring(atIndex + 1);

  if (userPart.length <= 3) {
    return `${userPart[0]}•••@${domainPart}`;
  }

  const firstTwo = userPart.substring(0, 2);
  const lastTwo = userPart.substring(userPart.length - 2);
  const maskLength = Math.max(3, userPart.length - 4);
  const maskedMiddle = "•".repeat(Math.min(maskLength, 10));

  return `${firstTwo}${maskedMiddle}${lastTwo}@${domainPart}`;
}

/**
 * Full SHA-256 hash or secure masked representation for non-privileged display
 */
export function hashEmailDisplay(email) {
  if (!email) return "••••••••••••";
  const masked = maskEmail(email);
  return `[Protected] ${masked}`;
}
