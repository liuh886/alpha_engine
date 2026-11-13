import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  FormalNavUnavailableError,
  loadFormalNav,
  parseFormalNavProjection,
  type FormalNavProjection,
  type FormalNavUnavailableReason,
} from './formal-nav';
import type { GovernedRunSummary } from './governed-run';
import type { ModelRunBundleV2Manifest } from './model-run-bundle-v2';
import type { ReportRow } from './types';

const PERFORMANCE_SHA = 'a'.repeat(64);
const MANIFEST_SHA = 'b'.repeat(64);
const BUNDLE_ID = 'c'.repeat(64);
const PERFORMANCE_BYTE_SIZE = 4321;

function runFixture(overrides: Partial<GovernedRunSummary> = {}): GovernedRunSummary {
  const manifest: ModelRunBundleV2Manifest = {
    schema_version: '2.0.0',
    model_family_id: 'us_ranker',
    model_version_id: 'us_x1_3',
    run_id: 'us_x1_3-through-2026_11_11',
    bundle_id: BUNDLE_ID,
    model_kind: 'cross_sectional_ranker',
    publication_channel: 'formal',
    publication_status: 'accepted_formal_baseline',
    generated_at: '2026-11-12T00:00:00Z',
    evidence_cutoff: '2026-11-11',
    research_only: true,
    trade_ready: false,
    comparability_key: {
      market: 'us',
      universe_id: 'us_selected_equities_v2',
      benchmark_id: 'qqq',
      start: '2024-01-02',
      end: '2026-11-11',
      trace_frequency: 'non_overlapping_10_session',
      horizon: '10_sessions',
      rebalance_contract_id: 'rebalance_10_sessions',
      cost_contract_id: 'cost_20_bps',
    },
    sections: [{
      section_id: 'performance',
      availability_status: 'available',
      required_for_model_kind: true,
      reason: null,
      path: 'performance.json',
      sha256: PERFORMANCE_SHA,
      byte_size: PERFORMANCE_BYTE_SIZE,
      media_type: 'application/json',
    }],
  };
  return {
    key: 'formal:us_ranker:us_x1_3:us_x1_3-through-2026_11_11',
    modelFamilyId: 'us_ranker',
    modelVersionId: 'us_x1_3',
    runId: 'us_x1_3-through-2026_11_11',
    bundleId: BUNDLE_ID,
    title: 'US x1.3',
    modelKind: 'cross_sectional_ranker',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'us',
    benchmark: 'qqq',
    generatedAt: '2026-11-12T00:00:00Z',
    evidenceCutoff: '2026-11-11',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: 'fixture/manifest.json',
    manifestSha256: MANIFEST_SHA,
    summary: {},
    manifest,
    loadWarnings: [],
    ...overrides,
  };
}

function projectionFixture(run: GovernedRunSummary = runFixture()): FormalNavProjection {
  return {
    schema_version: 'formal_nav_projection_v1',
    view: 'nav_series_v1',
    research_only: true,
    trade_ready: false,
    model_family_id: run.modelFamilyId,
    model_version_id: run.modelVersionId,
    run_id: run.runId,
    bundle_id: run.bundleId as string,
    manifest_sha256: run.manifestSha256 as string,
    evidence_cutoff: run.evidenceCutoff,
    benchmark: 'QQQ',
    trace_frequency: 'non_overlapping_10_session',
    date_range: { start: '2024-01-02', end: '2026-11-11' },
    performance: {
      section_id: 'performance',
      sha256: PERFORMANCE_SHA,
      byte_size: PERFORMANCE_BYTE_SIZE,
    },
    rows: [
      { date: '2024-01-02', holding_end_date: '2024-01-17', account: 100, bench_qqq: 101 },
      { date: '2026-11-11', account: 120.5, provisional_mtm: true, settlement_status: 'provisional_mtm' },
    ],
  };
}

function expectReason(fn: () => unknown, reason: FormalNavUnavailableReason): void {
  try {
    fn();
  } catch (error) {
    expect(error).toBeInstanceOf(FormalNavUnavailableError);
    expect((error as FormalNavUnavailableError).reason).toBe(reason);
    return;
  }
  throw new Error(`Expected FormalNavUnavailableError with reason ${reason}`);
}

afterEach(() => vi.unstubAllGlobals());

