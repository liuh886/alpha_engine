import { effectivePerformanceDate } from './performanceBenchmarks';
import { isPerformanceDate } from './performancePeriods';
import type { ReportRow } from './types';
import {
  fetchFormalAssetText,
  formalRunAssetPath,
  type GovernedRunSummary,
} from './governed-run';

/**
 * Why a formal NAV series is unavailable. Every failure is explicit so Today
 * and strategy cards can show a blocker instead of silently falling back to
 * the full performance section.
 */
export type FormalNavUnavailableReason =
  | 'missing_bundle'
  | 'performance_section_unavailable'
  | 'invalid_payload'
  | 'schema_mismatch'
  | 'boundary_mismatch'
  | 'identity_mismatch'
  | 'section_mismatch'
  | 'rows_invalid'
  | 'fetch_failed'
  | 'parse_failed';

export class FormalNavUnavailableError extends Error {
  readonly reason: FormalNavUnavailableReason;

  constructor(reason: FormalNavUnavailableReason, message: string) {
    super(message);
    this.name = 'FormalNavUnavailableError';
    this.reason = reason;
  }
}

export interface FormalNavPerformanceSection {
  section_id: 'performance';
  sha256: string;
  byte_size: number;
}

/** The disposable `nav.json` payload generated beside each public run. */
export interface FormalNavProjection {
  schema_version: 'formal_nav_projection_v1';
  view: 'nav_series_v1';
  research_only: true;
  trade_ready: false;
  model_family_id: string;
  model_version_id: string;
  run_id: string;
  bundle_id: string;
  manifest_sha256: string;
  evidence_cutoff: string;
  benchmark: string | null;
  trace_frequency: string | null;
  date_range: Record<string, unknown> | null;
  performance: FormalNavPerformanceSection;
  rows: ReportRow[];
}

