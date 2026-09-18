import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { StrategySignalDrawer } from './StrategySignalDrawer';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { StrategyOperationsSnapshot } from '@/lib/strategy-operations';

const mockRun: GovernedRunSummary = {
  key: 'us_x1_3',
  modelFamilyId: 'us_ranker',
  modelVersionId: 'us_x1_3',
  runId: 'us_x1_3-formal',
  bundleId: 'bundle-123',
  title: 'US x1.3',
  modelKind: 'cross_sectional_ranker',
  channel: 'formal',
  publicationStatus: 'accepted_formal_baseline',
  market: 'us',
  benchmark: 'QQQ',
  generatedAt: '2026-09-09',
  evidenceCutoff: '2026-09-09',
  evidenceStatus: 'complete',
  decisionStatus: 'supported',
  manifestPath: null,
  manifestSha256: null,
  summary: { metrics: [] },
  manifest: null,
  modelData: null,
  formalPackage: null,
  loadWarnings: [],
};

const mockSnapshot: StrategyOperationsSnapshot = {
  strategyId: 'us_x',
  modelVersionId: 'us_x1_3',
  status: 'target_pending_execution',
  asOf: '2026-09-09',
  latestCompletedSession: '2026-09-09',
  decisionCadence: 'Every 10 provider sessions',
  nextDecision: 'Publish on rebalance session',
  stateLabel: 'Rebalance target',
  decisionReason: 'Sector capped target rebalance',
  allocations: [
    { asset: 'AAPL', current: 0.1, target: 0.15, delta: 0.05 },
    { asset: 'MSFT', current: 0.15, target: 0.1, delta: -0.05 },
  ],
  turnover: 0.1,
  estimatedCost: 0.001,
  dataFreshness: 'current',
  factorFreshness: 'current',
  deliveryStatus: 'published',
  sourceLabel: 'Governed run',
  sourceHref: null,
  note: 'Active targets',
  factorEvidence: [
    {
      factorId: 'alpha158.corr',
      factorVersion: '1.0',
      implementationHash: 'a'.repeat(64),
      displayName: 'Price Volume Corr',
      informationFamily: 'technical',
      value: 0.1234,
      reference: null,
      state: 'positive',
      effect: 'support',
      reasonCode: 'corr_high',
      observedAt: '2026-09-09',
    },
  ],
  sourceIdentity: {
    formalBundleId: 'bundle-123',
    formalRunId: 'run-123',
    formalEvidenceCutoff: '2026-09-09',
    ledgerFingerprint: 'ledger-abc',
    signalSha256: 'sig-sha',
    factorCatalogImplementationHash: null,
    workflowRunId: '12345',
    commitSha: 'commit-abc',
    githubIssueNumber: 325,
  },
};

describe('StrategySignalDrawer', () => {
  it('renders operational signal with title and targets when open', () => {
    render(
      <MemoryRouter>
        <StrategySignalDrawer
          run={mockRun}
          snapshot={mockSnapshot}
          open={true}
          onOpenChange={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('Operational Signal & Targets')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'US x1.3' })).toBeInTheDocument();
    expect(screen.getByText('Sector capped target rebalance')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.getByText('+5.0%')).toBeInTheDocument();
    expect(screen.getByText('-5.0%')).toBeInTheDocument();
  });

  it('renders fallback when allocations are empty', () => {
    const emptySnapshot: StrategyOperationsSnapshot = {
      ...mockSnapshot,
      allocations: [],
    };

    render(
      <MemoryRouter>
        <StrategySignalDrawer
          run={mockRun}
          snapshot={emptySnapshot}
          open={true}
          onOpenChange={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('First target / no prior comparison record')).toBeInTheDocument();
  });

  it('expands governed evidence details on toggle click', () => {
    render(
      <MemoryRouter>
        <StrategySignalDrawer
          run={mockRun}
          snapshot={mockSnapshot}
          open={true}
          onOpenChange={vi.fn()}
        />
      </MemoryRouter>,
    );

    const toggleButton = screen.getByRole('button', { name: /view governed evidence details/i });
    expect(toggleButton).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(toggleButton);
    expect(toggleButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Price Volume Corr')).toBeInTheDocument();
    expect(screen.getByText(/ledger-abc/)).toBeInTheDocument();
  });

  it('calls onOpenChange when close button is clicked', () => {
    const onOpenChange = vi.fn();
    render(
      <MemoryRouter>
        <StrategySignalDrawer
          run={mockRun}
          snapshot={mockSnapshot}
          open={true}
          onOpenChange={onOpenChange}
        />
      </MemoryRouter>,
    );

    const closeButtons = screen.getAllByRole('button', { name: 'Close' });
    expect(closeButtons.length).toBeGreaterThan(0);
    fireEvent.click(closeButtons[0]);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
