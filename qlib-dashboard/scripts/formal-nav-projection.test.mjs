import { describe, expect, it } from 'vitest';
import {
  buildFormalNavProjection,
  FORMAL_NAV_PROJECTION_SCHEMA,
  FORMAL_NAV_VIEW,
} from './formal-nav-projection.mjs';

const PERFORMANCE_SHA = 'a'.repeat(64);
const MANIFEST_SHA = 'b'.repeat(64);
const BUNDLE_ID = 'c'.repeat(64);

function manifestFixture(overrides = {}) {
  return {
    bundle_id: BUNDLE_ID,
    evidence_cutoff: '2026-11-11',
    model_family_id: 'us_ranker',
    model_version_id: 'us_x1_3',
    run_id: 'us_x1_3-through-2026_11_11',
    sections: [
      {
        section_id: 'performance',
        availability_status: 'available',
        required_for_model_kind: true,
        reason: null,
        path: 'performance.json',
        sha256: PERFORMANCE_SHA,
        byte_size: 4321,
        media_type: 'application/json',
      },
    ],
    ...overrides,
  };
}

function recordFixture(overrides = {}) {
  return {
    model_family_id: 'us_ranker',
    model_version_id: 'us_x1_3',
    run_id: 'us_x1_3-through-2026_11_11',
    bundle_id: BUNDLE_ID,
    manifest_sha256: MANIFEST_SHA,
    ...overrides,
  };
}

function performanceFixture(overrides = {}) {
  return {
    benchmark: 'QQQ',
    trace_frequency: 'non_overlapping_10_session',
    date_range: { start: '2024-01-02', end: '2026-11-11' },
    report: [
      {
        date: '2024-01-02',
        holding_end_date: '2024-01-17',
        account: 0.9275820066928864,
        bench_qqq: 1.011475682258606,
        bench_qqq_before: 0.9999999999999999,
        benchmark_return: 0.011475682258605957,
        period_return: -0.07241799330711365,
        turnover: 0.5,
        weight_QQQ: 0.42,
        base_BYD_weight: 0.75,
        drawdown: -0.0724,
        operating_state: 'private',
        current_weights: { QQQ: 0.42 },
        target_weights: { QQQ: 0.5 },
        trades: [{ action: 'BUY' }],
        decision_reason: 'hold',
      },
      {
        date: '2026-11-11',
        holding_end_date: '2026-11-11',
        account: 5.843560652484866,
        account_before: 5.47869548925914,
        bench_qqq: 1.7047526712323855,
        bench_qqq_before: 1.6201051277049747,
        benchmark_return: 0.05224817950383365,
        provisional_mtm: true,
        settlement_status: 'provisional_mtm',
        weight_QQQ: 0.5,
      },
    ],
    ...overrides,
  };
}

function build(overrides = {}) {
  return buildFormalNavProjection({
    performance: performanceFixture(),
    manifest: manifestFixture(),
    record: recordFixture(),
    evidenceCutoff: '2026-11-11',
    ...overrides,
  });
}

