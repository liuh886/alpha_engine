import { describe, expect, it } from 'vitest';
import { projectPerformanceContext } from './formal-performance-context.mjs';
import { readPerformanceSourceContext } from '../src/lib/performanceSourceContext.ts';

function fixture() {
  const performance = {
    research_only: true, trade_ready: false, benchmark: 'QQQ', trace_frequency: 'non_overlapping_10_session',
    performance_semantics: { performance_date_field: 'holding_end_date' },
    report: [
      { date: '2026-01-02', holding_end_date: '2026-01-16', account: .9, period_return: -.1, bench_qqq: 1.05, benchmark_return: .05 },
      { date: '2026-01-16', holding_end_date: '2026-01-30', account: 1.1, period_return: 1.1 / .9 - 1, bench_qqq: .945, benchmark_return: -.1 },
      { date: '2026-02-02', holding_end_date: '2026-02-02', account: 1.2, account_before: 1.1, period_return: 1.2 / 1.1 - 1,
        bench_qqq: .99, bench_qqq_before: .945, benchmark_return: .99 / .945 - 1, provisional_mtm: true },
    ],
  };
  const summary = { metrics: [{ metric_id: 'total_return', value: .1, sample_count: 2, scope: 'settled_source', availability_status: 'available' }] };
  const source = { canonical_bundle_id: 'a'.repeat(64), canonical_manifest_sha256: 'b'.repeat(64),
    performance_sha256: 'c'.repeat(64), summary_sha256: 'd'.repeat(64), evidence_cutoff: '2026-02-02' };
  return { performance, summary, source };
}

describe('source-bound formal wealth context', () => {
  it('retains first-period loss, source metrics and every raw economic value without mutating canonical input', () => {
    const { performance, summary, source } = fixture();
    const original = structuredClone(performance);
    const result = projectPerformanceContext(performance, summary, source);
    expect(performance).toEqual(original);
    expect(result.report[0]).toMatchObject({ account: .9, account_before: 1, bench_qqq_before: 1 });
    for (let i = 0; i < original.report.length; i++) expect(result.report[i]).toMatchObject(original.report[i]);
    expect(result.public_evidence_context).toMatchObject({
      canonical_bundle_id: source.canonical_bundle_id, source_performance_sha256: source.performance_sha256,
      opening_date: '2026-01-02', first_observation_date: '2026-01-16', last_observation_date: '2026-02-02',
      wealth_observation_count: 3, non_provisional_count: 2, provisional_count: 1,
      total_return_window: { start: '2026-01-02', end: '2026-01-30', sample_count: 2, includes_provisional: false },
    });
    expect(result.report.at(-1).account / result.report[0].account_before - 1).toBeCloseTo(.2);
    expect(summary.metrics[0].value).toBe(.1);
  });

  it.each(['account', 'benchmark', 'count', 'metric', 'date', 'missing_return', 'unsettled_gap', 'bad_opening', 'overlap'])(
    'blocks inconsistent retained %s evidence', (change) => {
      const { performance, summary, source } = fixture();
      if (change === 'account') performance.report[1].account = 1.4;
      if (change === 'benchmark') performance.report[1].bench_qqq = 2;
      if (change === 'count') summary.metrics[0].sample_count = 7;
      if (change === 'metric') summary.metrics[0].value = .3;
      if (change === 'date') performance.report[1].holding_end_date = '2026-02-30';
      if (change === 'missing_return') delete performance.report[0].period_return;
      if (change === 'unsettled_gap') performance.report[0].provisional_mtm = true;
      if (change === 'bad_opening') performance.report[0].account_before = 9;
      if (change === 'overlap') performance.report[1].date = '2026-01-09';
      expect(() => projectPerformanceContext(performance, summary, source)).toThrow('publication blocked');
    },
  );

  it('does not infer an opening boundary for a different return contract', () => {
    const { performance, summary, source } = fixture();
    performance.trace_frequency = 'daily';
    expect(projectPerformanceContext(performance, summary, source)).toBeNull();
  });

  it.each(['valid', 'bundle', 'cutoff', 'count', 'opening', 'window', 'projection', 'missing', 'summary_hash', 'metric_value'])(
    'both view consumers verify source context: %s', (change) => {
      const { performance, summary, source } = fixture();
      const payload = projectPerformanceContext(performance, summary, source);
      const context = payload.public_evidence_context;
      const manifest = { projection_contract: 'public_historical_projection_v1', source_identity: source,
        comparability_key: { trace_frequency: 'non_overlapping_10_session', benchmark_id: 'QQQ' } };
      const canonical = { bundle_id: source.canonical_bundle_id, sections: [
        { section_id: 'summary', sha256: source.summary_sha256 }, { section_id: 'performance', sha256: source.performance_sha256 },
      ] };
      if (change === 'bundle') context.canonical_bundle_id = 'e'.repeat(64);
      if (change === 'cutoff') context.evidence_cutoff = '2026-02-03';
      if (change === 'count') context.wealth_observation_count = 999;
      if (change === 'opening') context.opening_account = 9;
      if (change === 'window') context.total_return_window.end = '2026-02-02';
      if (change === 'projection') delete manifest.projection_contract;
      if (change === 'summary_hash') context.source_summary_sha256 = 'e'.repeat(64);
      if (change === 'metric_value') summary.metrics[0].value = .8;
      const read = () => readPerformanceSourceContext(change === 'missing' ? undefined : context,
        payload.report, manifest, source.evidence_cutoff, summary, canonical);
      if (change === 'valid') expect(read()).toEqual(context);
      else expect(read).toThrow('could not be verified');
    },
  );
});