describe('parseFormalNavProjection', () => {
  it('accepts a projection bound to the verified run and returns ReportRow[]', () => {
    const run = runFixture();
    const parsed = parseFormalNavProjection(projectionFixture(run), run);
    expect(parsed).toMatchObject({
      schema_version: 'formal_nav_projection_v1',
      view: 'nav_series_v1',
      research_only: true,
      trade_ready: false,
      model_family_id: run.modelFamilyId,
      model_version_id: run.modelVersionId,
      run_id: run.runId,
      bundle_id: run.bundleId,
      manifest_sha256: run.manifestSha256,
      benchmark: 'QQQ',
      performance: { section_id: 'performance', sha256: PERFORMANCE_SHA, byte_size: PERFORMANCE_BYTE_SIZE },
    });
    expect(parsed.rows).toEqual(projectionFixture(run).rows);
  });

  const mismatches: Array<[string, Partial<FormalNavProjection>, FormalNavUnavailableReason]> = [
    ['model version', { model_version_id: 'other_version' }, 'identity_mismatch'],
    ['run', { run_id: 'other-run' }, 'identity_mismatch'],
    ['manifest', { manifest_sha256: 'd'.repeat(64) }, 'identity_mismatch'],
    ['bundle', { bundle_id: 'e'.repeat(64) }, 'identity_mismatch'],
    ['performance sha256', {
      performance: { section_id: 'performance', sha256: 'f'.repeat(64), byte_size: PERFORMANCE_BYTE_SIZE },
    }, 'section_mismatch'],
    ['performance byte_size', {
      performance: { section_id: 'performance', sha256: PERFORMANCE_SHA, byte_size: 1 },
    }, 'section_mismatch'],
  ];

  it.each(mismatches)('rejects a %s mismatch', (_label, overrides, reason) => {
    const run = runFixture();
    expectReason(
      () => parseFormalNavProjection({ ...projectionFixture(run), ...overrides }, run),
      reason,
    );
  });

  it('rejects a changed schema, view or research boundary', () => {
    const run = runFixture();
    expectReason(
      () => parseFormalNavProjection({ ...projectionFixture(run), schema_version: 'other' }, run),
      'schema_mismatch',
    );
    expectReason(
      () => parseFormalNavProjection({ ...projectionFixture(run), view: 'other' }, run),
      'schema_mismatch',
    );
    expectReason(
      () => parseFormalNavProjection({ ...projectionFixture(run), trade_ready: true }, run),
      'boundary_mismatch',
    );
  });

  it('rejects an unavailable performance declaration', () => {
    const run = runFixture();
    run.manifest!.sections[0] = {
      ...run.manifest!.sections[0],
      availability_status: 'not_retained',
      sha256: null,
      byte_size: null,
      media_type: null,
      reason: 'not retained',
    };
    expectReason(
      () => parseFormalNavProjection(projectionFixture(), run),
      'performance_section_unavailable',
    );
  });

  it('rejects empty, non-object and unusable rows', () => {
    const run = runFixture();
    const withRows = (rows: unknown) => ({ ...projectionFixture(run), rows: rows as ReportRow[] });
    expectReason(() => parseFormalNavProjection(withRows([]), run), 'rows_invalid');
    expectReason(() => parseFormalNavProjection(withRows([null]), run), 'rows_invalid');
    expectReason(
      () => parseFormalNavProjection(withRows([{ date: '2026-02-30', account: 1 }]), run),
      'rows_invalid',
    );
    expectReason(
      () => parseFormalNavProjection(withRows([{ date: '2026-01-01', account: 0 }]), run),
      'rows_invalid',
    );
    expectReason(
      () => parseFormalNavProjection(withRows([{ date: '2026-01-01', account: Number.NaN }]), run),
      'rows_invalid',
    );
    expectReason(
      () => parseFormalNavProjection(withRows([{ date: '2026-01-01', account: '100' }]), run),
      'rows_invalid',
    );
  });
});

describe('loadFormalNav', () => {
  it('reads nav.json from the run directory once per run identity', async () => {
    const run = runFixture();
    const text = `${JSON.stringify(projectionFixture(run))}\n`;
    const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => new Response(text, { status: 200 }));
    vi.stubGlobal('fetch', fetcher);

    const [first, second] = await Promise.all([loadFormalNav(run), loadFormalNav(run)]);
    expect(first).toEqual(second);
    expect(first.key).toBe(run.key);
    expect(first.rows).toHaveLength(2);
    expect(await loadFormalNav(run)).toBe(first);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe('/data/formal-model-runs/fixture/nav.json');
    expect(fetcher.mock.calls[0][1]).toEqual({ cache: 'no-cache' });
  });

  it('fails closed when nav.json is absent without reading performance.json', async () => {
    const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => new Response('', { status: 404 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(loadFormalNav(runFixture())).rejects.toMatchObject({
      name: 'FormalNavUnavailableError',
      reason: 'fetch_failed',
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe('/data/formal-model-runs/fixture/nav.json');
  });
});
