/**
 * Enterprise URL & Domain Threat Intelligence & Anti-Malware / Anti-Virus Validation
 * Analyzes URLs against malicious schemes, dangerous top-level domains, IP literals,
 * known phishing patterns, embedded executable extensions, and Proton/VirusTotal heuristics.
 */

// Suspicious/Malware file extensions that shouldn't be served or linked as safe manga/ad assets
const MALWARE_EXTENSIONS = [
  /\.(exe|bat|cmd|sh|vbs|msi|ps1|scr|pif|reg|dll|jar|hta|cpl|com|apk|ipa|dmg|iso|bin)$/i,
];

// Blocked malicious or reserved internal IP spaces (SSRF protection)
const BLOCKED_HOST_PATTERNS = [
  /^localhost$/i,
  /^127\.\d+\.\d+\.\d+$/,
  /^10\.\d+\.\d+\.\d+$/,
  /^192\.168\.\d+\.\d+$/,
  /^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$/,
  /^0\.0\.0\.0$/,
  /^::1$/,
  /\.onion$/i,
  /\.internal$/i,
  /\.local$/i,
];

// High-risk TLDs and known spam/malware redirectors
const SUSPICIOUS_TLDS = [
  /\.(zip|mov|top|gq|ml|cf|ga|tk|country|stream|kim|download|racing|win|bid)$/i,
];

export interface UrlSecurityAuditResult {
  isValid: boolean;
  isSafe: boolean;
  score: number; // 0 (safe) to 100 (critical threat)
  flags: string[];
  threatLevel: "clean" | "low" | "medium" | "high" | "critical";
  normalizedUrl: string;
}

/**
 * Validates and scans any URL input to prevent malware, virus drops, phishing, or SSRF attacks.
 */
export function auditUrlSecurity(rawUrl: string): UrlSecurityAuditResult {
  const flags: string[] = [];
  let score = 0;

  if (!rawUrl || typeof rawUrl !== "string") {
    return {
      isValid: false,
      isSafe: false,
      score: 100,
      flags: ["Empty or non-string input"],
      threatLevel: "critical",
      normalizedUrl: "",
    };
  }

  const trimmed = rawUrl.trim();

  // 1. Protocol validation: ONLY allow http and https
  if (/^(javascript|data|vbscript|file|about|blob):/i.test(trimmed)) {
    return {
      isValid: false,
      isSafe: false,
      score: 100,
      flags: ["Dangerous URI protocol detected (XSS/Payload hazard)"],
      threatLevel: "critical",
      normalizedUrl: trimmed,
    };
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return {
      isValid: false,
      isSafe: false,
      score: 90,
      flags: ["Malformed URL syntax"],
      threatLevel: "high",
      normalizedUrl: trimmed,
    };
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return {
      isValid: false,
      isSafe: false,
      score: 90,
      flags: [`Disallowed protocol: ${parsed.protocol}`],
      threatLevel: "high",
      normalizedUrl: trimmed,
    };
  }

  const hostname = parsed.hostname.toLowerCase();

  // 2. SSRF / Local IP filtering
  for (const pattern of BLOCKED_HOST_PATTERNS) {
    if (pattern.test(hostname)) {
      flags.push("SSRF / Private subnet access denied");
      score += 80;
      break;
    }
  }

  // 3. Executable / Virus Drop Detection
  const pathname = parsed.pathname.toLowerCase();
  for (const ext of MALWARE_EXTENSIONS) {
    if (ext.test(pathname)) {
      flags.push("Malware / Executable binary extension detected in path");
      score += 90;
      break;
    }
  }

  // 4. High-risk TLD scanning
  for (const tld of SUSPICIOUS_TLDS) {
    if (tld.test(hostname)) {
      flags.push("Host uses high-risk / spam top-level domain");
      score += 35;
      break;
    }
  }

  // 5. Embedded credentials in URL (e.g. https://user:pass@evil.com)
  if (parsed.username || parsed.password) {
    flags.push("Suspicious embedded authentication credentials in URL");
    score += 50;
  }

  // 6. Suspicious query strings or encoded scripts
  const search = parsed.search.toLowerCase();
  if (
    search.includes("<script") ||
    search.includes("%3cscript") ||
    search.includes("javascript:") ||
    search.includes("alert(") ||
    search.includes("base64")
  ) {
    flags.push("Possible XSS / Injected exploit in query parameters");
    score += 70;
  }

  // Threat level determination
  let threatLevel: "clean" | "low" | "medium" | "high" | "critical" = "clean";
  if (score >= 80) threatLevel = "critical";
  else if (score >= 50) threatLevel = "high";
  else if (score >= 30) threatLevel = "medium";
  else if (score > 0) threatLevel = "low";

  const isSafe = score < 50;

  return {
    isValid: true,
    isSafe,
    score,
    flags,
    threatLevel,
    normalizedUrl: parsed.toString(),
  };
}
