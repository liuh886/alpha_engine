import { createHash } from 'node:crypto';
import { lstat, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

// Derived research metrics are a disposable public projection of sealed
// repository evidence. This module copies validated artifact values; it does
// not compute, retain or promote a new evidence authority. Every rejection is
// fail-closed so a malformed derivation can never reach `public/data`.

export const DERIVED_EVIDENCE_TYPE = 'derived_formal_benchmark_excess';
export const DERIVED_SCHEMA_VERSION = '1.0';
export const DERIVED_CATALOG_SCHEMA_VERSION = 'derived_metric_catalog_v1';
export const DERIVED_METHOD_ID = 'compounded_relative_excess';
export const DERIVED_EXCESS_TOLERANCE = 1e-12;

const DERIVATION_ID = /^[a-z0-9][a-z0-9._-]{0,127}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const PUBLIC_ARTIFACT_PREFIX = 'derived-metrics/';

const PRIVATE_KEYS = new Set([
  'operating_state',
  'current_weights',
  'target_weights',
  'trades',
  'decision_reason',
  'decision_state',
  'positions',
]);

export class DerivedMetricPublicationError extends Error {
  constructor(message) {
    super(`Derived metric publication rejected: ${message}`);
    this.name = 'DerivedMetricPublicationError';
  }
}

function fail(message) {
  throw new DerivedMetricPublicationError(message);
}

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stableValue(value[key])]),
    );
  }
  return value;
}

/** Canonical JSON with sorted keys and one trailing newline. */
export function canonicalJson(value) {
  return `${JSON.stringify(stableValue(value))}\n`;
}

export function sha256Hex(body) {
  return createHash('sha256').update(body).digest('hex');
}

export function isValidIsoDate(value) {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function isPrivateDerivedKey(key) {
  const text = String(key);
  return PRIVATE_KEYS.has(text) || text.startsWith('weight_') || text.endsWith('_weight');
}

/**
 * Recursively locate the first private/operational key. Returns its JSON path
 * or null. Values are never inspected; only key names can leak runtime state.
 */
export function findPrivateDerivedLeakage(value, path = '$') {
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const found = findPrivateDerivedLeakage(value[index], `${path}[${index}]`);
      if (found) return found;
    }
    return null;
  }
  if (isRecord(value)) {
    for (const [key, child] of Object.entries(value)) {
      if (isPrivateDerivedKey(key)) return `${path}.${key}`;
      const found = findPrivateDerivedLeakage(child, `${path}.${key}`);
      if (found) return found;
    }
  }
  return null;
}

function requireFinite(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    fail(`${label} must be a finite number`);
  }
  return value;
}

function validateWindow(window) {
  if (!isRecord(window) || Object.keys(window).length === 0) {
    fail('window must be a non-empty object');
  }
  for (const field of ['declared_start', 'observed_start', 'observed_end']) {
    if (!isValidIsoDate(window[field])) {
      fail(`window.${field} must be an ISO date`);
    }
  }
  for (const field of ['declared_end', 'evidence_cutoff']) {
    if (window[field] !== undefined && !isValidIsoDate(window[field])) {
      fail(`window.${field} must be an ISO date when declared`);
    }
  }
  if (window.observed_start > window.observed_end) {
    fail('window.observed_start must not follow window.observed_end');
  }
  if (window.declared_end !== undefined && window.declared_start > window.declared_end) {
    fail('window.declared_start must not follow window.declared_end');
  }
  if (!Number.isInteger(window.observation_count) || window.observation_count <= 0) {
    fail('window.observation_count must be a positive integer');
  }
}

/**
 * Validate the sealed artifact contract before any byte is published. This is
 * intentionally independent of the formal catalog so malformed artifacts fail
 * with an artifact-local message.
 */
