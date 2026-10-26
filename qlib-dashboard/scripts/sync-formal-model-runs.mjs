import { copyFile, lstat, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(scriptDir, '..');
const repositoryRoot = resolve(dashboardRoot, '..');
const sourceRoot = join(repositoryRoot, 'data', 'research', 'formal_model_runs');
const targetRoot = join(dashboardRoot, 'public', 'data', 'formal-model-runs');

const digest = (body) => createHash('sha256').update(body).digest('hex');

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === 'object' && value !== null) {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stableValue(value[key])])
    );
  }
  return value;
}

function canonicalJson(value) {
  return `${JSON.stringify(stableValue(value))}\n`;
}

function computeBundleId(manifest) {
  const payload = { ...manifest };
  delete payload.bundle_id;
  return digest(canonicalJson(payload));
}

function sanitizeLineage(lineage) {
  const sanitized = JSON.parse(JSON.stringify(lineage));
  if (sanitized.source_evidence && typeof sanitized.source_evidence === 'object') {
    delete sanitized.source_evidence.operating_state;
  }
  delete sanitized.operating_state;
  delete sanitized.current_weights;
  delete sanitized.target_weights;
  return sanitized;
}

function hasOperationalLeakage(obj) {
  if (!obj || typeof obj !== 'object') return false;
  if ('operating_state' in obj) return true;
  for (const val of Object.values(obj)) {
    if (hasOperationalLeakage(val)) return true;
  }
  return false;
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

// Publish only the catalog-active runs as disposable public historical projections.
// Retained, pinned and superseded bundles are repository audit closures consumed by
// governed workflows, not static-site payload, so the browser bundle stays lean.
const catalogRaw = await readFile(join(sourceRoot, 'catalog.json'), 'utf8');
const sourceCatalog = JSON.parse(catalogRaw);
const publicCatalog = JSON.parse(catalogRaw);
const runDirectories = activeRunDirectories(sourceCatalog);

for (const runDirectory of runDirectories) {
  const sourceRunDir = join(sourceRoot, runDirectory);
  const targetRunDir = join(targetRoot, runDirectory);
  await mkdir(targetRunDir, { recursive: true });

  const manifestPath = join(runDirectory, 'manifest.json').replace(/\\/g, '/');
  const catalogRecord = publicCatalog.records.find((r) => r.manifest_path === manifestPath);
  if (!catalogRecord) {
    throw new Error(`Active run directory not found in catalog records: ${runDirectory}`);
  }

  const manifestBytes = await readFile(join(sourceRunDir, 'manifest.json'));
  if (digest(manifestBytes) !== catalogRecord.manifest_sha256) {
    throw new Error(`Formal manifest digest mismatch for ${catalogRecord.model_version_id}`);
  }
  const manifest = JSON.parse(manifestBytes.toString('utf8'));
  const originalBundleId = catalogRecord.bundle_id;
  const originalManifestSha = catalogRecord.manifest_sha256;

  let runProjected = false;
  const entries = await readdir(sourceRunDir, { withFileTypes: true });

  for (const entry of entries) {
    if (entry.name === 'manifest.json') continue; // handled after sections
    const sourceFilePath = join(sourceRunDir, entry.name);
    const targetFilePath = join(targetRunDir, entry.name);
    const info = await lstat(sourceFilePath);
    if (info.isSymbolicLink()) {
      throw new Error(`Formal model-run publication cannot follow symlink: ${relative(sourceRoot, sourceFilePath)}`);
    }
    if (!entry.isFile() || !entry.name.endsWith('.json')) {
      throw new Error(`Formal model-run publication accepts JSON files only: ${relative(sourceRoot, sourceFilePath)}`);
    }

    if (entry.name === 'lineage.json') {
      const lineageText = await readFile(sourceFilePath, 'utf8');
      const lineage = JSON.parse(lineageText);
      if (hasOperationalLeakage(lineage)) {
        const sanitized = sanitizeLineage(lineage);
        const encoded = canonicalJson(sanitized);
        await writeFile(targetFilePath, encoded, 'utf8');

        // Update section in manifest
        const lineageSection = manifest.sections.find((s) => s.section_id === 'lineage');
        if (lineageSection) {
          lineageSection.sha256 = digest(encoded);
          lineageSection.byte_size = Buffer.byteLength(encoded, 'utf8');
        }
        runProjected = true;
        continue;
      }
    }

    // Default: copy file as-is
    await copyFile(sourceFilePath, targetFilePath);
  }

  if (runProjected) {
    manifest.projection_contract = 'public_historical_projection_v1';
    manifest.source_identity = {
      canonical_bundle_id: originalBundleId,
      canonical_manifest_sha256: originalManifestSha,
    };
    manifest.bundle_id = computeBundleId(manifest);
    const manifestEncoded = canonicalJson(manifest);
    await writeFile(join(targetRunDir, 'manifest.json'), manifestEncoded, 'utf8');

    catalogRecord.canonical_bundle_id = originalBundleId;
    catalogRecord.canonical_manifest_sha256 = originalManifestSha;
    catalogRecord.bundle_id = manifest.bundle_id;
    catalogRecord.manifest_sha256 = digest(manifestEncoded);
    catalogRecord.projection_contract = 'public_historical_projection_v1';
  } else {
    await copyFile(join(sourceRunDir, 'manifest.json'), join(targetRunDir, 'manifest.json'));
  }
}

// Publish the public catalog and every top-level policy read model.
const publicCatalogEncoded = canonicalJson(publicCatalog);
await writeFile(join(targetRoot, 'catalog.json'), publicCatalogEncoded, 'utf8');

for (const entry of await readdir(sourceRoot, { withFileTypes: true })) {
  if (entry.isFile() && entry.name.endsWith('.json') && entry.name !== 'catalog.json') {
    await copyFile(join(sourceRoot, entry.name), join(targetRoot, entry.name));
  }
}
console.log(`Published ${runDirectories.length} catalog-active formal Model Run Bundle v2 assets from ${sourceRoot}.`);

// A disposable, compact view of the existing governed market evidence. Keep
// price bytes and formal event dates unchanged; do not ship factor panels or
// create another data source/evaluator for an instrument drill-down.
const marketSource = join(repositoryRoot, 'data', 'research', 'market_evidence');
const marketTarget = join(dashboardRoot, 'public', 'data', 'market-evidence');
const bindings = await Promise.all(publicCatalog.records.map(async (record) => {
  const body = await readFile(join(targetRoot, record.manifest_path));
  if (digest(body) !== record.manifest_sha256) throw new Error('Formal manifest digest changed during security projection');
  const manifest = JSON.parse(body);
  return {
    model_version_id: record.model_version_id,
    run_id: record.run_id,
    bundle_id: record.bundle_id,
    market: manifest.comparability_key.market,
  };
}));
await rm(marketTarget, { recursive: true, force: true });
for (const market of ['us', 'cn']) {
  const body = await readFile(join(marketSource, market, 'catalog.json'));
  const source = JSON.parse(body);
  if (source.market !== market || source.research_only !== true || source.trade_ready !== false) throw new Error('Invalid market price source boundary');
  const formalBindings = bindings.filter((binding) => binding.market === market);
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
    const events = value.formal_model_events.filter((event) => formalBindings.some((binding) =>
      binding.model_version_id === event.model_id && binding.run_id === event.run_id));
    const projection = {
      schema_version: value.schema_version, view: 'security_detail_v1', evidence_type: value.evidence_type,
      market, symbol: value.symbol, instrument_id: value.instrument_id, name: value.name, cutoff: value.cutoff,
      provider_manifest_sha256: value.provider_manifest_sha256, source_sha256: row.sha256,
      bars: value.bars, formal_model_events: events, research_only: true, trade_ready: false,
    };
    const encoded = JSON.stringify(projection) + '\n';
    await writeFile(join(marketTarget, market, row.path), encoded, 'utf8');
    symbols.push({
      ...row, sha256: digest(encoded), source_sha256: row.sha256,
      formal_event_count: events.length, factor_series_available: false,
    });
  }
  const projection = {
    schema_version: source.schema_version, view: 'security_detail_v1', evidence_type: source.evidence_type,
    market, cutoff: source.cutoff, provider_manifest_sha256: source.provider_manifest_sha256,
    source_catalog_sha256: digest(body), formal_bindings: formalBindings, symbols, research_only: true, trade_ready: false,
  };
  await writeFile(join(marketTarget, market, 'catalog.json'), JSON.stringify(projection) + '\n', 'utf8');
  console.log(`Published ${symbols.length} compact ${market.toUpperCase()} price histories with exact formal model bindings.`);
}
