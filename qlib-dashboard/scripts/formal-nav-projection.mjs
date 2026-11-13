// Disposable public NAV projection for formal Bundle v2 runs.
//
// The browser already owns every NAV/return transform (navFromReport,
// horizonCoverage, strategyPeriodSummary, discoverBenchmarkOptions). This
// module therefore copies raw frozen performance fields only; it never
// computes, rounds or fills a return. The row whitelist is the public
// boundary: weight, trade, position and decision fields cannot pass it.

export const FORMAL_NAV_PROJECTION_SCHEMA = 'formal_nav_projection_v1';
export const FORMAL_NAV_VIEW = 'nav_series_v1';

const ROW_FIELDS = new Set([
  'date',
  'holding_end_date',
  'account',
  'account_before',
  'provisional_mtm',
  'settlement_status',
]);

// `benchmark_return` is a per-row return, not a retained benchmark wealth
// observation; keep it out so the client alone derives returns.
const EXCLUDED_BENCHMARK_FIELD = 'benchmark_return';

const PRIVATE_KEY_PREFIX = 'weight_';
const PRIVATE_KEY_SUFFIX = '_weight';
const PRIVATE_KEYS = new Set([
  'operating_state',
  'current_weights',
  'target_weights',
  'weights',
  'trades',
  'decision_reason',
  'decision_state',
  'executed_reason',
  'position_state',
  'position_label',
]);

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isBenchmarkField(key) {
  return key !== EXCLUDED_BENCHMARK_FIELD && (key === 'bench' || key.startsWith('bench_'));
}

function isPrivateKey(key) {
  return PRIVATE_KEYS.has(key) || key.startsWith(PRIVATE_KEY_PREFIX) || key.endsWith(PRIVATE_KEY_SUFFIX);
}

function projectRow(row, index) {
  if (!isRecord(row)) {
    throw new Error(`Formal NAV projection row ${index} is not an object.`);
  }
  // Preserve the sealed report's key order; only the whitelist survives.
  const projected = {};
  for (const key of Object.keys(row)) {
    if (ROW_FIELDS.has(key) || isBenchmarkField(key)) projected[key] = row[key];
  }
  return projected;
}

function assertNoPrivateFields(value, path = 'projection') {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => assertNoPrivateFields(entry, `${path}[${index}]`));
    return;
  }
  if (!isRecord(value)) return;
  for (const [key, entry] of Object.entries(value)) {
    if (isPrivateKey(key)) {
      throw new Error(`Formal NAV projection refused private field ${path}.${key}.`);
    }
    assertNoPrivateFields(entry, `${path}.${key}`);
  }
}

/**
 * Build the deterministic, disposable NAV projection for one accepted run.
 *
 * The caller passes the already digest/size-verified sealed performance
 * payload, the final published manifest, and the public catalog record. The
 * performance section declaration is copied from that manifest so the browser
 * can bind `performance.sha256`/`byte_size` to the manifest it verified.
 */
export function buildFormalNavProjection({ performance, manifest, record, evidenceCutoff }) {
  if (!isRecord(performance) || !Array.isArray(performance.report) || performance.report.length === 0) {
    throw new Error('Formal NAV projection requires a non-empty performance report array.');
  }
  if (!isRecord(manifest) || !Array.isArray(manifest.sections)) {
    throw new Error('Formal NAV projection requires a verified Bundle v2 manifest.');
  }
  const section = manifest.sections.find((candidate) => candidate?.section_id === 'performance');
  if (!section || section.availability_status !== 'available'
      || typeof section.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(section.sha256)
      || !Number.isInteger(section.byte_size) || section.byte_size < 0) {
    throw new Error('Formal NAV projection requires an available performance section declaration.');
  }
  if (!isRecord(record)) {
    throw new Error('Formal NAV projection requires a formal catalog record.');
  }
  const identity = {
    model_family_id: String(record.model_family_id ?? ''),
    model_version_id: String(record.model_version_id ?? ''),
    run_id: String(record.run_id ?? ''),
    bundle_id: String(record.bundle_id ?? ''),
    manifest_sha256: String(record.manifest_sha256 ?? ''),
  };
  if (Object.values(identity).some((value) => value === '')) {
    throw new Error('Formal NAV projection requires a complete formal run identity.');
  }
  const cutoff = String(evidenceCutoff ?? manifest.evidence_cutoff ?? '');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(cutoff)) {
    throw new Error('Formal NAV projection requires a valid evidence cutoff.');
  }

  // Fixed insertion order plus JSON.stringify(value) + "\n" yields stable
  // bytes for the same sealed inputs. Rows keep their sealed key order.
  const projection = {
    schema_version: FORMAL_NAV_PROJECTION_SCHEMA,
    view: FORMAL_NAV_VIEW,
    research_only: true,
    trade_ready: false,
    ...identity,
    evidence_cutoff: cutoff,
    benchmark: performance.benchmark ?? null,
    trace_frequency: performance.trace_frequency ?? null,
    date_range: performance.date_range ?? null,
    performance: {
      section_id: 'performance',
      sha256: section.sha256,
      byte_size: section.byte_size,
    },
    rows: performance.report.map(projectRow),
  };
  assertNoPrivateFields(projection);
  return projection;
}
