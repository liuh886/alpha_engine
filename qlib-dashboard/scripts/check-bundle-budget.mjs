/**
 * check-bundle-budget.mjs
 *
 * Verifies that the already-built production artifact stays within the
 * documented JavaScript budget (450 KB gzip).
 *
 * The build is intentionally owned by the caller. This keeps CI to one
 * production build instead of rebuilding the application just to measure it.
 *
 * Because this project uses vite-plugin-singlefile, the application chunk is
 * normally inlined into dist/index.html. Standalone runtime files such as the
 * service worker are measured in addition to every inline script.
 *
 * Usage: npm run build && node scripts/check-bundle-budget.mjs
 * Exit 0 = pass, Exit 1 = missing/stale artifact or over budget.
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { resolve, dirname, extname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(__dirname, "..");

const BUDGET_KB = 450;
const DIST = resolve(PROJECT_ROOT, "dist");
const INDEX = resolve(DIST, "index.html");

if (!existsSync(INDEX)) {
  console.error("✘ Missing dist/index.html. Build the production artifact before checking its budget.");
  process.exit(1);
}

/** Recursively find files matching a predicate. */
function walk(dir, predicate, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, predicate, out);
    } else if (predicate(full)) {
      out.push(full);
    }
  }
  return out;
}

const jsFiles = walk(DIST, (file) => extname(file) === ".js");
const jsSegments = [];

if (jsFiles.length > 0) {
  console.log(`  Found ${jsFiles.length} JS file(s) in dist/:`);
  for (const file of jsFiles) {
    const raw = readFileSync(file);
    const gz = gzipSync(raw);
    const label = file.replace(DIST + "\\", "").replace(DIST + "/", "");
    jsSegments.push({
      label,
      rawKB: raw.length / 1024,
      gzipKB: gz.length / 1024,
    });
  }
}

const html = readFileSync(INDEX, "utf-8");
const scriptRe = /<script\b[^>]*>([\s\S]*?)<\/script>/gi;
let match;
let inlineCount = 0;
while ((match = scriptRe.exec(html)) !== null) {
  const body = match[1].trim();
  if (!body) continue;
  inlineCount += 1;
  const raw = Buffer.from(body, "utf-8");
  const gz = gzipSync(raw);
  jsSegments.push({
    label: `inline-script-${inlineCount}`,
    rawKB: raw.length / 1024,
    gzipKB: gz.length / 1024,
  });
}

if (inlineCount > 0) {
  console.log(`  Extracted ${inlineCount} inline <script> block(s):`);
}

if (jsSegments.length === 0) {
  console.error("✘ No JS assets found — neither standalone files nor inline scripts.");
  process.exit(1);
}

let totalRaw = 0;
let totalGzip = 0;
for (const segment of jsSegments) {
  console.log(`    ${segment.label}  raw ${segment.rawKB.toFixed(1)} KB  gzip ${segment.gzipKB.toFixed(1)} KB`);
  totalRaw += segment.rawKB;
  totalGzip += segment.gzipKB;
}

console.log();
console.log(`  Total JS raw:  ${totalRaw.toFixed(2)} KB`);
console.log(`  Total JS gzip: ${totalGzip.toFixed(2)} KB`);
console.log(`  Budget:         ${BUDGET_KB} KB`);
console.log();

if (totalGzip > BUDGET_KB) {
  console.error(`✘ OVER BUDGET by ${(totalGzip - BUDGET_KB).toFixed(2)} KB`);
  process.exit(1);
}

console.log(`✔ Within budget (${(BUDGET_KB - totalGzip).toFixed(2)} KB headroom)`);