export function validateDerivedMetricArtifact(artifact, label = 'derived artifact') {
  if (!isRecord(artifact)) fail(`${label}: artifact must be an object`);
  const leakage = findPrivateDerivedLeakage(artifact);
  if (leakage) fail(`${label}: private/operational field is not publishable (${leakage})`);
  if (artifact.evidence_type !== DERIVED_EVIDENCE_TYPE) {
    fail(`${label}: evidence_type must be ${DERIVED_EVIDENCE_TYPE}`);
  }
  if (artifact.schema_version !== DERIVED_SCHEMA_VERSION) {
    fail(`${label}: schema_version must be ${DERIVED_SCHEMA_VERSION}`);
  }
  if (typeof artifact.derivation_id !== 'string' || !DERIVATION_ID.test(artifact.derivation_id)) {
    fail(`${label}: derivation_id is not a safe public identifier`);
  }

  const boundaries = artifact.boundaries;
  if (!isRecord(boundaries)) fail(`${label}: boundaries are missing`);
  if (boundaries.research_only !== true) fail(`${label}: boundaries.research_only must be true`);
  if (boundaries.trade_ready !== false) fail(`${label}: boundaries.trade_ready must be false`);
  if (boundaries.descriptive_historical_metric !== true) {
    fail(`${label}: boundaries.descriptive_historical_metric must be true`);
  }
  if (boundaries.live_signal !== false) fail(`${label}: boundaries.live_signal must be false`);

  const strategy = artifact.strategy;
  if (!isRecord(strategy)) fail(`${label}: strategy identity is missing`);
  for (const field of ['model_family_id', 'model_version_id', 'run_id']) {
    if (typeof strategy[field] !== 'string' || !strategy[field].trim()) {
      fail(`${label}: strategy.${field} is missing`);
    }
  }
  if (typeof strategy.manifest_sha256 !== 'string' || !SHA256.test(strategy.manifest_sha256)) {
    fail(`${label}: strategy.manifest_sha256 is invalid`);
  }

  if (!isRecord(artifact.method) || artifact.method.method_id !== DERIVED_METHOD_ID) {
    fail(`${label}: method.method_id must be ${DERIVED_METHOD_ID}`);
  }

  const result = artifact.result;
  if (!isRecord(result)) fail(`${label}: result is missing`);
  const strategyReturn = requireFinite(result.strategy_cumulative_return, `${label}: result.strategy_cumulative_return`);
  const benchmarkReturn = requireFinite(result.benchmark_cumulative_return, `${label}: result.benchmark_cumulative_return`);
  requireFinite(result.excess_return, `${label}: result.excess_return`);
  if (strategyReturn <= -1 || benchmarkReturn <= -1) {
    fail(`${label}: cumulative returns must exceed -1 to support compounded comparison`);
  }

  validateWindow(artifact.window);
  return artifact;
}

/** Locate the unique public formal catalog record bound by the artifact. */
export function findPublishedFormalRecord(artifact, formalCatalog) {
  if (!isRecord(formalCatalog) || !Array.isArray(formalCatalog.records)) {
    fail('public formal catalog records are missing');
  }
  if (formalCatalog.research_only !== true || formalCatalog.trade_ready !== false) {
    fail('public formal catalog research boundary is invalid');
  }
  const strategy = artifact.strategy;
  const matches = formalCatalog.records.filter((record) => isRecord(record)
    && record.model_version_id === strategy.model_version_id
    && record.run_id === strategy.run_id
    && record.manifest_sha256 === strategy.manifest_sha256);
  if (matches.length !== 1) {
    fail(`${artifact.derivation_id}: derivation matches ${matches.length} public formal catalog records`);
  }
  const record = matches[0];
  if (record.model_family_id !== strategy.model_family_id) {
    fail(`${artifact.derivation_id}: model family does not match the public formal catalog`);
  }
  const manifestPath = String(record.manifest_path ?? '');
  if (!manifestPath.endsWith('/manifest.json') || manifestPath.startsWith('/')
      || manifestPath.includes('..') || manifestPath.includes('\\')) {
    fail(`${artifact.derivation_id}: public formal manifest path is unsafe`);
  }
  return record;
}

