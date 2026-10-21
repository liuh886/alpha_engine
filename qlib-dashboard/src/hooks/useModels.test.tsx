import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useModels } from './useModels';
import { loadFormalRuns, type GovernedRunSummary } from '@/lib/governed-run';
import { useGlobalStore } from '@/store/globalStore';
vi.mock('@/lib/governed-run', () => ({ loadFormalRuns: vi.fn() }));
const byd = { key: 'byd-new', channel: 'formal', modelVersionId: 'byd_v1_3', title: 'BYD v1.3' } as GovernedRunSummary;
const qqq = { ...byd, key: 'qqq-new', modelVersionId: 'qqq_v4_3', title: 'QQQR v4.3' };
beforeEach(() => { vi.clearAllMocks(); useGlobalStore.setState({ activeRunKey: '', selectedModelId: '' }); });
describe('formal-only workspace bootstrap', () => {
  it('preserves strategy selection when daily identities advance', async () => {
    useGlobalStore.setState({ activeRunKey: 'qqq-old', selectedModelId: qqq.modelVersionId });
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [byd, qqq], errors: [] });
    const { result } = renderHook(useModels);
    await act(async () => { await result.current.fetchModels(); });
    expect(result.current.activeRunKey).toBe(qqq.key);
    expect(result.current.runs).toEqual([byd, qqq]);
  });
  it('preserves exact selection and falls back when a strategy disappears', async () => {
    useGlobalStore.setState({ activeRunKey: qqq.key, selectedModelId: qqq.modelVersionId });
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [byd, qqq], errors: [] });
    const { result } = renderHook(useModels);
    await act(async () => { await result.current.fetchModels(); });
    expect(result.current.activeRunKey).toBe(qqq.key);
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [byd], errors: [] });
    await act(async () => { await result.current.fetchModels(); });
    expect(result.current.activeRunKey).toBe(byd.key);
  });
  it('rejects a partial load with an integrity failure', async () => {
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [byd], errors: ['manifest hash mismatch'] });
    const { result } = renderHook(useModels);
    await act(async () => { expect(await result.current.fetchModels()).toBeNull(); });
    expect(result.current.runs).toEqual([]);
    expect(result.current.runLoadErrors).toContain('manifest hash mismatch');
  });
  it('keeps an empty formal catalog unavailable', async () => {
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [], errors: [] });
    const { result } = renderHook(useModels);
    await act(async () => { expect(await result.current.fetchModels()).toBeNull(); });
    expect(result.current.runs).toEqual([]);
  });
});
