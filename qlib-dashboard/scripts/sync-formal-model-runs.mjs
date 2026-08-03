import { copyFile, lstat, mkdir, readdir, rm } from 'node:fs/promises';
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

await rm(targetRoot, { recursive: true, force: true });
await copyJsonTree(sourceRoot, targetRoot);
console.log(`Published formal Model Run Bundle v2 assets from ${sourceRoot}.`);