describe('buildFormalNavProjection', () => {
  it('declares the disposable NAV view and copies verified bindings', () => {
    const projection = build();
    expect(projection).toMatchObject({
      schema_version: FORMAL_NAV_PROJECTION_SCHEMA,
      view: FORMAL_NAV_VIEW,
      research_only: true,
      trade_ready: false,
      model_family_id: 'us_ranker',
      model_version_id: 'us_x1_3',
      run_id: 'us_x1_3-through-2026_11_11',
      bundle_id: BUNDLE_ID,
      manifest_sha256: MANIFEST_SHA,
      evidence_cutoff: '2026-11-11',
      benchmark: 'QQQ',
      trace_frequency: 'non_overlapping_10_session',
      date_range: { start: '2024-01-02', end: '2026-11-11' },
      performance: { section_id: 'performance', sha256: PERFORMANCE_SHA, byte_size: 4321 },
    });
    expect(projection.rows).toHaveLength(2);
  });

  it('keeps only whitelisted row fields in original order', () => {
    const projection = build();
    expect(projection.rows[0]).toEqual({
      date: '2024-01-02',
      holding_end_date: '2024-01-17',
      account: 0.9275820066928864,
      bench_qqq: 1.011475682258606,
      bench_qqq_before: 0.9999999999999999,
    });
    expect(projection.rows[1]).toEqual({
      date: '2026-11-11',
      holding_end_date: '2026-11-11',
      account: 5.843560652484866,
      account_before: 5.47869548925914,
      bench_qqq: 1.7047526712323855,
      bench_qqq_before: 1.6201051277049747,
      provisional_mtm: true,
      settlement_status: 'provisional_mtm',
    });
  });

  it('preserves every bench/bench_ field except benchmark_return', () => {
    const projection = build({
      performance: performanceFixture({
        report: [{
          date: '2024-02-01',
          account: 1.25,
          bench: -0.014633575275012078,
          bench_qqq: 0.9853664247249879,
          bench_byd_v1_2: 6.480284052620928,
          benchmark_return: 0.11,
          benchmark_account: 1.2,
        }],
      }),
    });
    expect(projection.rows[0]).toEqual({
      date: '2024-02-01',
      account: 1.25,
      bench: -0.014633575275012078,
      bench_qqq: 0.9853664247249879,
      bench_byd_v1_2: 6.480284052620928,
    });
  });

  it('copies numeric values verbatim without rounding or derivation', () => {
    const projection = build();
    expect(projection.rows[0].account).toBe(0.9275820066928864);
    expect(projection.rows[1].account).toBe(5.843560652484866);
    expect(Object.keys(projection.rows[0])).not.toContain('period_return');
    expect(Object.keys(projection.rows[0])).not.toContain('drawdown');
  });

  it('matches the projected opening row and final published section binding', () => {
    const projectedSha = 'd'.repeat(64);
    const manifest = manifestFixture();
    manifest.sections[0].sha256 = projectedSha;
    manifest.sections[0].byte_size = 6543;
    // projectPerformanceContext publishes validated opening values on row 0.
    const published = performanceFixture();
    published.report[0].account_before = 0.9312300000000001;
    published.report[0].bench_qqq_before = 1.02;
    published.public_evidence_context = { opening_basis: 'validated_retained_net_wealth_compounding' };

    const projection = build({ performance: published, manifest });

    expect(projection.rows).toHaveLength(published.report.length);
    expect(projection.rows[0]).toMatchObject({
      date: '2024-01-02',
      account: 0.9275820066928864,
      account_before: 0.9312300000000001,
      bench_qqq_before: 1.02,
    });
    expect(projection.rows[0]).not.toHaveProperty('public_evidence_context');
    expect(projection).not.toHaveProperty('public_evidence_context');
    expect(projection.performance).toEqual({
      section_id: 'performance',
      sha256: projectedSha,
      byte_size: 6543,
    });
  });

  it('serializes deterministically for the same sealed input', () => {
    const first = `${JSON.stringify(build())}\n`;
    const second = `${JSON.stringify(build({
      performance: structuredClone(performanceFixture()),
      manifest: structuredClone(manifestFixture()),
      record: structuredClone(recordFixture()),
    }))}\n`;
    expect(second).toBe(first);
    expect(new TextEncoder().encode(first).byteLength).toBeGreaterThan(0);
  });

  it('never emits operating state, weights, trades or private decisions', () => {
    const text = `${JSON.stringify(build())}\n`;
    for (const forbidden of [
      'operating_state', 'current_weights', 'target_weights', 'weight_', '_weight',
      '"weights"', '"trades"', 'decision_reason', 'decision_state',
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it('rejects a payload without a report array or with non-object rows', () => {
    expect(() => build({ performance: { ...performanceFixture(), report: undefined } }))
      .toThrow(/report array/);
    expect(() => build({ performance: { ...performanceFixture(), report: [] } }))
      .toThrow(/report array/);
    expect(() => build({ performance: { ...performanceFixture(), report: [{ date: '2024-01-02' }, null] } }))
      .toThrow(/row 1 is not an object/);
  });

  it('rejects an unavailable performance declaration or incomplete identity', () => {
    const unavailable = manifestFixture();
    unavailable.sections[0].availability_status = 'not_retained';
    expect(() => build({ manifest: unavailable })).toThrow(/performance section declaration/);
    expect(() => build({ record: recordFixture({ run_id: '' }) })).toThrow(/complete formal run identity/);
    expect(() => build({ evidenceCutoff: 'not-a-date' })).toThrow(/evidence cutoff/);
  });
});
