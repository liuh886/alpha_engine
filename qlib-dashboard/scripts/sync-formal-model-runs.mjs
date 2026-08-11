import { copyFile, lstat, mkdir, readFile, readdir, rm } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const FORMAL_EVIDENCE_CONTRACT = 'native_formal_bundle_v2';
const scriptDir = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(scriptDir, '..');
const repositoryRoot = resolve(dashboardRoot, '..');
const sourceRoot = join(repositoryRoot, 'data', 'research', 'formal_model_runs');
const targetRoot = join(dashboardRoot, 'public', 'data', 'formal-model-runs');

async function readJson(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

async function requireProductionEvidenceContract() {
  const catalog = await readJson(join(sourceRoot, 'catalog.json'));
  if (catalog.channel !== 'formal' || !Array.isArray(catalog.records) || catalog.records.length === 0) {
    throw new Error('Formal model-run publication requires a non-empty formal catalog.');
  }
  for (const record of catalog.records) {
    const manifestPath = join(sourceRoot, String(record.manifest_path ?? ''));
    const manifest = await readJson(manifestPath);
    const summarySection = manifest.sections?.find((section) => section.section_id === 'summary');
    if (summarySection?.availability_status !== 'available' || !summarySection.path) {
      throw new Error(`${record.model_version_id}: formal summary is unavailable.`);
    }
    const summary = await readJson(join(dirname(manifestPath), summarySection.path));
    if (summary.evidence_contract !== FORMAL_EVIDENCE_CONTRACT) {
      throw new Error(`${record.model_version_id}: formal evidence production contract is missing.`);
    }
  }
}

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

await requireProductionEvidenceContract();
await rm(targetRoot, { recursive: true, force: true });
await copyJsonTree(sourceRoot, targetRoot);
console.log(`Published formal Model Run Bundle v2 assets from ${sourceRoot} under ${FORMAL_EVIDENCE_CONTRACT}.`);