/**
 * Bind the artifact to the published formal run. The artifact's performance
 * input SHA must be the manifest's own performance section, and the declared
 * compounded excess must reconcile from the two declared cumulative returns.
 */
export function bindDerivedMetricToFormalRun(artifact, formalCatalog, manifest) {
  const record = findPublishedFormalRecord(artifact, formalCatalog);
  if (!isRecord(manifest)) fail(`${artifact.derivation_id}: public formal manifest is unavailable`);
  if (manifest.research_only !== true || manifest.trade_ready !== false) {
    fail(`${artifact.derivation_id}: public formal manifest boundary is invalid`);
  }
  if (manifest.model_family_id !== artifact.strategy.model_family_id
      || manifest.model_version_id !== artifact.strategy.model_version_id
      || manifest.run_id !== artifact.strategy.run_id) {
    fail(`${artifact.derivation_id}: public formal manifest identity mismatch`);
  }
  const performanceSection = Array.isArray(manifest.sections)
    ? manifest.sections.find((section) => isRecord(section) && section.section_id === 'performance')
    : undefined;
  if (!performanceSection || performanceSection.availability_status !== 'available'
      || typeof performanceSection.sha256 !== 'string' || !SHA256.test(performanceSection.sha256)) {
    fail(`${artifact.derivation_id}: public formal performance section is unavailable`);
  }

  if (!Array.isArray(artifact.inputs)) fail(`${artifact.derivation_id}: inputs are missing`);
  const performanceInputs = artifact.inputs.filter(
    (input) => isRecord(input) && input.role === 'formal_performance',
  );
  if (performanceInputs.length !== 1) {
    fail(`${artifact.derivation_id}: exactly one formal_performance input is required`);
  }
  const performanceInput = performanceInputs[0];
  if (performanceInput.manifest_section !== 'performance') {
    fail(`${artifact.derivation_id}: formal_performance input must bind manifest_section=performance`);
  }
  if (performanceInput.sha256 !== performanceSection.sha256) {
    fail(`${artifact.derivation_id}: formal_performance input SHA does not match the public formal manifest`);
  }
  if (typeof performanceInput.bytes === 'number'
      && Number.isInteger(performanceSection.byte_size)
      && performanceInput.bytes !== performanceSection.byte_size) {
    fail(`${artifact.derivation_id}: formal_performance input byte size does not match the public formal manifest`);
  }

  const { strategy_cumulative_return: strategyReturn,
    benchmark_cumulative_return: benchmarkReturn,
    excess_return: declaredExcess } = artifact.result;
  const recomputed = (1 + strategyReturn) / (1 + benchmarkReturn) - 1;
  if (!Number.isFinite(recomputed)
      || Math.abs(recomputed - declaredExcess) > DERIVED_EXCESS_TOLERANCE) {
    fail(`${artifact.derivation_id}: compounded excess does not reconcile within ${DERIVED_EXCESS_TOLERANCE}`);
  }
  return { record, performanceSection, performanceInput, recomputed };
}

function selectGeneratedAt(artifacts, formalCatalog, generatedAt) {
  if (typeof generatedAt === 'string' && generatedAt.trim()) return generatedAt;
  const artifactTimes = artifacts
    .map((artifact) => artifact?.strategy?.generated_at)
    .filter((value) => typeof value === 'string' && value.trim())
    .sort();
  if (artifactTimes.length > 0) return artifactTimes[artifactTimes.length - 1];
  if (typeof formalCatalog?.generated_at === 'string' && formalCatalog.generated_at.trim()) {
    return formalCatalog.generated_at;
  }
  fail('catalog generated_at must be sourced from an artifact or the formal catalog');
  return null;
}

/**
 * Build the catalog object. Entries are reduced to the published contract and
 * sorted by derivation_id; no wall-clock value is introduced here.
 */
