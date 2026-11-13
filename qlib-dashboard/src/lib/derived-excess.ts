import { sha256Text } from './model-run-bundle-v2';
import type { GovernedRunSummary } from './governed-run';

/**
 * A sealed derived benchmark-excess artifact bound to one accepted formal run.
 * This loader only reads the disposable public projection; the artifact (not
 * the run's performance rows) is the authority for every displayed number.
 */
export const DERIVED_EXCESS_EVIDENCE_TYPE = 'derived_formal_benchmark_excess' as const;
export const DERIVED_EXCESS_SCHEMA_VERSION = '1.0' as const;
export const DERIVED_METRIC_CATALOG_SCHEMA_VERSION = 'derived_metric_catalog_v1' as const;
export const DERIVED_EXCESS_TOLERANCE = 1e-12;

export type DerivedExcessErrorReason =
  | 'catalog_unavailable'
  | 'catalog_invalid'
  | 'artifact_unavailable'
  | 'artifact_invalid'
  | 'artifact_hash_mismatch'
  | 'schema_mismatch'
  | 'boundary_mismatch'
  | 'identity_mismatch'
  | 'performance_unavailable'
  | 'performance_sha_mismatch'
  | 'result_invalid'
  | 'reconciliation_mismatch'
  | 'window_invalid'
  | 'private_field';

export class DerivedExcessError extends Error {
  readonly reason: DerivedExcessErrorReason;

  constructor(reason: DerivedExcessErrorReason, message: string) {
    super(message);
    this.name = 'DerivedExcessError';
    this.reason = reason;
  }
}

export interface DerivedExcessBoundaries {
  research_only: true;
  trade_ready: false;
  descriptive_historical_metric: true;
  live_signal: false;
}

export interface DerivedExcessResult {
  strategy_cumulative_return: number;
  benchmark_cumulative_return: number;
  excess_return: number;
}

export interface DerivedExcessWindow {
  declared_start: string;
  declared_end: string | null;
  observed_start: string;
  observed_end: string;
  evidence_cutoff: string | null;
  observation_count: number;
}

export interface DerivedExcessBenchmark {
  comparability_id: string;
  declared_identity: string;
  series_semantics: string | null;
}

/** Validated metadata a consumer may render beside a formal run. */
export interface DerivedExcess {
  key: string;
  derivationId: string;
  schemaVersion: typeof DERIVED_EXCESS_SCHEMA_VERSION;
  evidenceType: typeof DERIVED_EXCESS_EVIDENCE_TYPE;
  boundaries: DerivedExcessBoundaries;
  modelFamilyId: string;
  modelVersionId: string;
  runId: string;
  manifestSha256: string;
  methodId: 'compounded_relative_excess';
  result: DerivedExcessResult;
  window: DerivedExcessWindow;
  benchmark: DerivedExcessBenchmark;
  /** `Derived · vs QQQ · 2024-01-30 → 2026-11-10 · 699 observations` */
  label: string;
}

interface DerivedMetricCatalogEntry {
  derivation_id: string;
  evidence_type: typeof DERIVED_EXCESS_EVIDENCE_TYPE;
  model_version_id: string;
  run_id: string;
  manifest_sha256: string;
  path: string;
  sha256: string;
  byte_size: number;
}

interface DerivedMetricCatalog {
  schema_version: typeof DERIVED_METRIC_CATALOG_SCHEMA_VERSION;
  research_only: true;
  trade_ready: false;
  generated_at: string;
  entries: DerivedMetricCatalogEntry[];
}