/** A parsed NAV projection bound to the governed run that was verified. */
export interface FormalNavSeries extends FormalNavProjection {
  key: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function fail(reason: FormalNavUnavailableReason, message: string): never {
  throw new FormalNavUnavailableError(reason, message);
}

function textOrNull(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function parseRows(payload: unknown, run: GovernedRunSummary): ReportRow[] {
  const rows = payload;
  if (!Array.isArray(rows) || rows.length === 0) {
    fail('rows_invalid', `Formal NAV projection has no report rows: ${run.key}`);
  }
  return rows.map((row, index) => {
    if (!isRecord(row)) {
      fail('rows_invalid', `Formal NAV projection row ${index} is not an object: ${run.key}`);
    }
    const date = effectivePerformanceDate(row as ReportRow);
    const account = row.account;
    if (!isPerformanceDate(date) || typeof account !== 'number'
        || !Number.isFinite(account) || account <= 0) {
      fail('rows_invalid', `Formal NAV projection row ${index} has no valid performance date/account: ${run.key}`);
    }
    return row as ReportRow;
  });
}

/**
 * Pure validation/binding of one `nav.json` payload to its verified manifest.
 * Returns rows typed as the existing `ReportRow` so navFromReport,
 * horizonCoverage, strategyPeriodSummary and discoverBenchmarkOptions apply
 * unchanged. All return math stays in those existing browser helpers.
 */
export function parseFormalNavProjection(
  payload: unknown,
  run: GovernedRunSummary,
): FormalNavProjection {
  if (!isRecord(payload)) {
    fail('invalid_payload', `Formal NAV projection is not an object: ${run.key}`);
  }
  if (payload.schema_version !== 'formal_nav_projection_v1' || payload.view !== 'nav_series_v1') {
    fail('schema_mismatch', `Formal NAV projection schema/view is invalid: ${run.key}`);
  }
  if (payload.research_only !== true || payload.trade_ready !== false) {
    fail('boundary_mismatch', `Formal NAV projection research boundary is invalid: ${run.key}`);
  }
  if (!run.manifest || !run.manifestPath || !run.manifestSha256 || !run.bundleId) {
    fail('missing_bundle', `Formal NAV projection requires a Bundle v2-backed run: ${run.key}`);
  }
  if (payload.model_family_id !== run.modelFamilyId
      || payload.model_version_id !== run.modelVersionId
      || payload.run_id !== run.runId
      || payload.bundle_id !== run.bundleId
      || payload.manifest_sha256 !== run.manifestSha256) {
    fail('identity_mismatch', `Formal NAV projection run identity mismatch: ${run.key}`);
  }
  const section = run.manifest.sections.find((candidate) => candidate.section_id === 'performance');
  if (!section || section.availability_status !== 'available' || !section.sha256 || section.byte_size === null) {
    fail('performance_section_unavailable', `Formal performance section is unavailable: ${run.key}`);
  }
  const performance = payload.performance;
  if (!isRecord(performance)
      || performance.section_id !== 'performance'
      || performance.sha256 !== section.sha256
      || performance.byte_size !== section.byte_size) {
    fail('section_mismatch', `Formal NAV projection performance section mismatch: ${run.key}`);
  }
  const rows = parseRows(payload.rows, run);
  return {
    schema_version: 'formal_nav_projection_v1',
    view: 'nav_series_v1',
    research_only: true,
    trade_ready: false,
    model_family_id: run.modelFamilyId,
    model_version_id: run.modelVersionId,
    run_id: run.runId,
    bundle_id: run.bundleId,
    manifest_sha256: run.manifestSha256,
    evidence_cutoff: typeof payload.evidence_cutoff === 'string' ? payload.evidence_cutoff : run.evidenceCutoff,
    benchmark: textOrNull(payload.benchmark),
    trace_frequency: textOrNull(payload.trace_frequency),
    date_range: isRecord(payload.date_range) ? payload.date_range : null,
    performance: {
      section_id: 'performance',
      sha256: section.sha256,
      byte_size: section.byte_size,
    },
    rows,
  };
}

interface NavRead {
  identity: string;
  read: Promise<FormalNavSeries>;
}

// Keep one verified NAV read per run object, mirroring governed-run section
// reuse. A changed manifest/section identity must fetch again.
const navReads = new WeakMap<GovernedRunSummary, NavRead>();

/**
 * Load the compact NAV projection for one accepted formal run. Fails closed
 * when `nav.json` is absent; never downloads the full performance section.
 */
export async function loadFormalNav(run: GovernedRunSummary): Promise<FormalNavSeries> {
  if (!run.manifest || !run.manifestPath || !run.manifestSha256 || run.channel !== 'formal') {
    fail('missing_bundle', `Formal NAV projection requires a Bundle v2-backed run: ${run.key}`);
  }
  const section = run.manifest.sections.find((candidate) => candidate.section_id === 'performance');
  if (!section || section.availability_status !== 'available' || !section.sha256 || section.byte_size === null) {
    fail('performance_section_unavailable', `Formal performance section is unavailable: ${run.key}`);
  }
  const path = formalRunAssetPath(run.manifestPath, 'nav.json');
  const identity = JSON.stringify([
    run.key, run.bundleId, run.manifestSha256, run.manifestPath, run.evidenceCutoff,
    path, section.sha256, section.byte_size,
  ]);
  const cached = navReads.get(run);
  if (cached?.identity === identity) return cached.read;

  const read = (async (): Promise<FormalNavSeries> => {
    let text: string;
    try {
      text = await fetchFormalAssetText(path);
    } catch (error) {
      fail(
        'fetch_failed',
        `Formal NAV projection is unavailable (${error instanceof Error ? error.message : String(error)}): ${run.key}`,
      );
    }
    let payload: unknown;
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      fail('parse_failed', `Formal NAV projection is not valid JSON: ${run.key}`);
    }
    return { ...parseFormalNavProjection(payload, run), key: run.key };
  })();
  const entry: NavRead = { identity, read };
  navReads.set(run, entry);
  try {
    return await read;
  } catch (error) {
    // Retry the same identity instead of replaying a cached rejection.
    if (navReads.get(run) === entry) navReads.delete(run);
    throw error;
  }
}
