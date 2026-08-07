import type { GovernedRunSummary } from './governed-run';
import { fetchBydRuntimeSnapshot, type BydSignalRecord } from './byd-runtime';
import { fetchV42RuntimeSnapshot, type V42EventRecord, type V42ObservationRecord } from './v42-runtime';

export type StrategyOperationalStatus =
  | 'pipeline_unavailable'
  | 'awaiting_observation'
  | 'current_no_change'
  | 'target_pending_execution'
  | 'execution_observed'
  | 'stale'
  | 'blocked'
  | 'delivery_failed';

export type StrategyFreshness = 'current' | 'stale' | 'blocked' | 'unknown';

export interface StrategyAllocationLeg {
  asset: string;
  current: number;
  target: number;
  delta: number;
}

export interface StrategyDriver {
  label: string;
  value: string;
}

export interface StrategyOperationsSnapshot {
  strategyId: string;
  status: StrategyOperationalStatus;
  asOf: string | null;
  latestCompletedSession: string | null;
  decisionCadence: string;
  nextDecision: string;
  stateLabel: string;
  decisionReason: string;
  allocations: StrategyAllocationLeg[];
  turnover: number | null;
  estimatedCost: number | null;
  dataFreshness: StrategyFreshness;
  factorFreshness: StrategyFreshness;
  deliveryStatus: string;
  sourceLabel: string;
  sourceHref: string | null;
  note: string;
  drivers: StrategyDriver[];
}

const QQQ_MODEL_ID = 'qqqi_qqq_tqqq_v4_2';
const BYD_MODEL_ID = 'byd_v1_2_convex_momentum_budget_v1';
const STATE_LABELS: Record<number, string> = {
  0: 'Defensive',
  1: 'Transition',
  2: 'Risk-on',
};

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function percent(value: unknown, digits = 1): string {
  return finite(value) ? `${(value * 100).toFixed(digits)}%` : '—';
}

function decimal(value: unknown, digits = 2): string {
  return finite(value) ? value.toFixed(digits) : '—';
}

function allocationLegs(current: Record<string, number>, target: Record<string, number>): StrategyAllocationLeg[] {
  return Array.from(new Set([...Object.keys(current), ...Object.keys(target)]))
    .sort()
    .map((asset) => {
      const currentWeight = finite(current[asset]) ? current[asset] : 0;
      const targetWeight = finite(target[asset]) ? target[asset] : 0;
      return {
        asset,
        current: currentWeight,
        target: targetWeight,
        delta: targetWeight - currentWeight,
      };
    });
}

function hasAllocationChange(allocations: StrategyAllocationLeg[]): boolean {
  return allocations.some((leg) => Math.abs(leg.delta) > 1e-9);
}

function unavailable(run: GovernedRunSummary, status: StrategyOperationalStatus, note: string): StrategyOperationsSnapshot {
  return {
    strategyId: run.modelVersionId,
    status,
    asOf: null,
    latestCompletedSession: run.evidenceCutoff || null,
    decisionCadence: run.modelKind === 'cross_sectional_ranker' ? 'Every 10 trading sessions' : 'Model-defined cadence',
    nextDecision: status === 'pipeline_unavailable' ? 'Signal publication not implemented' : 'Awaiting first valid observation',
    stateLabel: status === 'pipeline_unavailable' ? 'No governed live signal' : 'Awaiting observation',
    decisionReason: note,
    allocations: [],
    turnover: null,
    estimatedCost: null,
    dataFreshness: 'unknown',
    factorFreshness: 'unknown',
    deliveryStatus: 'not available',
    sourceLabel: 'Formal model evidence only',
    sourceHref: null,
    note,
    drivers: [],
  };
}

function qqqSnapshot(run: GovernedRunSummary, record: V42EventRecord, observation: V42ObservationRecord | null, issueUrl: string): StrategyOperationsSnapshot {
  const allocations = allocationLegs(record.current_weights, record.target_weights);
  const changed = hasAllocationChange(allocations);
  const executionObserved = Boolean(observation?.execution?.execution_date);
  const deliveryStatus = String(record.delivery?.telegram_status ?? record.delivery?.telegram ?? 'not declared');
  const deliveryFailed = deliveryStatus === 'failed';
  const status: StrategyOperationalStatus = deliveryFailed
    ? 'delivery_failed'
    : !record.data_freshness_ok
      ? 'stale'
      : changed && !executionObserved
        ? 'target_pending_execution'
        : changed && executionObserved
          ? 'execution_observed'
          : 'current_no_change';
  const features = record.signal_close_features;
  const stateFrom = STATE_LABELS[record.current_state] ?? `State ${record.current_state}`;
  const stateTo = STATE_LABELS[record.target_state] ?? `State ${record.target_state}`;

  return {
    strategyId: run.modelVersionId,
    status,
    asOf: record.signal_date,
    latestCompletedSession: observation?.as_of_data_date ?? record.latest_data_date_at_creation,
    decisionCadence: 'Daily close evaluation',
    nextDecision: 'Next completed US market close',
    stateLabel: record.current_state === record.target_state ? stateTo : `${stateFrom} → ${stateTo}`,
    decisionReason: record.decision_reason || 'No decision reason retained.',
    allocations,
    turnover: finite(record.turnover_units) ? record.turnover_units : null,
    estimatedCost: finite(record.estimated_transaction_cost) ? record.estimated_transaction_cost : null,
    dataFreshness: record.data_freshness_ok ? 'current' : 'stale',
    factorFreshness: 'unknown',
    deliveryStatus,
    sourceLabel: 'Governed QQQ state-change ledger',
    sourceHref: issueUrl,
    note: executionObserved
      ? `Next-open execution evidence observed ${observation?.execution?.execution_date}.`
      : changed
        ? 'Target is awaiting next-open execution evidence.'
        : 'Latest governed evaluation retained the existing allocation.',
    drivers: [
      { label: 'VIX close', value: decimal(features.vix_close) },
      { label: 'VIX 5D', value: percent(features.vix_return_5d, 2) },
      { label: 'VXN close', value: decimal(features.vxn_close) },
      { label: 'VXN 5D', value: percent(features.vxn_return_5d, 2) },
      { label: 'QQQ vs MA20', value: percent(features.qqq_distance_ma_short, 2) },
    ],
  };
}

