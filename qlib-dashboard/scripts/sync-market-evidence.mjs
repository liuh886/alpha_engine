import { copyFile, lstat, mkdir, readdir, rm } from 'node:fs/promises';
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

await rm(targetRoot, { recursive: true, force: true });
try {
  await copyJsonTree(sourceRoot, targetRoot);
  console.log(`Published market evidence assets from ${sourceRoot}.`);
} catch (error) {
  if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') {
    console.log('Market evidence is not published yet; Security Explorer will fail closed.');
  } else {
    throw error;
  }
}
