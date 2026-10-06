import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { OpenedResearchBundle } from '@/lib/research-bundle';
import type { DataReadinessEvidence } from '@/lib/artifact-data';
import { loadDataReadinessEvidence } from '@/lib/artifact-data';
import { EvidenceDataPage } from './EvidenceDataPage';

const state = vi.hoisted(() => ({ bundle: null as OpenedResearchBundle | null }));
vi.mock('@/hooks/useActiveResearchBundle', () => ({ useActiveResearchBundle: () => state.bundle }));
vi.mock('@/lib/artifact-data', async (original) => ({
  ...await original<typeof import('@/lib/artifact-data')>(), loadDataReadinessEvidence: vi.fn(),
}));
function bundle(id: string): OpenedResearchBundle {
  return {
    manifest: { schema_version: '1.0', frontend_reader_range: '*', bundle_id: id, title: id,
      generated_at: '2026-10-07T00:00:00Z', evidence_cutoff: null, research_only: true,
      trade_ready: false, scope: { markets: ['us'], model_count: 0 }, warnings: [],
      blocked_gates: [], promotion_decision: 'research_only', artifacts: [] },
    dashboard: { generated_at: null, snapshot_id: id, models: [] },
    source: { label: id, read: vi.fn() }, integrity: 'all_verified',
  };
}
function evidence(cutoff = '2026-10-05'): DataReadinessEvidence {
  return { readiness: { schema_version: '1.1', bundle_id: 'model-data', built_at: '2026-10-07T00:00:00Z',
    evidence_cutoff: cutoff, research_only: true, trade_ready: false,
    summary: { component_count: 0, ready_component_count: 0, partial_component_count: 0,
      blocked_component_count: 0, ready_training_profiles: [], blocked_training_profiles: [] } },
    components: [], profiles: [] };
}
describe('EvidenceDataPage asynchronous evidence', () => {
  beforeEach(() => { vi.resetAllMocks(); state.bundle = bundle('first'); });
  it('keeps absence distinct from a pending integrity check', async () => {
    let resolve!: (value: DataReadinessEvidence | null) => void;
    vi.mocked(loadDataReadinessEvidence).mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<EvidenceDataPage />);
    expect(screen.getByRole('status')).toHaveTextContent('Checking data readiness');
    expect(screen.queryByText(/does not declare model-data/)).not.toBeInTheDocument();
    await act(async () => { resolve(null); });
    expect(screen.getByText(/does not declare model-data/)).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
  it('retries a rejected read without treating it as missing evidence', async () => {
    vi.mocked(loadDataReadinessEvidence).mockRejectedValueOnce(new Error('Artifact digest mismatch'))
      .mockResolvedValueOnce(evidence());
    render(<EvidenceDataPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Artifact digest mismatch');
    fireEvent.click(screen.getByRole('button', { name: 'Retry readiness check' }));
    expect(await screen.findByText('2026-10-05')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(loadDataReadinessEvidence).toHaveBeenCalledTimes(2);
  });
  it('ignores a previous bundle response after switching bundles', async () => {
    let resolveFirst!: (value: DataReadinessEvidence) => void;
    let resolveSecond!: (value: DataReadinessEvidence) => void;
    vi.mocked(loadDataReadinessEvidence)
      .mockReturnValueOnce(new Promise((done) => { resolveFirst = done; }))
      .mockReturnValueOnce(new Promise((done) => { resolveSecond = done; }));
    const view = render(<EvidenceDataPage />);
    state.bundle = bundle('second'); view.rerender(<EvidenceDataPage />);
    await act(async () => { resolveSecond(evidence()); resolveFirst(evidence('2026-09-30')); });
    expect(screen.getByText('2026-10-05')).toBeInTheDocument();
    expect(screen.queryByText('2026-09-30')).not.toBeInTheDocument();
  });
  it('hides settled evidence immediately when the bundle changes', async () => {
    vi.mocked(loadDataReadinessEvidence).mockResolvedValueOnce(evidence('2026-09-30'))
      .mockReturnValueOnce(new Promise(() => {}));
    const view = render(<EvidenceDataPage />);
    await screen.findByText('2026-09-30');
    state.bundle = bundle('second'); view.rerender(<EvidenceDataPage />);
    expect(screen.queryByText('2026-09-30')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Checking data readiness');
  });
});
