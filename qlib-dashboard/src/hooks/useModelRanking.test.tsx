import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DerivedExcess } from '@/lib/derived-excess';
import type { FormalNavSeries } from '@/lib/formal-nav';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { SecurityBar, SecurityEvidence } from '@/lib/security-evidence';

vi.mock('@/lib/formal-nav', () => ({ loadFormalNav: vi.fn() }));
vi.mock('@/lib/security-evidence', () => ({ loadSecurityEvidence: vi.fn() }));
vi.mock('@/lib/derived-excess', () => ({ loadDerivedExcess: vi.fn() }));

function run(overrides: Partial<GovernedRunSummary> = {}): GovernedRunSummary {
  return {
    key: 'us_x1_3',
    modelFamilyId: 'us_x',
    modelVersionId: 'us_x1_3',
    runId: 'us_x1_3-formal',
    bundleId: 'b'.repeat(64),
    title: 'US x1.3',
    modelKind: 'cross_sectional_ranker',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'us',
    benchmark: 'QQQ',
    generatedAt: '2026-11-12',
    evidenceCutoff: '2026-11-11',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: 'us_x/manifest.json',
    manifestSha256: 'a'.repeat(64),
    summary: { metrics: [] },
    manifest: null,
    loadWarnings: [],
    ...overrides,
  };
}

const US_RUN = run();
const CN_RUN = run({
  key: 'cn_27_v1_3',
  modelFamilyId: 'cn_27',
  modelVersionId: 'cn_27_v1_3',
  runId: 'cn_27_v1_3-formal',
  title: 'CN_27 V1.3',
  market: 'cn',
  benchmark: '000300',
});

function navSeries(owner: GovernedRunSummary, points: Array<[string, number]>): FormalNavSeries {
  return {
    key: owner.key,
    schema_version: 'formal_nav_projection_v1',
    view: 'nav_series_v1',
    research_only: true,
    trade_ready: false,
    model_family_id: owner.modelFamilyId,
    model_version_id: owner.modelVersionId,
    run_id: owner.runId,
    bundle_id: owner.bundleId ?? '',
    manifest_sha256: owner.manifestSha256 ?? '',
    evidence_cutoff: owner.evidenceCutoff,
    benchmark: owner.benchmark,
    trace_frequency: null,
    date_range: null,
    performance: { section_id: 'performance', sha256: 'c'.repeat(64), byte_size: 10 },
    rows: points.map(([date, account]) => ({ date, account })),
  };
}

function bars(start: number): SecurityBar[] {
  return [
    { time: '2026-11-04', open: start, high: start, low: start, close: start, volume: 1 },
    { time: '2026-11-06', open: start + 1, high: start + 1, low: start + 1, close: start + 1, volume: 1 },
    { time: '2026-11-11', open: start + 2, high: start + 2, low: start + 2, close: start + 2, volume: 1 },
  ];
}

function evidence(market: 'us' | 'cn', symbol: string): SecurityEvidence {
  return {
    market,
    symbol,
    name: symbol,
    cutoff: '2026-11-11',
    source_sha256: 'd'.repeat(64),
    provider_manifest_sha256: 'e'.repeat(64),
    bars: bars(market === 'us' ? 690 : 4000),
    events: [],
    bindings: [],
  };
}

const DERIVED: DerivedExcess = {
  key: 'derived:qqqi',
  derivationId: 'derived-qqqi',
  schemaVersion: '1.0',
  evidenceType: 'derived_formal_benchmark_excess' as DerivedExcess['evidenceType'],
  boundaries: {
    research_only: true,
    trade_ready: false,
    descriptive_historical_metric: true,
    live_signal: false,
  },
  modelFamilyId: 'qqqi',
  modelVersionId: 'qqqi_v1_3',
  runId: 'qqqi_v1_3-formal',
  manifestSha256: 'f'.repeat(64),
  methodId: 'compounded_relative_excess',
  result: { strategy_cumulative_return: 1.2, benchmark_cumulative_return: 1, excess_return: 0.2 },
  window: {
    declared_start: '2024-01-30',
    declared_end: null,
    observed_start: '2024-01-30',
    observed_end: '2026-11-10',
    evidence_cutoff: '2026-11-11',
    observation_count: 699,
  },
  benchmark: { comparability_id: 'qqq', declared_identity: 'QQQ', series_semantics: 'close' },
  label: 'Derived · vs QQQ · 2024-01-30 → 2026-11-10 · 699 observations',
};

