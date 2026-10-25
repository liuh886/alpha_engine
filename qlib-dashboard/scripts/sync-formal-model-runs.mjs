import { copyFile, lstat, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
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

// A disposable, compact view of the existing governed market evidence. Keep
// price bytes and formal event dates unchanged; do not ship factor panels or
// create another data source/evaluator for an instrument drill-down.
const marketSource = join(repositoryRoot, 'data', 'research', 'market_evidence');
const marketTarget = join(dashboardRoot, 'public', 'data', 'market-evidence');
const digest = body => createHash('sha256').update(body).digest('hex');
const bindings = await Promise.all(catalog.records.map(async record => {
  const body = await readFile(join(sourceRoot, record.manifest_path));
  if (digest(body) !== record.manifest_sha256) throw new Error('Formal manifest digest changed during security projection');
  const manifest = JSON.parse(body);
  return { model_version_id: record.model_version_id, run_id: record.run_id, bundle_id: record.bundle_id,
    market: manifest.comparability_key.market };
}));
await rm(marketTarget, { recursive: true, force: true });
for (const market of ['us', 'cn']) {
  const body = await readFile(join(marketSource, market, 'catalog.json'));
  const source = JSON.parse(body);
  if (source.market !== market || source.research_only !== true || source.trade_ready !== false) throw new Error('Invalid market price source boundary');
  const formalBindings = bindings.filter(binding => binding.market === market);
  const symbols = [];
  await mkdir(join(marketTarget, market, 'symbols'), { recursive: true });
  for (const row of source.symbols) {
    if (!/^[A-Za-z0-9._-]+$/.test(row.symbol) || row.path !== `symbols/${row.symbol}.json`) throw new Error('Unsafe security source path');
    const path = join(marketSource, market, row.path);
    if ((await lstat(path)).isSymbolicLink()) throw new Error('Security projection cannot follow symlinks');
    const bytes = await readFile(path);
    if (digest(bytes) !== row.sha256) throw new Error(`Security source checksum mismatch: ${market}/${row.symbol}`);
    const value = JSON.parse(bytes);
    if (value.market !== market || value.symbol !== row.symbol || value.instrument_id !== row.instrument_id
      || value.provider_manifest_sha256 !== source.provider_manifest_sha256 || value.research_only !== true || value.trade_ready !== false) throw new Error('Security source identity mismatch');
    const events = value.formal_model_events.filter(event => formalBindings.some(binding =>
      binding.model_version_id === event.model_id && binding.run_id === event.run_id));
    const projection = { schema_version: value.schema_version, view: 'security_detail_v1', evidence_type: value.evidence_type,
      market, symbol: value.symbol, instrument_id: value.instrument_id, name: value.name, cutoff: value.cutoff,
      provider_manifest_sha256: value.provider_manifest_sha256, source_sha256: row.sha256,
      bars: value.bars, formal_model_events: events, research_only: true, trade_ready: false };
    const encoded = JSON.stringify(projection) + '\n';
    await writeFile(join(marketTarget, market, row.path), encoded, 'utf8');
    symbols.push({ ...row, sha256: digest(encoded), source_sha256: row.sha256,
      formal_event_count: events.length, factor_series_available: false });
  }
  const projection = { schema_version: source.schema_version, view: 'security_detail_v1', evidence_type: source.evidence_type,
    market, cutoff: source.cutoff, provider_manifest_sha256: source.provider_manifest_sha256,
    source_catalog_sha256: digest(body), formal_bindings: formalBindings, symbols, research_only: true, trade_ready: false };
  await writeFile(join(marketTarget, market, 'catalog.json'), JSON.stringify(projection) + '\n', 'utf8');
  console.log(`Published ${symbols.length} compact ${market.toUpperCase()} price histories with exact formal model bindings.`);
}
