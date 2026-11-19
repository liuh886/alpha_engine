import { describe, expect, it } from 'vitest';
import type { GovernedRunSummary } from './governed-run';
import {
  MAX_MODEL_OVERLAYS,
  MODEL_WINDOW_REJECTION,
  globalModelWindow,
  marketModelIds,
  modelCompareId,
  modelCompareOptions,
  modelIdentityColors,
  sameMarketModels,
} from './model-comparison';
import type { NavPoint } from './nav-series';

function makeRun(overrides: Partial<GovernedRunSummary> & { modelVersionId: string }): GovernedRunSummary {
  const { modelVersionId, ...rest } = overrides;
  return {
    key: `formal:family:${modelVersionId}:run`,
    modelFamilyId: 'family',
    modelVersionId,
    runId: `run-${modelVersionId}`,
    bundleId: 'b'.repeat(64),
    title: modelVersionId,
    modelKind: 'rules_based_allocation',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'us',
    benchmark: 'QQQ',
    generatedAt: '2026-01-12T00:00:00Z',
    evidenceCutoff: '2026-01-11',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: null,
    manifestSha256: null,
    summary: {},
    manifest: null,
    loadWarnings: [],
    ...rest,
  };
}

function points(startDay: number, endDay = 10, offset = 0): NavPoint[] {
  return Array.from({ length: endDay - startDay + 1 }, (_, index) => {
    const day = startDay + index;
    return { date: `2025-01-${String(day).padStart(2, '0')}`, value: 100 + offset + day };
  });
}

const base = { id: 'base', label: 'Base', modelVersionId: 'base_v1', points: points(1) };
const overlay = {
  id: 'overlay-a',
  label: 'Overlay A',
  modelVersionId: 'overlay_a_v1',
  points: points(3, 10, 200),
};
const baseline = { id: 'baseline', label: 'QQQ', points: points(2, 10, 500) };

describe('sameMarketModels', () => {
  it('excludes the base, isolates the market and deduplicates model versions', () => {
    const runs = [
      makeRun({ modelVersionId: 'base_v1' }),
      makeRun({ modelVersionId: 'overlay_a_v1' }),
      makeRun({ modelVersionId: 'overlay_a_v1', runId: 'second-run' }),
      makeRun({ modelVersionId: 'cn_v1', market: 'cn' }),
    ];
    expect(sameMarketModels(runs, 'us', 'base_v1').map(run => run.modelVersionId))
      .toEqual(['overlay_a_v1']);
    expect(sameMarketModels(runs, 'cn', 'base_v1').map(run => run.modelVersionId))
      .toEqual(['cn_v1']);
  });

  it('lists every same-market identity including the base for stable color assignment', () => {
    const runs = [
      makeRun({ modelVersionId: 'zeta' }),
      makeRun({ modelVersionId: 'alpha' }),
      makeRun({ modelVersionId: 'cn', market: 'cn' }),
    ];
    expect(marketModelIds(runs, 'us')).toEqual(['alpha', 'zeta']);
  });
});

describe('modelCompareOptions', () => {
  const runs = [
    makeRun({ modelVersionId: 'base_v1', title: 'Base' }),
    makeRun({ modelVersionId: 'us_b_v1', title: 'US B' }),
    makeRun({ modelVersionId: 'us_a_v1', title: 'US A' }),
    makeRun({ modelVersionId: 'cn_c_v1', title: 'CN C', market: 'cn' }),
  ];

  it('offers same-market models only and never the base', () => {
    const options = modelCompareOptions({
      runs,
      market: 'us',
      baseModelVersionId: 'base_v1',
    });
    expect(options.map(option => option.modelVersionId)).toEqual(['us_a_v1', 'us_b_v1']);
    expect(options.every(option => option.market === 'us')).toBe(true);
    expect(options.every(option => option.id === modelCompareId('us', option.modelVersionId))).toBe(true);
  });

  it('keeps a model that is already the active baseline visible but unavailable', () => {
    const options = modelCompareOptions({
      runs,
      market: 'us',
      baseModelVersionId: 'base_v1',
      baselineIdentity: 'US A',
    });
    const duplicate = options.find(option => option.modelVersionId === 'us_a_v1');
    expect(duplicate?.available).toBe(false);
    expect(duplicate?.reason).toBe('Already displayed as the active baseline.');
  });

  it('carries a runtime failure reason without dropping the option', () => {
    const options = modelCompareOptions({
      runs,
      market: 'us',
      baseModelVersionId: 'base_v1',
      unavailable: new Map([['us_b_v1', 'Verified NAV projection unavailable.']]),
    });
    const rejected = options.find(option => option.modelVersionId === 'us_b_v1');
    expect(rejected?.available).toBe(false);
    expect(rejected?.reason).toBe('Verified NAV projection unavailable.');
  });
});