async function harness() {
  const formalNav = await import('@/lib/formal-nav');
  const security = await import('@/lib/security-evidence');
  const derived = await import('@/lib/derived-excess');
  const { useModelRanking } = await import('./useModelRanking');
  const { renderHook, waitFor } = await import('@testing-library/react');
  return {
    useModelRanking,
    renderHook,
    waitFor,
    loadFormalNav: vi.mocked(formalNav.loadFormalNav),
    loadSecurityEvidence: vi.mocked(security.loadSecurityEvidence),
    loadDerivedExcess: vi.mocked(derived.loadDerivedExcess),
  };
}

beforeEach(() => {
  // The governed market-evidence promise cache is module-scoped; a fresh
  // module generation keeps each case independent without touching production
  // cache behavior.
  vi.resetModules();
  vi.clearAllMocks();
});

describe('useModelRanking', () => {
  it('reads one compact NAV projection per run and only the two governed indices', async () => {
    const { useModelRanking, renderHook, waitFor, loadFormalNav, loadSecurityEvidence, loadDerivedExcess } = await harness();
    loadFormalNav.mockImplementation(async (owner) => navSeries(owner, [
      ['2026-10-11', 100],
      ['2026-11-11', 110],
    ]));
    loadSecurityEvidence.mockImplementation(async (market, symbol) => evidence(market, symbol));
    const runs = [US_RUN, CN_RUN];
    const { result } = renderHook(() => useModelRanking(runs, { includeIndices: true, includeExcess: false }));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.issues).toEqual([]);
    expect(result.current.rows.map((row) => row.id).sort()).toEqual([
      'cn_27_v1_3', 'index:cn:000300', 'index:us:QQQ', 'us_x1_3',
    ]);
    expect(loadFormalNav).toHaveBeenCalledTimes(2);
    expect(loadSecurityEvidence).toHaveBeenCalledTimes(2);
    expect(loadSecurityEvidence).toHaveBeenCalledWith('us', 'QQQ');
    expect(loadSecurityEvidence).toHaveBeenCalledWith('cn', '000300');
    for (const [market, symbol] of loadSecurityEvidence.mock.calls) {
      expect(`${market}:${symbol}`).not.toMatch(/spy|voo|ivv|gspc|\^/i);
    }
    expect(loadDerivedExcess).not.toHaveBeenCalled();
  });

  it('scopes a governed index failure to that market without dropping strategies', async () => {
    const { useModelRanking, renderHook, waitFor, loadFormalNav, loadSecurityEvidence } = await harness();
    loadFormalNav.mockImplementation(async (owner) => navSeries(owner, [
      ['2026-10-11', 100],
      ['2026-11-11', 110],
    ]));
    loadSecurityEvidence.mockImplementation(async (market, symbol) => {
      if (market === 'us') throw new Error('governed closes unavailable');
      return evidence(market, symbol);
    });
    const runs = [US_RUN, CN_RUN];
    const { result } = renderHook(() => useModelRanking(runs, { includeIndices: true, includeExcess: false }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.rows.map((row) => row.id).sort()).toEqual([
      'cn_27_v1_3', 'index:cn:000300', 'us_x1_3',
    ]);
    expect(result.current.issues).toHaveLength(1);
    expect(result.current.issues[0]).toMatchObject({
      id: 'index:us:QQQ',
      kind: 'index',
      message: expect.stringContaining('QQQ: governed market evidence unavailable'),
    });
  });

  it('keeps a strategy read failure scoped and never falls back to another section', async () => {
    const { useModelRanking, renderHook, waitFor, loadFormalNav, loadSecurityEvidence } = await harness();
    loadFormalNav.mockImplementation(async (owner) => {
      if (owner.key === US_RUN.key) throw new Error('nav projection missing');
      return navSeries(owner, [['2026-10-11', 100], ['2026-11-11', 110]]);
    });
    const runs = [US_RUN, CN_RUN];
    const { result } = renderHook(() => useModelRanking(runs, { includeIndices: false, includeExcess: false }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(loadSecurityEvidence).not.toHaveBeenCalled();
    expect(result.current.rows).toHaveLength(1);
    expect(result.current.rows[0].id).toBe('cn_27_v1_3');
    expect(result.current.issues).toHaveLength(1);
    expect(result.current.issues[0]).toMatchObject({
      id: 'us_x1_3',
      kind: 'strategy',
      message: expect.stringContaining('US x1.3: ranking evidence unavailable'),
    });
  });

  it('labels retained excess and uses a derived artifact only when no retained value exists', async () => {
    const { useModelRanking, renderHook, waitFor, loadFormalNav, loadDerivedExcess } = await harness();
    loadFormalNav.mockImplementation(async (owner) => navSeries(owner, [
      ['2026-10-11', 100],
      ['2026-11-11', 110],
    ]));
    loadDerivedExcess.mockResolvedValue(DERIVED);
    const retainedRun = run({
      key: 'byd_v1_3',
      modelFamilyId: 'byd',
      modelVersionId: 'byd_v1_3',
      runId: 'byd_v1_3-formal',
      title: 'BYD v1.3',
      market: 'cn',
      benchmark: 'BYD v1.2',
      summary: { metrics: [
        { metric_id: 'excess_return', value: 0.25, availability_status: 'available', scope: 'full_history' },
      ] },
    });
    const runs = [retainedRun, US_RUN];
    const { result } = renderHook(() => useModelRanking(runs, { includeIndices: false, includeExcess: true }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(loadDerivedExcess).toHaveBeenCalledTimes(1);
    expect(loadDerivedExcess).toHaveBeenCalledWith(US_RUN);
    const retained = result.current.rows.find((row) => row.id === retainedRun.modelVersionId);
    const derived = result.current.rows.find((row) => row.id === US_RUN.modelVersionId);
    expect(retained?.excess).toMatchObject({ value: 0.25, source: 'retained', label: 'retained' });
    expect(derived?.excess).toMatchObject({ value: 0.2, source: 'derived', label: 'derived' });
  });

  it('keeps a derived-excess failure inside the excess cell reason', async () => {
    const { useModelRanking, renderHook, waitFor, loadFormalNav, loadDerivedExcess } = await harness();
    loadFormalNav.mockImplementation(async (owner) => navSeries(owner, [
      ['2026-10-11', 100],
      ['2026-11-11', 110],
    ]));
    loadDerivedExcess.mockRejectedValue(new Error('derived artifact digest mismatch'));
    const runs = [US_RUN];
    const { result } = renderHook(() => useModelRanking(runs, { includeIndices: false, includeExcess: true }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.rows).toHaveLength(1);
    expect(result.current.rows[0].excess).toMatchObject({ value: null, source: 'unavailable' });
    expect(result.current.rows[0].excess?.reason).toContain('Derived excess unavailable: derived artifact digest mismatch');
    expect(result.current.issues).toEqual([]);
  });

  it('reuses each governed market-evidence read across mounts', async () => {
    const { useModelRanking, renderHook, waitFor, loadSecurityEvidence } = await harness();
    loadSecurityEvidence.mockImplementation(async (market, symbol) => evidence(market, symbol));
    const runs: GovernedRunSummary[] = [];
    const first = renderHook(() => useModelRanking(runs, { includeIndices: true, includeExcess: false }));
    await waitFor(() => expect(first.result.current.rows).toHaveLength(2));
    first.unmount();

    const second = renderHook(() => useModelRanking(runs, { includeIndices: true, includeExcess: false }));
    await waitFor(() => expect(second.result.current.rows).toHaveLength(2));

    expect(loadSecurityEvidence).toHaveBeenCalledTimes(2);
  });

  it('stays idle when there are no runs and indices are excluded', async () => {
    const { useModelRanking, renderHook, loadFormalNav, loadSecurityEvidence } = await harness();
    const runs: GovernedRunSummary[] = [];
    const { result } = renderHook(() => useModelRanking(runs, { includeIndices: false, includeExcess: false }));
    expect(result.current).toEqual({ rows: [], loading: false, issues: [] });
    expect(loadFormalNav).not.toHaveBeenCalled();
    expect(loadSecurityEvidence).not.toHaveBeenCalled();
  });
});
