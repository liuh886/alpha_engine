import { copyFile, lstat, mkdir, readFile, readdir, rm } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(scriptDir, '..');
const repositoryRoot = resolve(dashboardRoot, '..');
const sourceRoot = join(repositoryRoot, 'data', 'research', 'market_evidence');
const targetRoot = join(dashboardRoot, 'public', 'data', 'market-evidence');

async function copyJsonTree(source, target) {
  const entries = await readdir(source, { withFileTypes: true });
  await mkdir(target, { recursive: true });
  for (const entry of entries) {
    const sourcePath = join(source, entry.name);
    const targetPath = join(target, entry.name);
    const info = await lstat(sourcePath);
    if (info.isSymbolicLink()) {
      throw new Error(`Market evidence publication cannot follow symlink: ${relative(sourceRoot, sourcePath)}`);
    }
    if (entry.isDirectory()) {
      await copyJsonTree(sourcePath, targetPath);
      continue;
    }
    if (!entry.isFile() || !entry.name.endsWith('.json')) {
      throw new Error(`Market evidence publication accepts JSON files only: ${relative(sourceRoot, sourcePath)}`);
    }
    await copyFile(sourcePath, targetPath);
  }
}

async function validateCatalog(market) {
  const path = join(targetRoot, market, 'catalog.json');
  const payload = JSON.parse(await readFile(path, 'utf8'));
  if (payload.schema_version !== '1.1' || payload.evidence_type !== 'market_evidence_catalog' || payload.market !== market) {
    throw new Error(`Invalid ${market.toUpperCase()} Market Evidence 1.1 catalog.`);
  }
  if (payload.research_only !== true || payload.trade_ready !== false) {
    throw new Error(`Invalid ${market.toUpperCase()} Market Evidence research boundary.`);
  }
  if (!Array.isArray(payload.symbols) || payload.symbols.length === 0) {
    throw new Error(`Empty ${market.toUpperCase()} Market Evidence catalog.`);
  }
}

await rm(targetRoot, { recursive: true, force: true });
await copyJsonTree(sourceRoot, targetRoot);
await Promise.all(['us', 'cn'].map(validateCatalog));
console.log(`Published required Market Evidence 1.1 assets from ${sourceRoot}.`);
