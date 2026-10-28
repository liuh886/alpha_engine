/// <reference types="node" />
// Synthetic browser/reader contract fixture, never copied to public or dist.
import { createHash } from 'node:crypto';
import firstSeasonSnapshot from './racetrack-v2.json' with { type: 'json' };

export function racetrackFirstSeasonFixture() {
  return structuredClone(firstSeasonSnapshot) as {
    manifest: Record<string, any>; scoreboard: Record<string, any>; files: Record<string, string>;
  };
}

export function racetrackFixture(market: 'us' | 'cn' = 'us', count = 11) {
  const release = createHash('sha256').update(`synthetic-race-${market}-${count}`).digest('hex');
  const pool = market === 'us' ? 'us_selected_equities_v2' : 'cn_selected_equities_v3';
  const benchmark = market === 'us' ? 'QQQ' : '000300';
  const dates = ['2026-07-01', '2026-07-31', '2026-08-03', '2026-08-31', '2026-09-01', '2026-09-30', '2026-10-09', '2026-10-26'];
  const entries = Array.from({ length: count }, (_, i) => ({
    runner_id: `fixture_${market}_${(i + 1).toString().padStart(2, '0')}`, runner_version: '1.0',
    thesis_summary: 'Synthetic contract fixture; this is not measured investment evidence.',
    current_rank: i + 1, season_points: Math.max(0, 10 - i), cumulative_points: 40 - i * 2,
    return_1m: .04 - i * .002, return_3m: .12 - i * .005, return_6m: null, return_1y: null,
    excess_vs_qqq: .03 - i * .001, excess_vs_pool: .02 - i * .001,
    max_drawdown: -.06 - i * .004, sharpe_ratio: 1.5 - i * .03, persistence_ratio: .75,
    monthly_ranks: ['2026-07', '2026-08', '2026-09', '2026-10'].map(month => ({
      month, rank: i + 1, total_runners: count, points_earned: Math.max(0, 10 - i), monthly_net_return: .03,
    })),
  }));
  const scoreboard = {
    schema_version: '1.0', pool_id: pool, benchmark_symbol: benchmark,
    as_of_session: dates[dates.length - 1], season_id: `season_${market}_2026_10`,
    status: count ? 'operational_race' : 'diagnostic_baseline_only',
    period_policy: 'calendar_month_buckets_including_partial', dates,
    benchmarks: { pool_index: dates.map((_, i) => 1 + i * .01), macro: dates.map((_, i) => 1 + i * .008) },
    entries, top_runners_nav: Object.fromEntries(entries.slice(0, 10).map((entry, i) => [entry.runner_id, dates.map((_, j) => 1 + j * (.025 - i * .0015))])),
  };
  const files: Record<string, string> = {};
  const artifacts: Record<string, { path: string; sha256: string; size_bytes: number }> = {};
  const add = (key: string, path: string, value: unknown) => {
    const raw = JSON.stringify(value);
    const ref = `versions/${release}/${path}`;
    files[ref] = raw;
    artifacts[key] = { path: ref, sha256: createHash('sha256').update(raw).digest('hex'), size_bytes: Buffer.byteLength(raw) };
  };
  add('scoreboard_latest', 'scoreboard_latest.json', scoreboard);
  add('scoreboard_archive', 'archive/scoreboard_2026-10-26.json', scoreboard);
  const detailRefs: Record<string, string> = {};
  for (const entry of entries) {
    const key = `runner:${entry.runner_id}`;
    detailRefs[entry.runner_id] = key;
    add(key, `runners/${createHash('sha256').update(entry.runner_id).digest('hex')}.json`, {
      schema_version: '1.0', runner_id: entry.runner_id, runner_version: entry.runner_version,
      pool_id: pool, market, as_of_session: scoreboard.as_of_session,
      thesis: `Synthetic thesis for ${entry.runner_id}. Used only to verify UI contracts, not investment performance.`,
      selection_logic: 'Fixture selection rule, with no deployed strategy or effective edge claim.',
      rebalance_logic: 'Synthetic monthly allocation used for interaction testing.',
      model_weights: [{ symbol: market === 'us' ? 'AAPL' : '600519', weight: .7 }], cash_weight: .3,
      monthly_ranks: entry.monthly_ranks, limitations: ['Synthetic test fixture. Not live holdings or measured research.'],
      rebalance_history: null, association_evidence: null, research_only: true, trade_ready: false,
    });
  }
  const manifest = {
    schema_version: '1.0', pipeline_version: '1.1.0', release_id: release,
    market, pool_id: pool, benchmark_symbol: benchmark,
    as_of_session: scoreboard.as_of_session, as_of_cutoff: '2026-10-26', season_id: scoreboard.season_id,
    generated_at_utc: '2026-10-27T00:00:00Z', data_qualification: 'synthetic_test_fixture_not_research_evidence',
    engine_config: { friction_rate: .0008 }, runner_count: count, artifacts, runner_details: detailRefs,
    research_only: true, trade_ready: false,
  };
  return { manifest, scoreboard, files };
}