function bydSnapshot(run: GovernedRunSummary, record: BydSignalRecord, issueUrl: string): StrategyOperationsSnapshot {
  const allocations = allocationLegs(record.current_weights, record.target_weights);
  const changed = hasAllocationChange(allocations);
  const status: StrategyOperationalStatus = !record.data_freshness_ok
    ? 'stale'
    : changed
      ? 'target_pending_execution'
      : 'current_no_change';

  return {
    strategyId: run.modelVersionId,
    status,
    asOf: record.signal_date,
    latestCompletedSession: record.latest_data_date,
    decisionCadence: 'Daily close evaluation',
    nextDecision: 'Next eligible BYD market close',
    stateLabel: record.target_mode_label || record.target_mode,
    decisionReason: record.transition_label || record.transition_type,
    allocations,
    turnover: finite(record.turnover_units) ? record.turnover_units : null,
    estimatedCost: finite(record.estimated_transaction_cost) ? record.estimated_transaction_cost : null,
    dataFreshness: record.data_freshness_ok ? 'current' : 'stale',
    factorFreshness: 'unknown',
    deliveryStatus: record.should_alert ? 'alert required' : 'not required',
    sourceLabel: 'Governed BYD signal ledger',
    sourceHref: issueUrl,
    note: changed
      ? 'Target allocation is published; brokerage execution is outside Alpha Engine.'
      : 'Latest governed evaluation retained the existing allocation.',
    drivers: [
      { label: 'Market state', value: record.factor_context.market_state || '—' },
      { label: 'Volatility state', value: record.factor_context.vol_state || '—' },
      { label: '20D momentum', value: percent(record.factor_context.mom_20, 2) },
      { label: '60D momentum', value: percent(record.factor_context.mom_60, 2) },
      { label: '252D drawdown', value: percent(record.factor_context.drawdown_252, 2) },
      { label: 'Financed increment', value: percent(record.factor_context.financed_increment, 2) },
    ],
  };
}

async function loadOne(run: GovernedRunSummary): Promise<StrategyOperationsSnapshot> {
  if (run.modelVersionId === QQQ_MODEL_ID) {
    try {
      const snapshot = await fetchV42RuntimeSnapshot();
      const event = snapshot.latestStateChange;
      if (!event) return unavailable(run, 'awaiting_observation', 'No governed QQQ state-change record is available.');
      return qqqSnapshot(run, event.record, snapshot.observation, event.issue.html_url);
    } catch (error) {
      return unavailable(run, 'blocked', error instanceof Error ? error.message : 'QQQ operating evidence is unavailable.');
    }
  }

  if (run.modelVersionId === BYD_MODEL_ID) {
    try {
      const snapshot = await fetchBydRuntimeSnapshot();
      const event = snapshot.latestSignal;
      if (!event) return unavailable(run, 'awaiting_observation', 'BYD signal pipeline is waiting for its first valid production observation.');
      return bydSnapshot(run, event.record, event.issue.html_url);
    } catch (error) {
      return unavailable(run, 'blocked', error instanceof Error ? error.message : 'BYD operating evidence is unavailable.');
    }
  }

  return unavailable(
    run,
    'pipeline_unavailable',
    'This accepted formal model does not yet publish a governed live/rebalance signal. Historical formal evidence remains available.',
  );
}

export async function loadStrategyOperations(runs: GovernedRunSummary[]): Promise<Map<string, StrategyOperationsSnapshot>> {
  const formalRuns = runs.filter((run) => run.channel === 'formal');
  const snapshots = await Promise.all(formalRuns.map(loadOne));
  return new Map(snapshots.map((snapshot) => [snapshot.strategyId, snapshot]));
}

export const STRATEGY_STATUS_LABEL: Record<StrategyOperationalStatus, string> = {
  pipeline_unavailable: 'Signal unavailable',
  awaiting_observation: 'Awaiting observation',
  current_no_change: 'Current · no change',
  target_pending_execution: 'New target',
  execution_observed: 'Execution observed',
  stale: 'Stale data',
  blocked: 'Operating data blocked',
  delivery_failed: 'Delivery failed',
};
