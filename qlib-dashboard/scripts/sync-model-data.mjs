import { copyFile, lstat, mkdir, readFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(scriptDir, '..');
const repositoryRoot = resolve(dashboardRoot, '..');
const sourceRoot = join(repositoryRoot, 'data', 'research', 'model_data_bundle_v1');
const targetRoot = join(dashboardRoot, 'public', 'data');
const publishedFiles = [
  'model-data-readiness.json',
  'data-components.json',
  'training-profiles.json',
];

await mkdir(targetRoot, { recursive: true });

for (const name of publishedFiles) {
  const sourcePath = join(sourceRoot, name);
  const info = await lstat(sourcePath);
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new Error(`Model data publication requires a regular file: ${relative(sourceRoot, sourcePath)}`);
  }
  JSON.parse(await readFile(sourcePath, 'utf8'));
  await copyFile(sourcePath, join(targetRoot, name));
}

console.log(`Published ${publishedFiles.length} governed model data read models from ${sourceRoot}.`);
