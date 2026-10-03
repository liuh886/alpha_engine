import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useModels } from './useModels';
import { modelsApi } from '@/api/modelsApi';
import { loadFormalRuns, loadPreviewRuns, type GovernedRunSummary } from '@/lib/governed-run';

vi.mock('@/api/modelsApi', () => ({ modelsApi: { getDashboardDb: vi.fn() } }));
vi.mock('@/lib/governed-run', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/governed-run')>(),
  loadFormalRuns: vi.fn(), loadPreviewRuns: vi.fn(),
}));

describe('formal workspace bootstrap', () => {
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
