import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SecurityBar, SecurityEvidence } from './security-evidence';

const { loadSecurityEvidence } = vi.hoisted(() => ({ loadSecurityEvidence: vi.fn() }));

vi.mock('./security-evidence', async importOriginal => {
  const actual = await importOriginal<typeof import('./security-evidence')>();
  return { ...actual, loadSecurityEvidence };
});

import {
  clearMarketBaselineCache,
  indexedBaselineSeries,
  isMarketBaselineInstrument,
  loadMarketBaseline,
  marketBaseline,
  securityBaselineCacheKey,
} from './security-baseline';

const bar = (time: string, open: number): SecurityBar => ({
  time, open, high: open + 1, low: open - 1, close: open + 0.5, volume: 10,
});

const evidence = (symbol: string): SecurityEvidence => ({
  market: symbol === '000300' ? 'cn' : 'us',
  symbol,
  name: symbol,
  cutoff: '2026-03-01',
  source_sha256: 'a'.repeat(64),
  provider_manifest_sha256: 'b'.repeat(64),
  bars: [bar('2026-01-02', 100)],
  events: [],
  bindings: [],
});

describe('security baseline identity', () => {
  afterEach(() => {
    loadSecurityEvidence.mockReset();
    clearMarketBaselineCache();
  });

  it('names only the governed market baseline per market', () => {
    expect(marketBaseline('us')).toEqual({ symbol: 'QQQ', label: 'QQQ' });
    expect(marketBaseline('cn')).toEqual({ symbol: '000300', label: 'CSI 300 (000300.SH)' });
    expect(isMarketBaselineInstrument('us', 'QQQ')).toBe(true);
    expect(isMarketBaselineInstrument('us', 'qqq')).toBe(true);
    expect(isMarketBaselineInstrument('us', 'SPY')).toBe(false);
    expect(isMarketBaselineInstrument('cn', '000300')).toBe(true);
    expect(isMarketBaselineInstrument('cn', 'QQQ')).toBe(false);
  });

  it('intersects exact dates and rebases both series to 100 at the first common date', () => {
    const series = indexedBaselineSeries(
      [
        bar('2026-01-02', 50),
        bar('2026-01-05', 55),
        bar('2026-01-06', 60),
      ],
      [
        bar('2026-01-05', 200),
        bar('2026-01-06', 190),
        bar('2026-01-07', 210),
      ],
    );
    expect(series).not.toBeNull();
    expect(series!.startDate).toBe('2026-01-05');
    expect(series!.endDate).toBe('2026-01-06');
    expect(series!.observations).toBe(2);
    expect(series!.instrument).toEqual([
      { date: '2026-01-05', value: 100 },
      { date: '2026-01-06', value: (60 / 55) * 100 },
    ]);
    expect(series!.baseline).toEqual([
      { date: '2026-01-05', value: 100 },
      { date: '2026-01-06', value: (190 / 200) * 100 },
    ]);
  });

  it('requires at least two exact common observations and never interpolates', () => {
    expect(indexedBaselineSeries([bar('2026-01-02', 50)], [bar('2026-01-05', 200)])).toBeNull();
    expect(indexedBaselineSeries(
      [bar('2026-01-02', 50), bar('2026-01-05', 55)],
      [bar('2026-01-02', 200)],
    )).toBeNull();
  });

  it('caches the baseline request per market, symbol and cutoff', async () => {
    loadSecurityEvidence.mockResolvedValue(evidence('QQQ'));
    const first = loadMarketBaseline('us', '2026-03-01');
    const second = loadMarketBaseline('us', '2026-03-01');
    expect(second).toBe(first);
    await first;
    expect(loadSecurityEvidence).toHaveBeenCalledTimes(1);
    expect(loadSecurityEvidence).toHaveBeenCalledWith('us', 'QQQ');
    expect(securityBaselineCacheKey('us', 'qqq', '2026-03-01')).toBe('us:QQQ:2026-03-01');
  });

  it('evicts a failed baseline request so the mode can retry', async () => {
    loadSecurityEvidence.mockRejectedValueOnce(new Error('baseline missing'));
    await expect(loadMarketBaseline('cn', '2026-03-01')).rejects.toThrow('baseline missing');
    loadSecurityEvidence.mockResolvedValueOnce(evidence('000300'));
    await expect(loadMarketBaseline('cn', '2026-03-01')).resolves.toMatchObject({ symbol: '000300' });
    expect(loadSecurityEvidence).toHaveBeenCalledTimes(2);
  });

  it('rejects a published baseline whose resolved identity is not the governed symbol', async () => {
    loadSecurityEvidence.mockResolvedValue(evidence('SPY'));
    await expect(loadMarketBaseline('us', '2026-03-01')).rejects.toThrow(/governed symbol/);
  });
});