const SHA256 = /^[a-f0-9]{64}$/;
const SAFE_DERIVATION_ID = /^[a-z0-9][a-z0-9._-]{0,127}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const PRIVATE_KEYS = new Set([
  'operating_state',
  'current_weights',
  'target_weights',
  'trades',
  'decision_reason',
  'decision_state',
  'positions',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function fail(reason: DerivedExcessErrorReason, message: string): never {
  throw new DerivedExcessError(reason, message);
}

function isValidIsoDate(value: unknown): value is string {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function isPrivateKey(key: string): boolean {
  return PRIVATE_KEYS.has(key) || key.startsWith('weight_') || key.endsWith('_weight');
}

function findPrivateField(value: unknown, path = '$'): string | null {
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const found = findPrivateField(value[index], `${path}[${index}]`);
      if (found) return found;
    }
    return null;
  }
  if (isRecord(value)) {
    for (const [key, child] of Object.entries(value)) {
      if (isPrivateKey(key)) return `${path}.${key}`;
      const found = findPrivateField(child, `${path}.${key}`);
      if (found) return found;
    }
  }
  return null;
}

function dataRoot(): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}data/`;
}

function parseCatalogEntry(raw: unknown, index: number): DerivedMetricCatalogEntry {
  if (!isRecord(raw)) fail('catalog_invalid', `Derived metric catalog entry ${index} is invalid.`);
  const derivationId = String(raw.derivation_id ?? '');
  if (!SAFE_DERIVATION_ID.test(derivationId)) {
    fail('catalog_invalid', `Derived metric catalog entry ${index} has an unsafe derivation_id.`);
  }
  if (raw.evidence_type !== DERIVED_EXCESS_EVIDENCE_TYPE) {
    fail('catalog_invalid', `Derived metric catalog entry ${derivationId} has an unexpected evidence_type.`);
  }
  const modelVersionId = String(raw.model_version_id ?? '');
  const runId = String(raw.run_id ?? '');
  const manifestSha256 = String(raw.manifest_sha256 ?? '');
  if (!modelVersionId || !runId || !SHA256.test(manifestSha256)) {
    fail('catalog_invalid', `Derived metric catalog entry ${derivationId} has an incomplete run identity.`);
  }
  const path = String(raw.path ?? '');
  if (path !== `derived-metrics/${derivationId}.json`) {
    fail('catalog_invalid', `Derived metric catalog entry ${derivationId} has an unsafe artifact path.`);
  }
  const sha256 = String(raw.sha256 ?? '');
  if (!SHA256.test(sha256)) {
    fail('catalog_invalid', `Derived metric catalog entry ${derivationId} has an invalid artifact digest.`);
  }
  const byteSize = raw.byte_size;
  if (typeof byteSize !== 'number' || !Number.isSafeInteger(byteSize) || byteSize <= 0) {
    fail('catalog_invalid', `Derived metric catalog entry ${derivationId} has an invalid byte size.`);
  }
  return {
    derivation_id: derivationId,
    evidence_type: DERIVED_EXCESS_EVIDENCE_TYPE,
    model_version_id: modelVersionId,
    run_id: runId,
    manifest_sha256: manifestSha256,
    path,
    sha256,
    byte_size: byteSize,
  };
}

function parseCatalog(payload: unknown): DerivedMetricCatalog {
  if (!isRecord(payload) || payload.schema_version !== DERIVED_METRIC_CATALOG_SCHEMA_VERSION) {
    fail('catalog_invalid', 'Derived metric catalog schema is invalid.');
  }
  if (payload.research_only !== true || payload.trade_ready !== false) {
    fail('catalog_invalid', 'Derived metric catalog research boundary is invalid.');
  }
  if (typeof payload.generated_at !== 'string' || !payload.generated_at.trim() || !Array.isArray(payload.entries)) {
    fail('catalog_invalid', 'Derived metric catalog metadata is incomplete.');
  }
  const seen = new Set<string>();
  const entries = payload.entries.map((raw, index) => {
    const entry = parseCatalogEntry(raw, index);
    if (seen.has(entry.derivation_id)) {
      fail('catalog_invalid', `Duplicate derived metric derivation_id: ${entry.derivation_id}`);
    }
    seen.add(entry.derivation_id);
    return entry;
  });
  return {
    schema_version: DERIVED_METRIC_CATALOG_SCHEMA_VERSION,
    research_only: true,
    trade_ready: false,
    generated_at: payload.generated_at,
    entries,
  };
}

function findCatalogEntry(catalog: DerivedMetricCatalog, run: GovernedRunSummary): DerivedMetricCatalogEntry | null {
  const matches = catalog.entries.filter((entry) => entry.model_version_id === run.modelVersionId
    && entry.run_id === run.runId
    && entry.manifest_sha256 === run.manifestSha256);
  if (matches.length > 1) {
    fail('catalog_invalid', `Derived metric catalog has multiple entries for ${run.key}.`);
  }
  return matches[0] ?? null;
}

function parseWindow(window: unknown): DerivedExcessWindow {
  if (!isRecord(window) || Object.keys(window).length === 0) {
    fail('window_invalid', 'Derived metric window is missing.');
  }
  const declaredStart = window.declared_start;
  const observedStart = window.observed_start;
  const observedEnd = window.observed_end;
  for (const [field, value] of [
    ['declared_start', declaredStart],
    ['observed_start', observedStart],
    ['observed_end', observedEnd],
  ] as const) {
    if (!isValidIsoDate(value)) {
      fail('window_invalid', `Derived metric window.${field} must be an ISO date.`);
    }
  }
  const declaredEnd = window.declared_end === undefined ? null : window.declared_end;
  const evidenceCutoff = window.evidence_cutoff === undefined ? null : window.evidence_cutoff;
  for (const [field, value] of [
    ['declared_end', declaredEnd],
    ['evidence_cutoff', evidenceCutoff],
  ] as const) {
    if (value !== null && !isValidIsoDate(value)) {
      fail('window_invalid', `Derived metric window.${field} must be an ISO date when declared.`);
    }
  }
  const declaredStartDate = declaredStart as string;
  const observedStartDate = observedStart as string;
  const observedEndDate = observedEnd as string;
  if (observedStartDate > observedEndDate) {
    fail('window_invalid', 'Derived metric observed window is inverted.');
  }
  if (typeof declaredEnd === 'string' && declaredStartDate > declaredEnd) {
    fail('window_invalid', 'Derived metric declared window is inverted.');
  }
  const observationCount = window.observation_count;
  if (typeof observationCount !== 'number' || !Number.isInteger(observationCount) || observationCount <= 0) {
    fail('window_invalid', 'Derived metric observation_count must be a positive integer.');
  }
  return {
    declared_start: declaredStartDate,
    declared_end: typeof declaredEnd === 'string' ? declaredEnd : null,
    observed_start: observedStartDate,
    observed_end: observedEndDate,
    evidence_cutoff: typeof evidenceCutoff === 'string' ? evidenceCutoff : null,
    observation_count: observationCount,
  };
}

/** Pure artifact validation/binding against the catalog entry and run manifest. */
function parseDerivedExcessArtifact(
  payload: unknown,
  entry: DerivedMetricCatalogEntry,
  run: GovernedRunSummary,
): DerivedExcess {
  if (!isRecord(payload)) fail('artifact_invalid', `Derived metric artifact must be an object: ${run.key}`);
  const leakage = findPrivateField(payload);
  if (leakage) fail('private_field', `Derived metric artifact contains a private field (${leakage}): ${run.key}`);
  if (payload.schema_version !== DERIVED_EXCESS_SCHEMA_VERSION) {
    fail('schema_mismatch', `Derived metric artifact schema is invalid: ${run.key}`);
  }
  if (payload.evidence_type !== DERIVED_EXCESS_EVIDENCE_TYPE) {
    fail('schema_mismatch', `Derived metric artifact evidence_type is invalid: ${run.key}`);
  }
  const boundaries = payload.boundaries;
  if (!isRecord(boundaries)
      || boundaries.research_only !== true
      || boundaries.trade_ready !== false
      || boundaries.descriptive_historical_metric !== true
      || boundaries.live_signal !== false) {
    fail('boundary_mismatch', `Derived metric artifact research boundary is invalid: ${run.key}`);
  }
  if (!isRecord(payload.strategy)) {
    fail('identity_mismatch', `Derived metric artifact strategy identity is missing: ${run.key}`);
  }
  const strategy = payload.strategy;
  if (strategy.model_family_id !== run.modelFamilyId
      || strategy.model_version_id !== run.modelVersionId
      || strategy.run_id !== run.runId
      || strategy.manifest_sha256 !== run.manifestSha256
      || strategy.manifest_sha256 !== entry.manifest_sha256
      || strategy.model_version_id !== entry.model_version_id
      || strategy.run_id !== entry.run_id) {
    fail('identity_mismatch', `Derived metric artifact identity does not match the governed run: ${run.key}`);
  }
  if (payload.derivation_id !== entry.derivation_id) {
    fail('identity_mismatch', `Derived metric artifact derivation_id does not match its catalog entry: ${run.key}`);
  }
  if (!isRecord(payload.method) || payload.method.method_id !== 'compounded_relative_excess') {
    fail('schema_mismatch', `Derived metric artifact method is invalid: ${run.key}`);
  }
  if (!run.manifest) {
    fail('performance_unavailable', `Derived metric artifact requires a Bundle v2-backed run: ${run.key}`);
  }
  const performanceSection = run.manifest.sections.find((section) => section.section_id === 'performance');
  if (!performanceSection || performanceSection.availability_status !== 'available' || !performanceSection.sha256) {
    fail('performance_unavailable', `Derived metric artifact requires an available formal performance section: ${run.key}`);
  }
  const inputs = Array.isArray(payload.inputs) ? payload.inputs : [];
  const performanceInputs = inputs.filter(
    (input): input is Record<string, unknown> => isRecord(input) && input.role === 'formal_performance',
  );
  if (performanceInputs.length !== 1) {
    fail('performance_sha_mismatch', `Derived metric artifact requires exactly one formal_performance input: ${run.key}`);
  }
  const performanceInput = performanceInputs[0];
  if (performanceInput.manifest_section !== 'performance'
      || performanceInput.sha256 !== performanceSection.sha256) {
    fail('performance_sha_mismatch', `Derived metric performance input SHA does not match the run manifest: ${run.key}`);
  }
  if (!isRecord(payload.result)) {
    fail('result_invalid', `Derived metric artifact result is missing: ${run.key}`);
  }
  const result = payload.result;
  const strategyReturn = result.strategy_cumulative_return;
  const benchmarkReturn = result.benchmark_cumulative_return;
  const excessReturn = result.excess_return;
  if (typeof strategyReturn !== 'number' || !Number.isFinite(strategyReturn)
      || typeof benchmarkReturn !== 'number' || !Number.isFinite(benchmarkReturn)
      || typeof excessReturn !== 'number' || !Number.isFinite(excessReturn)) {
    fail('result_invalid', `Derived metric artifact result must be finite: ${run.key}`);
  }
  if (strategyReturn <= -1 || benchmarkReturn <= -1) {
    fail('result_invalid', `Derived metric artifact cumulative returns must exceed -1: ${run.key}`);
  }
  const recomputed = (1 + strategyReturn) / (1 + benchmarkReturn) - 1;
  if (!Number.isFinite(recomputed) || Math.abs(recomputed - excessReturn) > DERIVED_EXCESS_TOLERANCE) {
    fail('reconciliation_mismatch', `Derived metric compounded excess does not reconcile: ${run.key}`);
  }
  const window = parseWindow(payload.window);
  const benchmark = payload.benchmark;
  if (!isRecord(benchmark)
      || typeof benchmark.declared_identity !== 'string'
      || !benchmark.declared_identity.trim()) {
    fail('identity_mismatch', `Derived metric benchmark identity is missing: ${run.key}`);
  }
  const declaredIdentity = benchmark.declared_identity;
  return {
    key: `${run.key}:derived_excess`,
    derivationId: entry.derivation_id,
    schemaVersion: DERIVED_EXCESS_SCHEMA_VERSION,
    evidenceType: DERIVED_EXCESS_EVIDENCE_TYPE,
    boundaries: {
      research_only: true,
      trade_ready: false,
      descriptive_historical_metric: true,
      live_signal: false,
    },
    modelFamilyId: run.modelFamilyId,
    modelVersionId: run.modelVersionId,
    runId: run.runId,
    manifestSha256: run.manifestSha256 ?? entry.manifest_sha256,
    methodId: 'compounded_relative_excess',
    result: {
      strategy_cumulative_return: strategyReturn,
      benchmark_cumulative_return: benchmarkReturn,
      excess_return: excessReturn,
    },
    window,
    benchmark: {
      comparability_id: typeof benchmark.comparability_id === 'string' ? benchmark.comparability_id : '',
      declared_identity: declaredIdentity,
      series_semantics: typeof benchmark.series_semantics === 'string' ? benchmark.series_semantics : null,
    },
    label: `Derived · vs ${declaredIdentity} · ${window.declared_start} → ${window.observed_end} · ${window.observation_count} observations`,
  };
}

async function readCatalog(): Promise<DerivedMetricCatalog | null> {
  let response: Response;
  try {
    response = await fetch(`${dataRoot()}derived-metrics/catalog.json`, { cache: 'no-cache' });
  } catch (error) {
    fail('catalog_unavailable', `Derived metric catalog request failed (${error instanceof Error ? error.message : String(error)}).`);
  }
  if (response.status === 404) return null;
  if (!response.ok) {
    fail('catalog_unavailable', `Derived metric catalog request failed (${response.status}).`);
  }
  let payload: unknown;
  try {
    payload = JSON.parse(await response.text()) as unknown;
  } catch {
    fail('catalog_invalid', 'Derived metric catalog is not valid JSON.');
  }
  return parseCatalog(payload);
}

async function readArtifact(entry: DerivedMetricCatalogEntry, run: GovernedRunSummary): Promise<DerivedExcess> {
  let response: Response;
  try {
    response = await fetch(`${dataRoot()}${entry.path}`, { cache: 'no-cache' });
  } catch (error) {
    fail('artifact_unavailable', `Derived metric artifact request failed (${error instanceof Error ? error.message : String(error)}): ${run.key}`);
  }
  if (!response.ok) {
    fail('artifact_unavailable', `Derived metric artifact request failed (${response.status}): ${run.key}`);
  }
  const text = await response.text();
  if ((await sha256Text(text)) !== entry.sha256
      || new TextEncoder().encode(text).byteLength !== entry.byte_size) {
    fail('artifact_hash_mismatch', `Derived metric artifact digest changed after catalog publication: ${run.key}`);
  }
  let payload: unknown;
  try {
    payload = JSON.parse(text) as unknown;
  } catch {
    fail('artifact_invalid', `Derived metric artifact is not valid JSON: ${run.key}`);
  }
  return parseDerivedExcessArtifact(payload, entry, run);
}

// One verified read per governed run identity. Catalog publication is stable
// for the lifetime of a page load, so repeated consumers share one fetch pair.
const reads = new Map<string, Promise<DerivedExcess | null>>();

function readIdentity(run: GovernedRunSummary): string {
  const performance = run.manifest?.sections.find((section) => section.section_id === 'performance');
  return JSON.stringify([
    run.key,
    run.modelVersionId,
    run.runId,
    run.manifestSha256,
    run.manifestPath,
    run.bundleId,
    performance?.sha256 ?? null,
  ]);
}

/**
 * Load the published derived excess for one formal run. Returns null when the
 * catalog declares no derivation for the run; malformed or mismatched
 * published data throws a `DerivedExcessError` instead of falling back to a
 * number recomputed from the run's performance rows.
 */
export async function loadDerivedExcess(run: GovernedRunSummary): Promise<DerivedExcess | null> {
  const identity = readIdentity(run);
  const cached = reads.get(identity);
  if (cached) return cached;
  const read = (async (): Promise<DerivedExcess | null> => {
    const catalog = await readCatalog();
    if (!catalog) return null;
    const entry = findCatalogEntry(catalog, run);
    if (!entry) return null;
    return readArtifact(entry, run);
  })();
  reads.set(identity, read);
  try {
    return await read;
  } catch (error) {
    // Retry the same identity instead of replaying a cached rejection.
    if (reads.get(identity) === read) reads.delete(identity);
    throw error;
  }
}
