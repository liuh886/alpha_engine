import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useModelRanking } from '@/hooks/useModelRanking';
import { StrategyFleet } from './StrategyFleet';
import type { GovernedRunSummary } from '@/lib/governed-run';
import {
  indexRowsFromBars,
  strategyRowsFromNav,
  type ModelRankingRow,
} from '@/lib/model-ranking';
import type { SecurityBar } from '@/lib/security-evidence';
import type { StrategyOperationsSnapshot } from '@/lib/strategy-operations';
import type { ReportRow } from '@/lib/types';

vi.mock('@/hooks/useModelRanking', () => ({ useModelRanking: vi.fn() }));

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
  evidenceCutoff: '2026-11-12',
});

function nav(points: Array<[string, number]>): ReportRow[] {
  return points.map(([date, account]) => ({ date, account }));
}

function bar(time: string, close: number): SecurityBar {
  return { time, open: close, high: close, low: close, close, volume: 1000 };
}

const ROWS: ModelRankingRow[] = [
  strategyRowsFromNav(US_RUN, nav([['2026-10-11', 100], ['2026-11-11', 110]]), {
    excess: { value: 0.25, source: 'retained', label: 'retained', basis: 'Retained formal excess metric.' },
  })[0],
  strategyRowsFromNav(CN_RUN, nav([['2023-09-01', 100], ['2026-09-04', 140]]), {
    excess: { value: null, source: 'unavailable', label: 'Excess unavailable', basis: '', reason: 'Not retained.' },
  })[0],
  indexRowsFromBars('us', 'QQQ', 'QQQ', [
    bar('2026-11-04', 110), bar('2026-11-06', 116), bar('2026-11-11', 121),
  ], '2026-11-12')[0],
  indexRowsFromBars('cn', '000300', 'CSI 300', [
    bar('2026-11-04', 3980), bar('2026-11-06', 4010), bar('2026-11-11', 4043.93),
  ], '2026-11-12')[0],
];

function snapshot(overrides: Partial<StrategyOperationsSnapshot> = {}): StrategyOperationsSnapshot {
  return {
    strategyId: 'us_x',
    modelVersionId: 'us_x1_3',
    status: 'target_pending_execution',
    asOf: '2026-11-11',
    latestCompletedSession: '2026-11-11',
    decisionCadence: 'Every 10 provider sessions',
    nextDecision: 'Next rebalance',
    stateLabel: 'Rebalance target',
    decisionReason: 'New target exposure',
    allocations: [{ asset: 'AAPL', current: 0.1, target: 0.2, delta: 0.1 }],
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
    ...overrides,
  };
}

const SNAPSHOTS = new Map<string, StrategyOperationsSnapshot>([
  ['us_x1_3', snapshot()],
  ['cn_27_v1_3', snapshot({
    strategyId: 'cn_27',
    modelVersionId: 'cn_27_v1_3',
    status: 'stale',
    decisionReason: 'Observation delayed',
  })],
]);

function renderFleet(rows = ROWS, issues: Array<{ id: string; kind: 'strategy' | 'index'; message: string }> = []) {
  vi.mocked(useModelRanking).mockReturnValue({ rows, loading: false, issues });
  return render(
    <MemoryRouter>
      <StrategyFleet runs={[US_RUN, CN_RUN]} snapshots={SNAPSHOTS} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('StrategyFleet', () => {
  it('renders the shared full-density ranking for strategies and governed indices', () => {
    renderFleet();
    expect(screen.getByRole('region', { name: 'Formal strategy fleet' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Excess' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Max DD' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Signal' })).toBeInTheDocument();
    expect(screen.getAllByTestId(/^fleet-/)).toHaveLength(2);
    expect(screen.getAllByTestId(/^ranking-index-/)).toHaveLength(2);
    expect(screen.getByText('2 strategies · 2 governed indices')).toBeInTheDocument();
    expect(screen.getByLabelText('Market')).toBeInTheDocument();
    expect(screen.getByLabelText('Signal filter')).toBeInTheDocument();
    for (const label of ['1W', '1M', '3M', '1Y', '2Y', '3Y']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('filters by market without dropping the governed indices of that market', () => {
    renderFleet();
    fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'us' } });
    expect(screen.getByTestId('fleet-us_x1_3')).toBeInTheDocument();
    expect(screen.getByTestId('ranking-index-us-QQQ')).toBeInTheDocument();
    expect(screen.queryByTestId('fleet-cn_27_v1_3')).not.toBeInTheDocument();
    expect(screen.queryByTestId('ranking-index-cn-000300')).not.toBeInTheDocument();
    expect(screen.getByText('1 strategies · 1 governed indices')).toBeInTheDocument();
  });

  it('filters new and attention signals and explains an empty result', () => {
    renderFleet();
    fireEvent.change(screen.getByLabelText('Signal filter'), { target: { value: 'attention' } });
    expect(screen.getByTestId('fleet-cn_27_v1_3')).toBeInTheDocument();
    expect(screen.queryByTestId('fleet-us_x1_3')).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'us' } });
    expect(screen.getByText('No strategies match these filters.')).toBeInTheDocument();
  });

  it('opens the existing signal drawer from the shared signal cell', () => {
    renderFleet();
    fireEvent.click(screen.getByRole('button', { name: 'Inspect signal for US x1.3: Increase' }));
    expect(screen.getByRole('heading', { name: 'US x1.3' })).toBeInTheDocument();
    expect(screen.getAllByText('New target exposure').length).toBeGreaterThanOrEqual(1);
  });

  it('passes scoped read issues through without hiding healthy rows', () => {
    renderFleet(ROWS, [{ id: 'us_x1_3', kind: 'strategy', message: 'US x1.3: ranking evidence unavailable (missing).' }]);
    expect(screen.getByRole('list', { name: 'Model ranking read issues' }))
      .toHaveTextContent('US x1.3: ranking evidence unavailable (missing).');
    expect(screen.getByTestId('fleet-cn_27_v1_3')).toBeInTheDocument();
    expect(screen.getByTestId('ranking-index-us-QQQ')).toBeInTheDocument();
  });

  it('keeps stale evidence visible and does not use a shared as-of date', () => {
    renderFleet();
    const stale = screen.getByTestId('fleet-cn_27_v1_3');
    expect(within(stale).getByTestId('stale-cn_27_v1_3')).toHaveTextContent('Stale · 69d behind cutoff');
    expect(within(stale).getByText('As of 2026-09-04')).toBeInTheDocument();
    expect(within(screen.getByTestId('fleet-us_x1_3')).getByText('As of 2026-11-11')).toBeInTheDocument();
  });
});
