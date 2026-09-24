import { copyFile, lstat, mkdir, readFile, readdir, rm } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(scriptDir, '..');
const repositoryRoot = resolve(dashboardRoot, '..');
const sourceRoot = join(repositoryRoot, 'data', 'research', 'formal_model_runs');
const targetRoot = join(dashboardRoot, 'public', 'data', 'formal-model-runs');

async function copyJsonTree(source, target) {
  const entries = await readdir(source, { withFileTypes: true });
  await mkdir(target, { recursive: true });
  for (const entry of entries) {
    const sourcePath = join(source, entry.name);
    const targetPath = join(target, entry.name);
    const info = await lstat(sourcePath);
    if (info.isSymbolicLink()) throw new Error(`Formal model-run publication cannot follow symlink: ${relative(sourceRoot, sourcePath)}`);
    if (entry.isDirectory()) {
      await copyJsonTree(sourcePath, targetPath);
      continue;
    }
    if (!entry.isFile() || !entry.name.endsWith('.json')) {
      throw new Error(`Formal model-run publication accepts JSON files only: ${relative(sourceRoot, sourcePath)}`);
    }
    await copyFile(sourcePath, targetPath);
  }
}

function activeRunDirectories(catalog) {
  if (!catalog || !Array.isArray(catalog.records)) {
    throw new Error('Formal Model Run Bundle v2 catalog records are missing');
  }
  const directories = new Set();
  for (const record of catalog.records) {
    const manifestPath = String(record?.manifest_path ?? '');
    if (!manifestPath.endsWith('/manifest.json') || manifestPath.startsWith('/') || manifestPath.includes('..')) {
      throw new Error(`Formal catalog record has an unsafe manifest path: ${manifestPath}`);
    }
    directories.add(dirname(manifestPath));
  }
  return [...directories].sort();
}

await rm(targetRoot, { recursive: true, force: true });
await mkdir(targetRoot, { recursive: true });

// Publish the catalog and every top-level policy read model.
for (const entry of await readdir(sourceRoot, { withFileTypes: true })) {
  if (entry.isFile() && entry.name.endsWith('.json')) {
    await copyFile(join(sourceRoot, entry.name), join(targetRoot, entry.name));
  }
}

// Publish only the catalog-active runs. Retained, pinned and superseded
// bundles are repository audit closures consumed by governed workflows, not
// static-site payload, so the browser bundle stays lean.
const catalog = JSON.parse(await readFile(join(sourceRoot, 'catalog.json'), 'utf8'));
const runDirectories = activeRunDirectories(catalog);
for (const runDirectory of runDirectories) {
  await copyJsonTree(join(sourceRoot, runDirectory), join(targetRoot, runDirectory));
}
console.log(`Published ${runDirectories.length} catalog-active formal Model Run Bundle v2 assets from ${sourceRoot}.`);
