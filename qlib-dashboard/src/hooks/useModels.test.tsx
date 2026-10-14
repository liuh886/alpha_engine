import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useModels } from './useModels';
import { modelsApi } from '@/api/modelsApi';
import { loadFormalRuns, loadPreviewRuns, type GovernedRunSummary } from '@/lib/governed-run';
import { useGlobalStore } from '@/store/globalStore';

vi.mock('@/api/modelsApi', () => ({ modelsApi: { getDashboardDb: vi.fn() } }));
vi.mock('@/lib/governed-run', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/governed-run')>(),
  loadFormalRuns: vi.fn(), loadPreviewRuns: vi.fn(),
}));

describe('formal workspace bootstrap', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    useGlobalStore.setState({ activeRunKey: '', selectedModelId: '' });
  });

  it('keeps the selected model when a new daily run replaces its exact key', async () => {
    vi.mocked(modelsApi.getDashboardDb).mockRejectedValue(new Error('Legacy unavailable'));
    vi.mocked(loadPreviewRuns).mockResolvedValue({ runs: [], errors: [] });
    const byd = { key: 'byd-new', channel: 'formal', modelVersionId: 'byd_v1_3', evidenceCutoff: '2026-10-13', title: 'BYD v1.3', summary: {} } as GovernedRunSummary;
    const qqq = { ...byd, key: 'qqq-new', modelVersionId: 'qqq_v4_3', title: 'QQQR v4.3' };
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [byd, qqq], errors: [] });
    useGlobalStore.setState({ activeRunKey: 'qqq-old', selectedModelId: qqq.modelVersionId });
    const { result } = renderHook(useModels);
    await act(async () => { await result.current.fetchModels(); });
    expect(result.current.activeRunKey).toBe(qqq.key);
    expect(sessionStorage.getItem('selectedModelId')).toBe(JSON.stringify(qqq.modelVersionId));
    expect(result.current.runs.map((run) => run.key)).toEqual([byd.key, qqq.key]);
  });

  it('preserves an exact selection and falls back safely when the model disappears', async () => {
    vi.mocked(modelsApi.getDashboardDb).mockRejectedValue(new Error('Legacy unavailable'));
    vi.mocked(loadPreviewRuns).mockResolvedValue({ runs: [], errors: [] });
    const byd = { key: 'byd-new', channel: 'formal', modelVersionId: 'byd_v1_3', evidenceCutoff: '2026-10-13', title: 'BYD v1.3', summary: {} } as GovernedRunSummary;
    const qqq = { ...byd, key: 'qqq-new', modelVersionId: 'qqq_v4_3', title: 'QQQR v4.3' };
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [byd, qqq], errors: [] });
    useGlobalStore.setState({ activeRunKey: qqq.key, selectedModelId: qqq.modelVersionId });
    const { result } = renderHook(useModels);
    await act(async () => { await result.current.fetchModels(); });
    expect(result.current.activeRunKey).toBe(qqq.key);
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [byd], errors: [] });
    await act(async () => { await result.current.fetchModels(); });
    expect(result.current.activeRunKey).toBe(byd.key);
    expect(result.current.selectedModelId).toBe(byd.modelVersionId);
  });

  it('keeps verified formal evidence accessible when the optional legacy bundle fails', async () => {
    vi.mocked(modelsApi.getDashboardDb).mockRejectedValue(new Error('Legacy bundle unavailable'));
    vi.mocked(loadPreviewRuns).mockResolvedValue({ runs: [], errors: [] });
    const formal = {
      key: 'formal:cn:cn_x1_2:run', channel: 'formal', modelVersionId: 'cn_x1_2',
      evidenceCutoff: '2026-09-24', generatedAt: '2026-09-25', title: 'CN x1.2', summary: {},
    } as GovernedRunSummary;
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [formal], errors: [] });
    const { result } = renderHook(useModels);
    let loaded;
    await act(async () => { loaded = await result.current.fetchModels(); });
    expect(loaded).toEqual([]);
    expect(result.current.runs).toEqual([expect.objectContaining({ key: formal.key })]);
    expect(result.current.runLoadErrors[0]).toContain('Optional legacy');
  });
  it('still rejects formal evidence with an integrity failure', async () => {
    vi.mocked(modelsApi.getDashboardDb).mockRejectedValue(new Error('Legacy unavailable'));
    vi.mocked(loadPreviewRuns).mockResolvedValue({ runs: [], errors: [] });
    vi.mocked(loadFormalRuns).mockResolvedValue({ runs: [], errors: ['manifest hash mismatch'] });
    const { result } = renderHook(useModels);
    let loaded;
    await act(async () => { loaded = await result.current.fetchModels(); });
    expect(loaded).toBeNull();
    expect(result.current.runs).toEqual([]);
    expect(result.current.runLoadErrors[0]).toContain('manifest hash mismatch');
  });
});
