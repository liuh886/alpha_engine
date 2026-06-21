/**
 * check-bundle-budget.mjs
 *
 * Builds the frontend and verifies the gzip size of dist/index.html
 * stays within the documented performance budget (450 KB).
 *
 * Usage:  node scripts/check-bundle-budget.mjs
 * Exit 0 = pass, Exit 1 = over budget.
 */

import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(__dirname, "..");

const BUDGET_KB = 450;
const ARTIFACT = resolve(PROJECT_ROOT, "dist", "index.html");

// 1. Build
console.log("▸ Building production bundle…");
execSync("npm run build", { cwd: PROJECT_ROOT, stdio: "inherit" });

// 2. Measure
const raw = readFileSync(ARTIFACT);
const gzipped = gzipSync(raw);
const gzipKB = gzipped.length / 1024;

console.log();
console.log(`  Raw size:  ${(raw.length / 1024).toFixed(2)} KB`);
console.log(`  Gzip size: ${gzipKB.toFixed(2)} KB`);
console.log(`  Budget:    ${BUDGET_KB} KB`);
console.log();

// 3. Gate
if (gzipKB > BUDGET_KB) {
  console.error(`✘ OVER BUDGET by ${(gzipKB - BUDGET_KB).toFixed(2)} KB`);
  process.exit(1);
} else {
  const headroom = BUDGET_KB - gzipKB;
  console.log(`✔ Within budget (${headroom.toFixed(2)} KB headroom)`);
  process.exit(0);
}