export function buildDerivedMetricCatalog(entries, generatedAt) {
  if (typeof generatedAt !== 'string' || !generatedAt.trim()) {
    fail('catalog generated_at is required');
  }
  const sorted = [...entries].sort((left, right) => left.derivation_id.localeCompare(right.derivation_id));
  const seen = new Set();
  const publishedEntries = sorted.map((entry) => {
    if (!isRecord(entry)) fail('catalog entry must be an object');
    if (typeof entry.derivation_id !== 'string' || !DERIVATION_ID.test(entry.derivation_id)) {
      fail('catalog entry derivation_id is invalid');
    }
    if (seen.has(entry.derivation_id)) fail(`duplicate derivation_id ${entry.derivation_id}`);
    seen.add(entry.derivation_id);
    if (entry.evidence_type !== DERIVED_EVIDENCE_TYPE) {
      fail(`${entry.derivation_id}: catalog entry evidence_type is invalid`);
    }
    for (const field of ['model_version_id', 'run_id']) {
      if (typeof entry[field] !== 'string' || !entry[field].trim()) {
        fail(`${entry.derivation_id}: catalog entry ${field} is missing`);
      }
    }
    if (typeof entry.manifest_sha256 !== 'string' || !SHA256.test(entry.manifest_sha256)) {
      fail(`${entry.derivation_id}: catalog entry manifest_sha256 is invalid`);
    }
    if (entry.path !== `${PUBLIC_ARTIFACT_PREFIX}${entry.derivation_id}.json`) {
      fail(`${entry.derivation_id}: catalog entry path is not the published artifact path`);
    }
    if (typeof entry.sha256 !== 'string' || !SHA256.test(entry.sha256)) {
      fail(`${entry.derivation_id}: catalog entry sha256 is invalid`);
    }
    if (!Number.isInteger(entry.byte_size) || entry.byte_size <= 0) {
      fail(`${entry.derivation_id}: catalog entry byte_size is invalid`);
    }
    return {
      derivation_id: entry.derivation_id,
      evidence_type: entry.evidence_type,
      model_version_id: entry.model_version_id,
      run_id: entry.run_id,
      manifest_sha256: entry.manifest_sha256,
      path: entry.path,
      sha256: entry.sha256,
      byte_size: entry.byte_size,
    };
  });
  return {
    schema_version: DERIVED_CATALOG_SCHEMA_VERSION,
    research_only: true,
    trade_ready: false,
    generated_at: generatedAt,
    entries: publishedEntries,
  };
}

/**
 * Pure publication builder. `manifests` maps a public manifest SHA-256 to its
 * parsed manifest payload so the caller owns every file read.
 */
export function buildDerivedMetricPublication({
  artifacts,
  formalCatalog,
  manifests,
  generatedAt,
}) {
  if (!Array.isArray(artifacts)) fail('artifacts must be an array');
  const manifestFor = (record) => {
    if (manifests instanceof Map) return manifests.get(record.manifest_sha256);
    if (isRecord(manifests)) return manifests[record.manifest_sha256];
    return undefined;
  };
  const selected = artifacts.filter(
    (artifact) => isRecord(artifact) && artifact.evidence_type === DERIVED_EVIDENCE_TYPE,
  );
  const files = [];
  const entries = [];
  for (const artifact of selected) {
    const label = typeof artifact.derivation_id === 'string' ? artifact.derivation_id : 'derived artifact';
    validateDerivedMetricArtifact(artifact, label);
    const record = findPublishedFormalRecord(artifact, formalCatalog);
    bindDerivedMetricToFormalRun(artifact, formalCatalog, manifestFor(record));
    const encoded = canonicalJson(artifact);
    const entry = {
      derivation_id: artifact.derivation_id,
      evidence_type: DERIVED_EVIDENCE_TYPE,
      model_version_id: artifact.strategy.model_version_id,
      run_id: artifact.strategy.run_id,
      manifest_sha256: artifact.strategy.manifest_sha256,
      path: `${PUBLIC_ARTIFACT_PREFIX}${artifact.derivation_id}.json`,
      sha256: sha256Hex(encoded),
      byte_size: Buffer.byteLength(encoded, 'utf8'),
    };
    files.push({
      derivation_id: artifact.derivation_id,
      path: entry.path,
      encoded,
      sha256: entry.sha256,
      byte_size: entry.byte_size,
    });
    entries.push(entry);
  }
  const catalog = buildDerivedMetricCatalog(
    entries,
    selectGeneratedAt(selected, formalCatalog, generatedAt),
  );
  return { files, catalog, catalogEncoded: canonicalJson(catalog) };
}

