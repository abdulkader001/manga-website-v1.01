// Fails when `npm audit` reports a high or critical advisory, except the ones
// listed in IGNORED (each with the reason it can't be fixed yet). npm has no
// built-in way to ignore one advisory, so this reads `npm audit --json`.
//
// Usage: npm audit --json | node .github/scripts/npm-audit-gate.mjs
import { readFileSync } from "node:fs";

const IGNORED = {
  // braces: stack exhaustion on deeply nested brace patterns. Every published
  // version is affected (<=3.0.3) and there is no fixed release. It reaches us
  // only through tailwindcss 3 (chokidar, fast-glob, micromatch), at build
  // time, on the glob patterns in our own tailwind.config.js -- never on
  // visitor input, and nothing of it ships to the server or the browser
  // (`npm audit --omit=dev` is clean). Revisit when braces ships a fix or the
  // site moves to Tailwind 4.
  "GHSA-vfj7-8cjw-p6xm": "braces <=3.0.3, build-time only via tailwindcss 3, no fix yet",
};
const FAIL_ON = new Set(["high", "critical"]);

const report = JSON.parse(readFileSync(0, "utf8") || "{}");
// A failed audit (registry down, bad lockfile) prints an error, not a report:
// fail rather than pass with nothing checked.
if (report.error || !report.metadata) {
  console.error("npm audit did not produce a report:", JSON.stringify(report.error || report).slice(0, 500));
  process.exit(1);
}
const blocking = new Map();
const ignored = new Map();
for (const [pkg, vuln] of Object.entries(report.vulnerabilities || {})) {
  // String entries in `via` point at another package's advisory, which is
  // listed under that package; only the advisory objects are checked here.
  for (const via of vuln.via || []) {
    if (typeof via !== "object" || !FAIL_ON.has(via.severity)) continue;
    const id = (via.url || "").split("/").pop() || String(via.source);
    (IGNORED[id] ? ignored : blocking).set(id, `${via.severity} ${pkg}: ${via.title} (${via.url})`);
  }
}

for (const [id, line] of ignored) console.log(`ignored ${id}: ${line} -- ${IGNORED[id]}`);
if (blocking.size) {
  for (const line of blocking.values()) console.error(`BLOCKING ${line}`);
  process.exit(1);
}
console.log("npm audit gate: no high or critical advisory outside the ignore list.");
