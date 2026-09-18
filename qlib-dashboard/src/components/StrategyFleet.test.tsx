import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { StrategyFleet } from './StrategyFleet';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { StrategyOperationsSnapshot } from '@/lib/strategy-operations';

vi.mock('@/hooks/useAccessControl', () => ({
  useAccessControl: () => ({
    requiredTier: () => 'public',
    canAccess: () => true,
    policyLoading: false,
  }),
}));

const mockRuns: GovernedRunSummary[] = [
  {
    key: 'us_x1_3',
    modelFamilyId: 'us_ranker',
    modelVersionId: 'us_x1_3',
    runId: 'us_x1_3-formal',
    bundleId: 'bundle-us',
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
    summary: {
      metrics: [
        {
          metric_id: 'total_return',
          value: 0.25,
          availability_status: 'available',
        },
        {
          metric_id: 'excess_return',
          value: 0.1,
          availability_status: 'available',
        },
        {
          metric_id: 'max_drawdown',
          value: -0.15,
          availability_status: 'available',
        },
        {
          metric_id: 'sharpe_ratio',
          value: 1.25,
          availability_status: 'available',
        },
      ],
    },
    manifest: null,
    modelData: null,
    formalPackage: null,
    loadWarnings: [],
  },
  {
    key: 'byd_v1_3',
    modelFamilyId: 'byd_allocation',
    modelVersionId: 'byd_v1_3',
    runId: 'byd_v1_3-formal',
    bundleId: 'bundle-cn',
    title: 'BYD v1.3',
    modelKind: 'rules_based_allocation',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'cn',
    benchmark: 'BYD v1.2',
    generatedAt: '2026-09-09',
    evidenceCutoff: '2026-09-09',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: null,
    manifestSha256: null,
    summary: {
      metrics: [
        {
          metric_id: 'total_return',
          value: 0.45,
          availability_status: 'available',
        },
        {
          metric_id: 'excess_return',
          value: 0.08,
          availability_status: 'available',
        },
        {
          metric_id: 'max_drawdown',
          value: -0.2,
          availability_status: 'available',
        },
        {
          metric_id: 'sharpe_ratio',
          value: 0.95,
          availability_status: 'available',
        },
      ],
    },
    manifest: null,
    modelData: null,
    formalPackage: null,
    loadWarnings: [],
  },
];

const mockSnapshots = new Map<string, StrategyOperationsSnapshot>([
  [
    'us_x1_3',
    {
      strategyId: 'us_x',
      modelVersionId: 'us_x1_3',
      status: 'target_pending_execution',
      asOf: '2026-09-09',
      latestCompletedSession: '2026-09-09',
      decisionCadence: 'Every 10 provider sessions',
      nextDecision: 'Next rebalance',
      stateLabel: 'Rebalance target',
      decisionReason: 'New target exposure',
      allocations: [
        { asset: 'AAPL', current: 0.1, target: 0.2, delta: 0.1 },
      ],
      turnover: 0.1,
      estimatedCost: 0.001,
      dataFreshness: 'current',
      factorFreshness: 'current',
      deliveryStatus: 'published',
      sourceLabel: 'Governed run',
      sourceHref: null,
      note: 'New target',
      factorEvidence: [],
      sourceIdentity: {
        formalBundleId: null,
        formalRunId: null,
        formalEvidenceCutoff: null,
        ledgerFingerprint: null,
        signalSha256: null,
        factorCatalogImplementationHash: null,
        workflowRunId: null,
        commitSha: null,
        githubIssueNumber: null,
      },
    },
  ],
  [
    'byd_v1_3',
    {
      strategyId: 'byd',
      modelVersionId: 'byd_v1_3',
      status: 'current_no_change',
      asOf: '2026-09-09',
      latestCompletedSession: '2026-09-09',
      decisionCadence: 'Every completed CN session',
      nextDecision: 'Next eligible session',
      stateLabel: 'Hold positions',
      decisionReason: 'Position unchanged',
      allocations: [
        { asset: 'BYD', current: 0.75, target: 0.75, delta: 0.0 },
      ],
      turnover: 0.0,
      estimatedCost: 0.0,
      dataFreshness: 'current',
      factorFreshness: 'current',
      deliveryStatus: 'published',
      sourceLabel: 'Governed run',
      sourceHref: null,
      note: 'Hold',
      factorEvidence: [],
      sourceIdentity: {
        formalBundleId: null,
        formalRunId: null,
        formalEvidenceCutoff: null,
        ledgerFingerprint: null,
        signalSha256: null,
        factorCatalogImplementationHash: null,
        workflowRunId: null,
        commitSha: null,
        githubIssueNumber: null,
      },
    },
  ],
]);

function renderFleet() {
  return render(
    <MemoryRouter>
      <StrategyFleet runs={mockRuns} snapshots={mockSnapshots} />
    </MemoryRouter>,
  );
}

describe('StrategyFleet', () => {
  it('renders all strategies in stable watchlist order', () => {
    renderFleet();
    expect(screen.getByText('US x1.3')).toBeInTheDocument();
    expect(screen.getByText('BYD v1.3')).toBeInTheDocument();
    expect(screen.getByText(/2 strategies · Stable watchlist order/)).toBeInTheDocument();
  });

  it('filters strategies by market selection', () => {
    renderFleet();
    const marketSelect = screen.getByRole('combobox', { name: 'Market' });

    fireEvent.change(marketSelect, { target: { value: 'us' } });
    expect(screen.getByText('US x1.3')).toBeInTheDocument();
    expect(screen.queryByText('BYD v1.3')).not.toBeInTheDocument();
    expect(screen.getByText(/1 strategies · Stable watchlist order/)).toBeInTheDocument();

    fireEvent.change(marketSelect, { target: { value: 'cn' } });
    expect(screen.queryByText('US x1.3')).not.toBeInTheDocument();
    expect(screen.getByText('BYD v1.3')).toBeInTheDocument();
  });

  it('filters strategies by signal state', () => {
    renderFleet();
    const signalSelect = screen.getByRole('combobox', { name: 'Signal filter' });

    // Filter to new signals (US x1.3 has delta > 0, so isNew is true)
    fireEvent.change(signalSelect, { target: { value: 'new' } });
    expect(screen.getByText('US x1.3')).toBeInTheDocument();
    expect(screen.queryByText('BYD v1.3')).not.toBeInTheDocument();

    // Filter to attention (neither is attention in mock data)
    fireEvent.change(signalSelect, { target: { value: 'attention' } });
    expect(screen.queryByText('US x1.3')).not.toBeInTheDocument();
    expect(screen.queryByText('BYD v1.3')).not.toBeInTheDocument();
    expect(screen.getByText('No strategies match these filters.')).toBeInTheDocument();
  });

  it('opens StrategySignalDrawer when signal badge is clicked', () => {
    renderFleet();
    // Click inspect signal for US x1.3
    const signalButton = screen.getByRole('button', { name: /inspect signal for us x1.3/i });
    fireEvent.click(signalButton);

    expect(screen.getByText('Operational Signal & Targets')).toBeInTheDocument();
    expect(screen.getAllByText('New target exposure').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('heading', { name: 'US x1.3' })).toBeInTheDocument();
  });
});