/**
 * Read and select sealed derived artifacts. A missing source directory is an
 * intentional empty set; malformed JSON or symlinks still fail closed.
 */
export async function readDerivedArtifacts(sourceRoot) {
  let entries;
  try {
    entries = await readdir(sourceRoot, { withFileTypes: true });
  } catch (error) {
    if (error?.code === 'ENOENT') return [];
    throw error;
  }
  entries.sort((left, right) => left.name.localeCompare(right.name));
  const artifacts = [];
  for (const entry of entries) {
    if (entry.isSymbolicLink()) {
      fail(`${entry.name}: symlinked derived artifacts are not publishable`);
    }
    if (entry.isDirectory()) {
      fail(`${entry.name}: nested directories are not derived metric artifacts`);
    }
    if (!entry.isFile() || !entry.name.endsWith('.json')) continue;
    const bytes = await readFile(join(sourceRoot, entry.name));
    let artifact;
    try {
      artifact = JSON.parse(bytes.toString('utf8'));
    } catch {
      fail(`${entry.name}: derived artifact is not valid JSON`);
    }
    if (!isRecord(artifact) || artifact.evidence_type !== DERIVED_EVIDENCE_TYPE) continue;
    artifacts.push(artifact);
  }
  return artifacts;
}

/**
 * Publish the validated derived-metric projection beside the formal public
 * catalog. Runs after `sync-formal-model-runs.mjs` so every binding resolves
 * against the final public manifest bytes.
 */
export async function publishDerivedMetrics({ repositoryRoot, dashboardRoot }) {
  if (!repositoryRoot || !dashboardRoot) {
    throw new Error('Derived metric publication requires repositoryRoot and dashboardRoot.');
  }
  const sourceRoot = join(repositoryRoot, 'data', 'research', 'derived_metrics');
  const formalRoot = join(dashboardRoot, 'public', 'data', 'formal-model-runs');
  const targetRoot = join(dashboardRoot, 'public', 'data', 'derived-metrics');

  const artifacts = await readDerivedArtifacts(sourceRoot);
  let formalCatalog;
  try {
    formalCatalog = JSON.parse(await readFile(join(formalRoot, 'catalog.json'), 'utf8'));
  } catch (error) {
    fail(`public formal catalog is unavailable: ${error instanceof Error ? error.message : String(error)}`);
  }

  const manifests = new Map();
  for (const artifact of artifacts) {
    const record = findPublishedFormalRecord(artifact, formalCatalog);
    if (manifests.has(record.manifest_sha256)) continue;
    const manifestBytes = await readFile(join(formalRoot, record.manifest_path));
    if (sha256Hex(manifestBytes) !== record.manifest_sha256) {
      fail(`${artifact.derivation_id}: public formal manifest digest mismatch`);
    }
    manifests.set(record.manifest_sha256, JSON.parse(manifestBytes.toString('utf8')));
  }

  const publication = buildDerivedMetricPublication({ artifacts, formalCatalog, manifests });
  await rm(targetRoot, { recursive: true, force: true });
  await mkdir(targetRoot, { recursive: true });
  for (const file of publication.files) {
    await writeFile(join(targetRoot, `${file.derivation_id}.json`), file.encoded, 'utf8');
  }
  await writeFile(join(targetRoot, 'catalog.json'), publication.catalogEncoded, 'utf8');
  console.log(
    `Published ${publication.files.length} derived metric artifact(s) `
    + `with a ${publication.catalog.entries.length}-entry disposable catalog.`,
  );
  return publication;
}