describe('modelIdentityColors', () => {
  it('assigns fixed tokens by sorted model identity, not selection order', () => {
    const forward = modelIdentityColors(['a', 'b', 'c', 'd', 'e']);
    const reverse = modelIdentityColors(['e', 'd', 'c', 'b', 'a']);
    expect(forward.get('a')).toEqual(reverse.get('a'));
    expect(forward.get('a')).toMatchObject({ token: 'chart-4', role: 'model-1' });
    expect(forward.get('b')).toMatchObject({ token: 'chart-6', role: 'model-2' });
    expect(forward.get('c')).toMatchObject({ token: 'chart-3', role: 'model-3' });
    expect(forward.get('d')).toMatchObject({ token: 'chart-5', role: 'model-4' });
    expect(forward.get('e')).toMatchObject({ token: 'chart-1', role: 'model-5' });
  });

  it('uses the neutral overflow colour past the validated five-slot order', () => {
    const colors = modelIdentityColors(['a', 'b', 'c', 'd', 'e', 'f']);
    expect(colors.get('f')).toEqual({
      token: 'muted-foreground',
      role: 'muted',
      color: 'hsl(var(--muted-foreground))',
    });
  });
});

describe('globalModelWindow', () => {
  it('rebases every series to 100 at the global exact common start', () => {
    const window = globalModelWindow({ base, overlays: [overlay], baseline, start: '2025-01-01', end: '2025-01-10' });
    expect(window).not.toBeNull();
    expect(window?.startDate).toBe('2025-01-03');
    expect(window?.endDate).toBe('2025-01-10');
    expect(window?.observations).toBe(8);
    expect(window?.series.map(series => [series.id, series.role])).toEqual([
      ['base', 'base'],
      ['baseline', 'baseline'],
      ['overlay-a', 'overlay'],
    ]);
    for (const series of window?.series ?? []) {
      expect(series.points[0]).toEqual({ date: '2025-01-03', value: 100 });
    }
    expect(window?.rejected.size).toBe(0);
    expect(window?.baselineIncluded).toBe(true);
  });

  it('keeps raw observations on the global window so returns never start earlier', () => {
    const window = globalModelWindow({ base, overlays: [overlay], baseline, start: '2025-01-01', end: '2025-01-10' });
    const rawBase = window?.raw.get('base') ?? [];
    expect(rawBase[0]).toEqual({ date: '2025-01-03', value: 103 });
    expect(rawBase[rawBase.length - 1]).toEqual({ date: '2025-01-10', value: 110 });
  });

  it('narrows the window when another model is added and never interpolates a missing date', () => {
    const sparse = {
      id: 'overlay-b',
      label: 'Overlay B',
      modelVersionId: 'overlay_b_v1',
      points: [
        { date: '2025-01-04', value: 300 },
        { date: '2025-01-06', value: 302 },
        { date: '2025-01-08', value: 304 },
        { date: '2025-01-10', value: 306 },
      ],
    };
    const first = globalModelWindow({ base, overlays: [overlay], baseline, start: '2025-01-01', end: '2025-01-10' });
    const both = globalModelWindow({
      base,
      overlays: [overlay, sparse],
      baseline,
      start: '2025-01-01',
      end: '2025-01-10',
    });
    expect(first?.startDate).toBe('2025-01-03');
    expect(both?.startDate).toBe('2025-01-04');
    expect(both?.observations).toBe(4);
    expect(both?.series.find(series => series.id === 'overlay-b')?.points.map(point => point.date))
      .toEqual(['2025-01-04', '2025-01-06', '2025-01-08', '2025-01-10']);
  });

  it('re-windows when the period bounds change', () => {
    const window = globalModelWindow({ base, overlays: [overlay], baseline, start: '2025-01-06', end: '2025-01-10' });
    expect(window?.startDate).toBe('2025-01-06');
    expect(window?.endDate).toBe('2025-01-10');
    expect(window?.observations).toBe(5);
    expect(window?.series[0].points[0]).toEqual({ date: '2025-01-06', value: 100 });
  });

  it('rejects an overlay with fewer than two exact common dates instead of plotting it partially', () => {
    const almostEmpty = {
      id: 'overlay-c',
      label: 'Overlay C',
      modelVersionId: 'overlay_c_v1',
      points: [{ date: '2025-01-10', value: 400 }],
    };
    const window = globalModelWindow({
      base,
      overlays: [almostEmpty],
      baseline,
      start: '2025-01-01',
      end: '2025-01-10',
    });
    expect(window?.rejected.get('overlay-c')).toBe(MODEL_WINDOW_REJECTION);
    expect(window?.series.map(series => series.id)).toEqual(['base', 'baseline']);
    expect(window?.series.some(series => series.id === 'overlay-c')).toBe(false);
    expect(window?.rejected.has('overlay-c')).toBe(true);
  });

  it('keeps the base and overlays readable when the baseline has no usable overlap', () => {
    const farBaseline = { id: 'baseline', label: 'Far', points: points(1, 1, 900) };
    const window = globalModelWindow({
      base,
      overlays: [overlay],
      baseline: farBaseline,
      start: '2025-01-01',
      end: '2025-01-10',
    });
    expect(window?.baselineIncluded).toBe(false);
    expect(window?.series.map(series => series.id)).toEqual(['base', 'overlay-a']);
    expect(window?.raw.has('baseline')).toBe(false);
  });

  it('returns no window when the base cannot supply two observations', () => {
    const onePoint = { id: 'base', label: 'Base', points: [{ date: '2025-01-01', value: 100 }] };
    expect(globalModelWindow({
      base: onePoint,
      overlays: [],
      baseline: null,
      start: '2025-01-01',
      end: '2025-01-10',
    })).toBeNull();
  });

  it('documents the three-overlay cap', () => {
    expect(MAX_MODEL_OVERLAYS).toBe(3);
  });
});
