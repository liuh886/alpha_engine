import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useMarketComparisons } from './useMarketComparisons';

const mocks = vi.hoisted(() => ({
  loadCatalog: vi.fn(),
  loadSecurity: vi.fn(),
}));

vi.mock('@/lib/market-evidence', () => ({
  loadMarketEvidenceCatalog: mocks.loadCatalog,
  loadSecurityMarketEvidence: mocks.loadSecurity,
}));

const catalog = (market: 'us' | 'cn') => ({ market });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};

describe('useMarketComparisons', () => {
  beforeEach(() => {
    mocks.loadCatalog.mockReset();
    mocks.loadSecurity.mockReset();
  });

  it('loads catalogs only when Compare is opened', async () => {
    mocks.loadCatalog.mockImplementation(async (market: 'us' | 'cn') => catalog(market));
    const { result } = renderHook(() => useMarketComparisons('us'));

    expect(mocks.loadCatalog).not.toHaveBeenCalled();
    await act(async () => { await result.current.ensureCatalogs(); });
    expect(mocks.loadCatalog).toHaveBeenCalledTimes(2);
    expect(result.current.catalogs.map(item => item.market)).toEqual(['us', 'cn']);
  });

  it('drops an in-flight series when the market context changes', async () => {
    mocks.loadCatalog.mockImplementation(async (market: 'us' | 'cn') => catalog(market));
    const stale = deferred<{ bars: Array<{ time: string }> }>();
    mocks.loadSecurity.mockReturnValue(stale.promise);
    const { result, rerender } = renderHook(({ market }) => useMarketComparisons(market), {
      initialProps: { market: 'us' as 'us' | 'cn' },
    });

    await act(async () => { await result.current.ensureCatalogs(); });
    let request!: Promise<void>;
    act(() => {
      request = result.current.requestComparison({ key: 'us:AAPL', market: 'us', symbol: 'AAPL' });
    });
    expect(result.current.loadingKeys).toContain('us:AAPL');

    rerender({ market: 'cn' });
    await act(async () => {
      stale.resolve({ bars: [{ time: '2026-08-14' }] });
      await request;
    });

    expect(result.current.marketBars).toEqual({});
    expect(result.current.loadingKeys).toEqual([]);
    expect(result.current.failedKeys).toEqual([]);
  });

  it('surfaces failed series and allows retry', async () => {
    mocks.loadCatalog.mockImplementation(async (market: 'us' | 'cn') => catalog(market));
    mocks.loadSecurity
      .mockRejectedValueOnce(new Error('network failed'))
      .mockResolvedValueOnce({ bars: [{ time: '2026-08-14' }] });
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { result } = renderHook(() => useMarketComparisons('us'));

    await act(async () => { await result.current.ensureCatalogs(); });
    await act(async () => {
      await result.current.requestComparison({ key: 'us:AAPL', market: 'us', symbol: 'AAPL' });
    });
    expect(result.current.failedKeys).toContain('us:AAPL');

    await act(async () => {
      await result.current.requestComparison({ key: 'us:AAPL', market: 'us', symbol: 'AAPL' });
    });
    expect(result.current.failedKeys).not.toContain('us:AAPL');
    expect(result.current.marketBars['us:AAPL']).toHaveLength(1);
    consoleError.mockRestore();
  });
});
