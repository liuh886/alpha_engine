/**
 * check-bundle-budget.mjs
 *
 * Builds the frontend and verifies that the total gzipped size of all
 * JavaScript shipped to the browser stays within the documented budget
 * (450 KB).
 *
 * Because this project uses vite-plugin-singlefile, JS chunks are inlined
 * into dist/index.html as <script> tags.  The script extracts every
 * inline <script> body, gzips each one independently, and sums the totals.
 *
 * If the build produces standalone .js files in dist/ (e.g. if the
 * singlefile plugin is removed in the future), those are measured instead.
 *
 * Usage:  node scripts/check-bundle-budget.mjs
 * Exit 0 = pass, Exit 1 = over budget.
 */

import { execSync } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { resolve, dirname, extname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(__dirname, "..");

const BUDGET_KB = 450;
const DIST = resolve(PROJECT_ROOT, "dist");

// ── 1. Build ────────────────────────────────────────────────────────
console.log("▸ Building production bundle…");
execSync("npm run build", { cwd: PROJECT_ROOT, stdio: "inherit" });
console.log();

// ── 2. Collect JS bytes ─────────────────────────────────────────────

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

const jsFiles = walk(DIST, (f) => extname(f) === ".js");

let jsSegments = [];  // { label, rawKB, gzipKB }

if (jsFiles.length > 0) {
  // ── Mode A: standalone .js files in dist/ ──
  console.log(`  Found ${jsFiles.length} JS file(s) in dist/:`);
  for (const f of jsFiles) {
    const raw = readFileSync(f);
    const gz = gzipSync(raw);
    const label = f.replace(DIST + "\\", "").replace(DIST + "/", "");
    jsSegments.push({
      label,
      rawKB: raw.length / 1024,
      gzipKB: gz.length / 1024,
    });
  }
} else {
  // ── Mode B: JS inlined inside index.html (singlefile mode) ──
  const indexPath = resolve(DIST, "index.html");
  const html = readFileSync(indexPath, "utf-8");

  // Match every <script ...>...</script> with a non-empty body.
  // The singlefile plugin produces a single large inline script.
  const scriptRe = /<script\b[^>]*>([\s\S]*?)<\/script>/gi;
  let match;
  let i = 0;
  while ((match = scriptRe.exec(html)) !== null) {
    const body = match[1].trim();
    if (!body) continue;
    i++;
    const raw = Buffer.from(body, "utf-8");
    const gz = gzipSync(raw);
    jsSegments.push({
      label: `inline-script-${i}`,
      rawKB: raw.length / 1024,
      gzipKB: gz.length / 1024,
    });
  }
  if (jsSegments.length === 0) {
    console.error("✘ No JS assets found — neither standalone files nor inline scripts.");
    process.exit(1);
  }
  console.log(`  Single-file mode: extracted ${jsSegments.length} inline <script> block(s):`);
}

// ── 3. Report ───────────────────────────────────────────────────────
let totalRaw = 0;
let totalGzip = 0;
for (const seg of jsSegments) {
  console.log(`    ${seg.label}  raw ${seg.rawKB.toFixed(1)} KB  gzip ${seg.gzipKB.toFixed(1)} KB`);
  totalRaw += seg.rawKB;
  totalGzip += seg.gzipKB;
}
console.log();
console.log(`  Total JS raw:  ${totalRaw.toFixed(2)} KB`);
console.log(`  Total JS gzip: ${totalGzip.toFixed(2)} KB`);
console.log(`  Budget:         ${BUDGET_KB} KB`);
console.log();

// ── 4. Gate ─────────────────────────────────────────────────────────
if (totalGzip > BUDGET_KB) {
  console.error(`✘ OVER BUDGET by ${(totalGzip - BUDGET_KB).toFixed(2)} KB`);
  process.exit(1);
} else {
  console.log(`✔ Within budget (${(BUDGET_KB - totalGzip).toFixed(2)} KB headroom)`);
  process.exit(0);
}
